# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **Learning loop: custom classes → on-device inference → hardware control.**
  Image classification only; object detection, segmentation, gesture recognition
  and car control are out of this stage.
  - PC dataset management (`pvl_dataset.py`): create/open, add and rename
    classes, browse/delete samples, single and burst capture from the live
    stream; data lives under `%LOCALAPPDATA%\PhoneVisionLab`, never in the repo
  - Train/val split **by capture batch** (`pvl_split.py`) with seed and ratio
    recorded, plus a data health check that reports missing classes, thin
    classes, undecodable images and severe imbalance instead of faking metrics
  - Training (`pvl_train.py`): MobileNetV3Small transfer learning, CPU by
    default, GPU offered only when actually detected, cooperative cancel,
    best-model-by-validation-accuracy saving, full config recorded
  - Export (`pvl_export.py`): Keras → TFLite (float16) plus a fixed-sample
    consistency check; **export is refused** when max abs error or Top-1
    agreement falls outside tolerance
  - Self-describing `.pvlmodel.zip`: model, labels, input size, tensor layout,
    colour order, scale/crop/normalisation rules, output interpretation,
    training parameters and pretrained-weight provenance
  - Preprocessing contract (`pvl_preprocess.py`) as the single source of truth,
    mirrored field-by-field on Android (`Preprocessor.kt`)
  - Android on-device inference: model import with per-field validation
    (`ModelPackage.kt`), TFLite CPU inference (`InferenceEngine.kt`), preview +
    prediction + confidence + measured FPS and per-stage timings; inference runs
    fully offline after import
  - Hardware interaction: `ControlProtocol.kt` / `pvl_hardware.py` /
    `led_controller.ino` share one wire contract. Rule engine with consecutive
    confirm, hysteresis and cooldown; device adapter with requestId dedup,
    timeout, retry only for idempotent actions and no replay after reconnect
  - ESP32 LED controller firmware (`controller-firmware/`) with HTTP control
    endpoint, duplicate-command dedup and a device-side 10-minute watchdog
  - Performance analysis (`pvl_perf.py`): per-stage mean/P50/P95, dropped
    frames, command ack latency, CSV / summary / JSON export; monotonic clocks
    only, never cross-device timestamp subtraction; unsupported power metrics
    display "不支持"
  - PySide6 workbench tabs: Dataset, Train & Export, Hardware, Performance
  - Optional training dependency set (`requirements-train.txt`) kept separate
    from the base client dependencies
  - Docs: `docs/user-guide.zh-CN.md`, `docs/training.zh-CN.md`,
    `docs/hardware.zh-CN.md`, `docs/demo-script.zh-CN.md`

### Changed

- Android app now has two mutually exclusive modes (camera streaming / on-device
  AI inference); entering inference mode stops the MJPEG server
- `CameraController` gained an optional frame-Bitmap callback so inference and
  streaming share one capture session (older phones cannot open two at once)
