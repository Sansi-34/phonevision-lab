# PhoneVision Lab

> [中文文档](README.zh-CN.md)

Turn an old Android phone into a vision sensor for machine vision learning on
Windows. Stream MJPEG over WiFi (and eventually USB), then learn image
processing with OpenCV.

**Status: Pre-release / development snapshot. Not ready for v1.0.**

## What is verified to work

- Android Camera2 live preview
- WiFi MJPEG streaming over HTTP
- `GET /ping` and `GET /stream` endpoints
- Windows PySide6 vision workbench (default client): top bar + live view + mode inspector + collapsible diagnostics, bilingual zh-CN/en
- Legacy Tkinter client (kept for compatibility): `python legacy_main.py`
- Strict MJPEG parser (boundary + Content-Length + SOI/EOI)
- Grayscale / Canny / HSV / contour experiments
- Fully local operation, no cloud / no account / no telemetry

## Getting started

```bash
# Default client (PySide6 vision workbench), Chinese or English
python main.py --host 192.168.x.x
python main.py --host 192.168.x.x --lang en

# Legacy Tkinter client (compatibility)
python legacy_main.py --host 192.168.x.x
```

Replace `192.168.x.x` with the IP shown in the phone app. Start streaming on the
phone first. Parameters are shown per active vision mode; the diagnostics panel
is collapsed by default; shortcuts: S save, R reconnect, 1-5 switch mode,
Ctrl+Q quit. Language choice is saved locally; the project has no telemetry.

## What is in progress, not yet complete

- USB as a formal product feature (adb forward is a reusable technique only)
- Automatic device discovery
- Secure pairing
- Remote start/stop and camera parameter control
- Learning mode / experiment mode / project save / Python code export
- Windows installer

## Modules

| Path | Description |
| --- | --- |
| `android/` | Android sensor app: Camera2 + ImageReader(JPEG) + NanoHTTPD MJPEG server |
| `pc-client/` | Windows client: strict MJPEG reader, OpenCV vision modes, PySide6 vision workbench (default), legacy Tkinter client |

## Important warnings

- **Not ready for v1.0.**
- The current HTTP stream has **no authentication**. Anyone on the same LAN
  can fetch the stream while the app is streaming.
- Use only on a **trusted local network**.
- **USB is not yet a formal product feature.**
- Automatic discovery and secure pairing are **not implemented**.

## License

[MIT](LICENSE)
