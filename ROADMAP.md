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

## Learning loop: custom classes to on-device inference (0.2.0 alpha)

The first closed loop — collect your own classes, train, export, run offline on
the phone, drive real hardware, and measure it. **Object detection, segmentation,
gesture recognition and car control are explicitly out of this stage.**

- [x] Dataset management: create/open, add and rename classes, browse and delete
      samples, single/burst capture from the live stream
- [x] Train/val split **by capture batch** (never per frame) with seed + ratio
      recorded; data health check that reports instead of faking metrics
- [x] Training: MobileNetV3Small transfer learning, CPU by default, GPU offered
      only when actually detected, cooperative cancel
- [x] Export: Keras → TFLite (float16) + fixed-sample consistency check; export
      is **refused** when the check fails
- [x] Self-describing `.pvlmodel.zip` (model, labels, input size, layout, colour
      order, scale/crop/normalisation, output interpretation, training params,
      pretrained provenance)
- [x] Android: model import with per-field validation, on-device TFLite inference,
      preview + prediction + confidence + measured FPS and per-stage timings
- [x] Hardware interaction: rule engine (consecutive confirm + hysteresis +
      cooldown) → device adapter (requestId dedup, timeout, retry only for
      idempotent actions, no replay after reconnect) → ESP32 LED firmware
- [x] Performance analysis: per-stage mean/P50/P95, dropped frames, command ack
      latency, CSV / summary / JSON export
- [ ] **Real-device validation** of the whole loop (needs a phone + ESP32 + LED)

## Next after the learning loop

- Object detection / segmentation (a second model family, not in 0.2.0)
- Servo / motor control with device-side timeout stop
- Automatic device discovery and USB transport as first-class features
- Secure pairing for the HTTP stream

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