- TensorFlow Lite 2.16.1 added as an Android dependency (AAR `minSdk 19`,
  compatible with the project's `minSdk 21`); CPU only by default
- Android dependency-verification metadata gained TFLite artifact checksums
- QSS theme gained rules for the new workbench tabs, list/log widgets, inputs,
  combo boxes, checkboxes and progress bars
- `GET /stream` now answers `503` (+`Retry-After`) while the camera has not
  started streaming, instead of holding the response open with no frames;
  the PC client treats `503` as "not ready yet" and retries in 300 ms instead of
  the 1/2/3 s disconnect backoff

### Fixed

- **PC workbench: one-shot notifications were swallowed.** `_update_metrics()`
  called `toast.clear()` on every 33 ms tick, so "saved", "no frame to save" and
  the "export in progress, cannot close" warning disappeared before a user could
  read them. Clearing is now tied to an error transition, and success/warning
  messages are left to the banner's own dismiss timer.
- **PC workbench: frame dedup froze live state.** `_update_frame()` returned
  early when the frame number had not changed, which also skipped the status
  pill, the reconnect placeholder and the statistics sync. Only the expensive
  `apply_mode()` + `QPixmap` path is deduplicated now.
- **PC workbench: the diagnostics resolution stayed `0x0`.** `stats["width"]` /
  `["height"]` were read but never written from the snapshot, so starting from
  the connection dialog (empty `/ping` info) never picked up the real
  resolution.
- **PC workbench: single-letter shortcuts hijacked text input.** Window-level
  `S` / `R` / `1`-`5` shortcuts fired while typing in the dataset class name or
  the controller IP/port fields (typing `192.168.1.10` switched the vision
  mode). They are now ignored while a text input has focus.
- **PC workbench: dangling `QImage` view.** The frame's `QImage` wrapped a local
  numpy buffer without copying it.
- **PC client: `stop()` did not close the stream connection.** The reader thread
  sat in a socket read (up to 5 s) so `join(3.0)` timed out routinely, and a
  reconnect could leave the old connection consuming bandwidth. `stop()` now
  closes the response first; failed `raise_for_status` / missing boundary paths
  also close it instead of leaking a `stream=True` connection.
- **Android: model import blocked the UI thread.** Unzipping an up-to-80 MB
  package, writing it and constructing the TFLite `Interpreter` all ran on the
  main thread. Import, load and interpreter construction now run on a single
  background executor with progress and per-state button gating.
- **Android: stopping the stream leaked a blocked thread per stop.**
  `LatestFrameStore.read()` waited on the condition forever and
  `NanoHTTPD.stop()` only closed sockets, which cannot wake a condition wait.
  The store now exposes a timeout-bounded `getAfter(...)`, `MjpegServer.stop()`
  signals waiters before closing, and readers exit within one 250 ms window.
- **Android: a late camera callback could hijack the next session.** `start()`
  and `stop()` now bump a generation counter; opened devices, configured
  sessions and frame callbacks from an older generation are closed and dropped
  instead of overwriting `isStreaming` and the shared session fields.
- PC protocol parity: `Feedback.from_json()` accepts the Android-side `"error"`
  alias as `failed` and keeps rejecting unknown statuses (the previous test
  expected an unknown status to default to `received`, which contradicts both
  implementations and would let the rule engine treat an unparsed reply as a
  confirmation).
- Cross-platform test bug: `tests/test_entrypoints.py` captured subprocess
  output with `text=True` but no encoding, so on a Chinese-locale Windows the
  reader thread raised `UnicodeDecodeError`, `stdout` became `None` and six
  tests errored out. Both sides are pinned to UTF-8 now.
- `tests/test_i18n.py` asserted the *machine's* saved UI language was not `en`,
  which fails on any developer machine that had picked English. It now compares
  before/after, which is what "injected settings are isolated" actually means.
- Split by batch: a class with a single capture batch had that batch assigned to
  validation, leaving the training set empty ("split succeeded", then training
  failed on an empty train set). Such classes now stay entirely in training with
  an explicit warning.
- `--version` implemented for the PySide6 entrypoint (the packaged EXE has no
  terminal, so this is the only way for a user to state the exact build); the
  missing `version_unknown` translation key was added, which also un-silences
  the dialog localization assertions.
- `DatasetStore.create()` ignored the root passed to its constructor and always
  used the data directory, so an explicitly requested path could be rewritten
- Rule engine cooldown blocked the very first trigger (`last_action` was
  initialised to 0, making "never acted" look like "just acted"); it now starts
  as "never acted"
- `_resize_bilinear()` broadcast `(h, w, 3)` against `(1, w)` and raised on
  upscaling; it is now separable
- Nearest-neighbour resize could read out of range on extreme aspect ratios

### Security

- Dataset sample deletion rejects any path containing `..`, absolute paths, or
  anything resolving outside the dataset root
- Model import validates format version, required files, input/output shapes,
  colour order, tensor layout, normalisation, contract version and label count,
  and refuses with a specific reason instead of crashing
- Controller firmware starts with the LED off, never lights up on boot

### Not verified (needs real hardware)

- End-to-end run on a physical phone
- Real ESP32 + LED actuation and phone-to-controller direct connection
- Servo / motor control (not implemented; `servo_set` returns "not implemented"
  rather than pretending success)

## [0.1.0-alpha.1] - unreleased

> Version line reserved for the first tagged pre-release. Dates are added when a
> tag is cut; no dates are fabricated here.

### Added

- Android sensor app: Camera2 preview + ImageReader(JPEG) + NanoHTTPD MJPEG server
  (`GET /ping`, `GET /stream`)
- PC client: strict MJPEG parser, OpenCV vision modes, PySide6 workbench
  (bilingual zh-CN/en), legacy Tkinter client kept for compatibility
- Fully local operation — no cloud, no account, no telemetry

> Repository URL (once public) is added to the version-links section at release
> time.
