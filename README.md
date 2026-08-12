# PhoneVision Lab

> [中文文档](README.zh-CN.md)

Turn an old Android phone into a vision sensor for machine vision learning on
Windows. Stream MJPEG over WiFi, then learn image processing with OpenCV — five
vision modes, bilingual UI, fully local, no account, no telemetry.

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
```

- **Phone = sensor**: captures frames, JPEG-encodes them, pushes an MJPEG stream.
- **PC = brain**: parses the stream, applies the five vision modes, and shows the
  result for learning.

## What is verified to work

- Android Camera2 live preview and WiFi MJPEG streaming over HTTP
- `GET /ping` (JSON status) and `GET /stream` (multipart MJPEG) endpoints
- Windows PySide6 vision workbench (default client): top bar + live view + mode
  inspector + collapsible diagnostics, bilingual zh-CN/en
- Strict MJPEG parser (boundary + Content-Length + SOI/EOI)
- Five vision modes: Original / Gray / Canny / HSV / Contours
- Legacy Tkinter client (compatibility only): `python legacy_main.py`
- Fully local operation — no cloud, no account, no telemetry

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
