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

## Repositories / top-level directories

| Path | Role |
| --- | --- |
| `android/` | Sensor app: Camera2 live preview, JPEG capture, NanoHTTPD MJPEG server (`/ping`, `/stream`) |
| `pc-client/` | Windows client: strict MJPEG reader, OpenCV vision modes, PySide6 workbench (default), legacy Tkinter client |
| `docs/` | Architecture, protocol, troubleshooting, release checklist, Qt/LGPL compliance |
| `packaging/` (under pc-client) | PyInstaller spec, portable README, third-party license bundle |
| `.github/` | Issue templates and pull request template |

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
