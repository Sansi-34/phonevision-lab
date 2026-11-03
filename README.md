# PhoneVision Lab

> [中文文档](README.zh-CN.md)

Turn an old Android phone into a vision sensor for machine vision learning on
Windows. Stream MJPEG over WiFi, then learn image processing with OpenCV — five
vision modes, bilingual UI, fully local, no account, no telemetry.

It also closes a full learning loop: collect your own classes on the PC, train a
lightweight classifier, export a model package, run **offline inference on the
phone**, and drive real hardware (LED) from a recognition result — with measured
performance data you can export.

**Status: Pre-release / development snapshot. Not ready for v1.0.**

## System overview

```
  ┌─────────────────────┐   MJPEG over HTTP (WiFi)   ┌──────────────────────────┐
  │   Android phone     │  ───────────────────────►  │   Windows PC             │
  │  (the sensor)       │   GET /stream              │  (the workbench)         │
  │  Camera2 + JPEG     │   GET /ping  (JSON)        │  PySide6 UI + OpenCV     │
  │  NanoHTTPD server   │                            │  original / gray / canny │
  └─────────────────────┘                            │  hsv / contours          │
                                                     └──────────────────────────┘

  Mode 2 (mutually exclusive with streaming):
  ┌─────────────────────┐                            ┌──────────────────────────┐
  │  On-device AI       │  TFLite, CPU, offline      │  Train + export          │
  │  Camera → Bitmap    │ ─────────────────────────► │  dataset / split / train │
  │  → prediction       │                            │  → .pvlmodel.zip         │
  │  → rule → HTTP:8081 │ ───────────┐               └──────────────────────────┘
  └─────────────────────┘            ▼
                            External controller → real LED
```

- **Phone = sensor**: captures frames, JPEG-encodes them, pushes an MJPEG stream.
- **PC = brain**: parses the stream, applies the five vision modes, and shows the
  result for learning.
- **Phone = edge device (mode 2)**: runs a classifier locally, no network needed
  for inference, and can command an external controller over the LAN.

## What is verified to work

- Android Camera2 live preview and WiFi MJPEG streaming over HTTP
- `GET /ping` (JSON status) and `GET /stream` (multipart MJPEG) endpoints
- Windows PySide6 vision workbench (default client): top bar + live view + mode
  inspector + collapsible diagnostics, bilingual zh-CN/en
- Strict MJPEG parser (boundary + Content-Length + SOI/EOI)
- Five vision modes: Original / Gray / Canny / HSV / Contours
- Legacy Tkinter client (compatibility only): `python legacy_main.py`
- Fully local operation — no cloud, no account, no telemetry

### Learning loop (V0-B)

- **Dataset management**: create/open datasets, add and rename classes, browse and
  delete samples, capture single frames or bursts from the live stream.
- **Batch-aware splitting**: train/val split by *capture batch*, never by single
  frame, so near-identical frames cannot leak across sets. Seed and ratio recorded.
- **Data health check**: missing classes, too few samples, undecodable images and
  severe imbalance are reported instead of faked.
- **Training**: MobileNetV3Small transfer learning (CPU by default; GPU offered only
  when actually detected). Progress, loss and validation metrics are live; cancel is
  cooperative.
- **Export**: Keras → TFLite (float16) + a fixed-sample consistency check
  (max abs error and Top-1 agreement). Export is **refused** if the check fails.
- **Model package**: self-describing `.pvlmodel.zip` with model, labels, input
  size, tensor layout, colour order, scaling/crop/normalisation rules, output
  interpretation, training parameters and pretrained-weight provenance.
- **On-device inference**: import the package on the phone, preview + predicted
  class + confidence + measured inference FPS and per-stage timings. Inference runs
  fully offline after import.
- **Hardware interaction**: recognition result → rule engine → device adapter →
  controller. Consecutive-confirm, hysteresis and cooldown prevent flapping;
  commands are deduplicated by requestId; only idempotent actions retry; a stopped
  auto-control state produces no further actions.
- **Performance analysis**: per-stage mean/P50/P95, dropped frames, command ack
  latency, and CSV / summary / JSON export.

### Browser workbench (web build)

The same learning loop also runs as a local web build under `web/`:

```bash
python web/launcher.py      # prints http://127.0.0.1:<port>
```

- Dataset capture, train/export, hardware and performance pages call the **same**
  `pc-client` modules the desktop client uses — the logic is not duplicated
- Binds `127.0.0.1` only and verifies `Host`/`Origin`, so a page from the open
  internet cannot drive the local API. There is still no account system: treat it
  as a single-user local tool
