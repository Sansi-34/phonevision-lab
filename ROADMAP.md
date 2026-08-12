# Roadmap

This is a learning project. The roadmap is a direction, not a promise —
priorities shift with maintainer availability and contributor interest.
**No dates are promised.** Items are rough stages; anything may be reprioritized.

> 中文可看 [README.zh-CN.md](README.zh-CN.md) 的"正在建设"章节。

## Alpha scope (0.1.0)

Current focus — make the local WiFi learning loop solid:

- [x] Android phone as MJPEG-over-HTTP camera source (Camera2 + NanoHTTPD)
- [x] PC client: strict MJPEG parser + OpenCV vision modes (Original / Gray /
      Canny / HSV / Contours)
- [x] PySide6 bilingual workbench as default client
- [x] Fully local, no telemetry, no account
- [x] Windows portable package (no Python required) with license bundle
- [ ] Automatic device discovery
- [ ] Secure pairing (the HTTP stream currently has no authentication — LAN-only)

## USB transport

Turn `adb forward` (currently a reusable technique) into a first-class product
feature: automatic USB detection, fallback from WiFi to USB, and connection
status that reflects the active transport.

## Learning / teaching experiments

Beyond raw vision modes, add guided experiments that teach machine vision step by
step: save projects (settings + parameter presets), export the current pipeline as
Python code, and inline explanations of each step.

## Project save / configuration

Persist project files (device, modes, parameters, language) as shareable project
files, with import/export.

## Signed releases

Move from unsigned local builds to signed, reproducible releases with a proper
release checklist, checksum distribution, and automated build validation. Security
documentation (private vulnerability reporting) ships with the public repo.
