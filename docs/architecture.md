# Architecture

This document describes how PhoneVision Lab is organized. It is written to be
readable for learners — it explains the *why* of each layer, not just the what.

## System overview

```
 ┌─────────────────────┐   MJPEG over HTTP (WiFi)   ┌──────────────────────────┐
 │   Android phone     │  ───────────────────────►  │   Windows PC             │
 │                     │                            │                          │
 │  Camera2 +          │    GET /stream             │  mjpeg_reader (parser)   │
 │  ImageReader(JPEG)  │    multipart/x-mixed-      │        │                 │
 │        │            │    replace                 │        ▼                 │
 │  NanoHTTPD server   │    GET /ping  (JSON)       │  app_model (state/stats) │
 └─────────────────────┘                            │        │                 │
                                                    │        ▼                 │
                                                    │  PySide6 workbench       │
                                                    │  (VideoView + inspector) │
                                                    │  vision_modes: original  │
                                                    │    gray / canny / hsv /  │
                                                    │    contours              │
                                                    └──────────────────────────┘
```

Roles:

- **Phone = sensor.** It captures frames, JPEG-encodes them, and streams them.
  It does not do image processing for the user.
- **PC = brain.** It parses the stream, applies vision modes, and shows the
  result for learning.

### Two operating modes (mutually exclusive)

```
  ┌──────────────────────────────────────────────────────────────┐
  │ Mode 1: Camera streaming (V0-A)                              │
  │   Camera2 → JPEG → LatestFrameStore → NanoHTTPD /stream      │
  │   Phone streams; PC receives, processes, displays.           │
  ├──────────────────────────────────────────────────────────────┤
  │ Mode 2: On-device AI inference (V0-B)                        │
  │   Camera2 → JPEG → Bitmap → InferenceEngine (TFLite)         │
  │                              │                               │
  │                              ├─► Preview + prediction + perf │
  │                              └─► RuleEngine → DeviceAdapter  │
  │                                       │                      │
  │                                       ▼  HTTP :8081          │
  │                              External controller (LED etc.)  │
  └──────────────────────────────────────────────────────────────┘
```

The two modes are **mutually exclusive**: entering inference mode stops the
MJPEG server, because opening two camera capture sessions at once fails on most
older phones.

### Why TensorFlow Lite (and not ONNX Runtime)

Both were checked against the project's `minSdk = 21` (Android 5.0) target:

| Runtime | AAR `minSdk` | Verdict |
| --- | --- | --- |
| TensorFlow Lite 2.16.1 | **19** | Compatible — keeps Android 5.0 support |
| ONNX Runtime Android 1.31.1 | 24 | Would raise `minSdk` to 7.0, breaking the old-phone goal |

TFLite also ships all four ABIs (`arm64-v8a`, `armeabi-v7a`, `x86`, `x86_64`).
Acceleration is **CPU-only by default**: NNAPI/GPU delegates behave very
differently across vendor ROMs and have not been validated device by device, so
enabling them would be an unverified claim. `Config.USE_NNAPI = false`.

## Repositories / top-level directories

| Path | Role |
| --- | --- |
| `android/` | Sensor app: Camera2 live preview, JPEG capture, NanoHTTPD MJPEG server (`/ping`, `/stream`); on-device TFLite inference + hardware control |
| `pc-client/` | Windows client: strict MJPEG reader, OpenCV vision modes, PySide6 workbench (dataset / train / hardware / perf tabs), legacy Tkinter client; also the shared training/dataset/hardware modules |
| `web/` | Local web build of the same learning loop: `launcher.py` + `server/` (stdlib HTTP API) + `static/` (no-build ES modules). Reuses `pc-client` modules instead of reimplementing them |
| `web-prototype/` | Archived v1 static design prototype; not referenced at runtime |
| `controller-firmware/` | ESP32 Arduino firmware: HTTP control endpoint driving a real LED |
| `docs/` | Architecture, protocol, hardware, training, troubleshooting, release checklist, Qt/LGPL compliance, web platform |
| `packaging/` (under pc-client) | PyInstaller spec, portable README, third-party license bundle |
| `.github/` | CI workflows, issue templates and pull request template |

## Web platform (local build)

The web build is a second front end over the **same** Python modules, not a
second implementation:

1. **`web/launcher.py`** resolves the repo root, picks a free port, starts the
   API server, and prints/opens `http://127.0.0.1:<port>`. It is the only process
   the user starts.
2. **`web/server/app.py`** is a small `ThreadingHTTPServer` router: every call
   returns `{ok: true, data}` or `{ok: false, error: {code, message}}`, so the
   front end can map a code to the next action instead of parsing prose.
3. **Domain modules** (`dataset.py`, `training.py`, `hardware.py`,
   `performance.py`, `device.py`) import `pvl_dataset`, `pvl_train`,
   `pvl_hardware`, `pvl_perf` and `connection` from `pc-client`. Any behaviour
   change belongs in those modules, not in two places.
4. **`web/static/`** is plain ES modules with no build step: one module per page,
   each returning a `cleanup` function so polling and capture loops stop when the
   route changes.

Trust boundary: the server binds `127.0.0.1` only and, on top of that, rejects
requests whose `Host`/`Origin` do not match the local origin — a page on the open
internet must not be able to drive a local dataset/training API. There is still no
account system; treat it as a single-user local tool.