- Platform notes: [docs/web-platform.zh-CN.md](docs/web-platform.zh-CN.md);
  UI specification: [docs/ui-ux-web.zh-CN.md](docs/ui-ux-web.zh-CN.md) (both Chinese)

## Getting started

```bash
# Default client (PySide6 vision workbench), Chinese or English
python main.py --host 192.168.x.x
python main.py --host 192.168.x.x --lang en

# Legacy Tkinter client (compatibility only)
python legacy_main.py --host 192.168.x.x
```

1. Start the phone app and tap **Start Streaming** first.
2. Replace `192.168.x.x` with the IP shown in the phone app (not an example IP).
   Port defaults to 8080.
3. Switch vision modes with buttons or keys 1-5; `S` saves a screenshot,
   `R` reconnects, `Ctrl+Q` quits.
4. The diagnostics panel is collapsed by default; language choice is saved locally.

Requires Python 3.12+: `pip install -r requirements.txt`.

Training needs an extra, optional dependency set (TensorFlow, ~500 MB) so that
plain preview and capture stay light:

```bash
pip install -r requirements.txt -r requirements-train.txt
```

Full walkthrough (dataset → train → export → phone inference → LED → perf):
[docs/user-guide.zh-CN.md](docs/user-guide.zh-CN.md).
Model, weights and licence details: [docs/training.zh-CN.md](docs/training.zh-CN.md).
Hardware protocol and wiring: [docs/hardware.zh-CN.md](docs/hardware.zh-CN.md).

## Runtime compatibility (checked, not assumed)

| Component | Requirement | Notes |
| --- | --- | --- |
| TFLite AAR 2.16.1 | `minSdk 19` | Compatible with the project's `minSdk 21` (Android 5.0) |
| ABIs shipped | arm64-v8a, armeabi-v7a, x86, x86_64 | Covers nearly all existing phones |
| Acceleration | **CPU only by default** | NNAPI/GPU delegates vary by vendor ROM and are not validated per device |

ONNX Runtime Android was evaluated and **not** adopted: its AAR requires
`minSdk 24`, which would drop Android 5.0/6.0 support and break the old-phone goal.

## Windows portable package (no Python required)

A `PhoneVisionLab-0.1.0-alpha.1-windows-x64.zip` (PyInstaller onedir) is produced
at build time. **Not an official release yet** — a local build artifact only.

1. Unzip and double-click `PhoneVisionLab.exe`.
2. The connection dialog opens: enter the IP shown in the phone app (not the
   example IP), port 8080 by default. The phone must be streaming first.
3. The last successful address is saved locally only (QSettings) and is editable.
4. Logs: `%LOCALAPPDATA%\PhoneVisionLab\logs\phonevision.log` (local rotation, no
   image content, no telemetry).
5. Switch Simplified Chinese / English in the top bar; the choice is saved locally.
6. Unsigned: Windows SmartScreen may warn "unknown publisher" — click "Run anyway".

Verify the ZIP checksum:

```powershell
certutil -hashfile PhoneVisionLab-0.1.0-alpha.1-windows-x64.zip SHA256
```

Running from source is still the official path (see Getting started above).
Third-party licenses and the Qt/PySide6 LGPL-3.0 compliance details are bundled in
the package (`THIRD_PARTY_NOTICES.md` + `licenses/`) and documented in
[docs/qt-lgpl-compliance.md](docs/qt-lgpl-compliance.md).

## Privacy

- Fully local: no telemetry, no analytics, no cloud, no account.
- Local logs record only version/start/connection state/errors — never image
  content, screenshots, parameter values, or secrets.
- **Caution**: the HTTP stream has **no authentication**. Anyone on the same LAN
  can fetch the stream while the app is streaming. Use only on a trusted network.

## Roadmap

USB transport, automatic device discovery, secure pairing, learning/experiment
mode, project save, and signed releases are planned — no dates promised. See
[ROADMAP.md](ROADMAP.md).

## Troubleshooting

See [docs/troubleshooting.md](docs/troubleshooting.md) — includes SmartScreen,
connection failures, image-quality issues, and log locations.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) and [SUPPORT.md](SUPPORT.md).
Security issues: see [SECURITY.md](SECURITY.md).

## License

[MIT](LICENSE). Qt / PySide6 are used under LGPL-3.0 (Community Edition) — see
[docs/qt-lgpl-compliance.md](docs/qt-lgpl-compliance.md).
