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
- Windows Tkinter client (image view + mode panel + metrics bar)
- Strict MJPEG parser (boundary + Content-Length + SOI/EOI)
- Grayscale / Canny / HSV / contour experiments
- Fully local operation, no cloud / no account / no telemetry

## What is in progress, not yet complete

- PySide6 as the formal Windows Studio (recommended direction, not yet feature-aligned with Tkinter, and the formal entry point is not switched)
- USB as a formal product feature (adb forward is a reusable technique only)
- Automatic device discovery
- Secure pairing
- Remote start/stop and camera parameter control
- Learning mode / experiment mode / project save / Python code export
- Windows installer
- Bilingual product UI

## Modules

| Path | Description |
| --- | --- |
| `android/` | Android sensor app: Camera2 + ImageReader(JPEG) + NanoHTTPD MJPEG server |
| `pc-client/` | Windows client: strict MJPEG reader, OpenCV vision modes, Tkinter GUI, PySide6 GUI (in progress) |

## Important warnings

- **Not ready for v1.0.**
- The current HTTP stream has **no authentication**. Anyone on the same LAN
  can fetch the stream while the app is streaming.
- Use only on a **trusted local network**.
- **USB is not yet a formal product feature.**
- Automatic discovery and secure pairing are **not implemented**.

## License

[MIT](LICENSE)