## Data flow (PC side)

1. **`mjpeg_reader.py`** — background thread fetches `GET /stream` and parses the
   `multipart/x-mixed-replace` body strictly: it matches the boundary and
   `Content-Length`, validates JPEG SOI/EOI markers, and only keeps the **latest**
   frame. Dropping stale frames means latency never accumulates even if the
   consumer is slow.
2. **`app_model.py`** — the single source of truth for connection state, frame
   counters, FPS, and errors. The UI reads snapshots from it; the reader thread
   feeds it. It owns lifecycle (start/stop/reconnect) and reports whether the
   stream is stale.
3. **`qt_client/main_window.py`** — builds the workbench UI: top bar (brand,
   device, status pill, language selector, save/reconnect), the large `VideoView`
   (frame area), the right-hand inspector (five modes + parameter sliders +
   teaching hint), and a collapsible diagnostics panel.
4. **`vision_modes.py`** — pure functions that transform one BGR frame:
   `original`, `gray`, `canny`, `hsv` (mask), `contours`. Parameters (thresholds,
   HSV ranges, min area) live in `DEFAULT_PARAMS` and drive each mode.
5. **`qt_client/connection_dialog.py`** — the double-click launch page: enter the
   phone IP/port, `/ping` precheck in a worker thread, then hand the stream URL to
   the main window.

## Learning / inference pipeline (V0-B)

The closed loop is **capture → train → export → on-device inference → hardware →
performance**. Every stage is a separate module with no GUI dependency, so each
one is unit-testable without a phone.

```
  pvl_paths.py       user data dirs (datasets / runs / models / exports)
        │
  pvl_dataset.py     DatasetStore: create/open/save, classes, capture batches
        │
  pvl_split.py       split by BATCH (never by single frame) + data health check
        │
  pvl_preprocess.py  THE preprocessing contract (single source of truth)
        │
  pvl_train.py       MobileNetV3Small transfer learning (TensorFlow, CPU/GPU)
        │
  pvl_export.py      Keras → TFLite + fixed-sample consistency check + .pvlmodel.zip
        │
        ├──► Android: Preprocessor.kt (mirrors pvl_preprocess field by field)
        │             ModelPackage.kt (import + validate against manifest)
        │             InferenceEngine.kt (TFLite, CPU, perf counters)
        │
        └──► pvl_hardware.py   RuleEngine + DeviceAdapter (PC side, same rules)
                    │
                    ▼
             Controller firmware (ESP32) → real LED
```

### Layering rule: hardware never touches the camera

The vision → hardware path is strictly separated:

| Layer | Responsibility | Must NOT do |
| --- | --- | --- |
| Vision result | class, confidence, timestamp | decide anything |
| Rule engine | decide whether an action is warranted | send commands |
| Device adapter | connect, send, dedup, timeout, disconnect | know about cameras or UI |
| Firmware | actuate and report | know about models |

Hardware communication is **never** written inside a camera callback or a UI
refresh function. On Android, `InferenceActivity.maybeDriveHardware()` is the only
place that wires the rule engine to the adapter.

### Dataset splitting: why by batch

Random per-frame splitting inflates validation metrics: frames captured a few
milliseconds apart are near-identical, so the validation set would have already
"seen" the training data. Splitting is therefore done **per capture batch** — all
frames from one burst go entirely to train or entirely to val. With only one
batch per class the split is refused rather than faked.

### Performance measurement

Stages are measured separately and never mixed: phone capture FPS, PC receive
FPS, PC display FPS, phone inference FPS, and preprocess / model / postprocess
timings each have their own counter. All local intervals use a monotonic clock.
**Phone and PC wall-clock timestamps are never subtracted** — the two devices are
not synchronised, so the difference has no physical meaning. Power data is shown
only when the device exposes a real source; unsupported metrics display
"不支持" rather than a fabricated number.

## UI state model

`AppSnapshot` (a dataclass in `app_model.py`) is the immutable-ish view the UI
renders from. It carries `connection_state` (Connecting/Streaming/Reconnecting/
Stopped/Error), device name, FPS counters, frame counters, and a stale flag. The
`VideoView` chooses its placeholder (connecting / reconnecting / stopped / error)
based on this snapshot — the UI never guesses state from the network directly.

## i18n

All user-facing strings live in `qt_client/i18n.py` as a `{key: (zh, en)}` table.
`Translator.text(key)` resolves the current language; switching language emits a
`language_changed` signal that UI components connect to so text re-renders in
place. Tests assert the two languages always have identical key sets and
placeholder sets.

## Concurrency notes

- The MJPEG reader runs in a background thread; the UI must never touch it
  directly. Everything crosses the thread boundary through `AppModel`/snapshot.
- Qt timers (`QTimer`, ~30fps) drive `_refresh()`; frame dedup is by frame number,
  so the same frame is never re-rendered.
- The connection dialog uses a `QThread` worker for `/ping`; a `_closed` flag
  prevents a late worker from opening a window after the dialog closes.

## Why no telemetry

The project is local-first by design: no cloud, no account, no analytics. The
privacy section of every user-facing document reflects this, and the code keeps it
that way.
