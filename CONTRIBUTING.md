# Contributing to PhoneVision Lab

Thanks for your interest in contributing. This is a learning-friendly, MIT-licensed
project that turns an old Android phone into a vision sensor for machine vision
practice on Windows.

> 中文版见 [CONTRIBUTING.zh-CN.md](CONTRIBUTING.zh-CN.md)。

## 1. Ground rules

- **Beginner-friendly**: the code is written to be readable and teachable. Keep it
  that way. Prefer clear names and short functions over clever one-liners.
- **MVP first**: if a change grows large, split it. A small merged PR is better than
  a big draft.
- **Keep it local**: no telemetry, no cloud account, no analytics. Do not add any
  network call that is not core to streaming/learning.
- **Respect existing architecture**: do not rewrite modules that already work
  unless the task explicitly asks for it.

## 2. Environment

Prerequisites:

- **Python 3.12+**
- Android toolchain for the `android/` app (optional, only if you touch Android):
  - JDK 17 (e.g. Adoptium Temurin 17)
  - Android SDK (compileSdk / targetSdk / minSdk as set in `android/app/build.gradle.kts`)
  - Gradle is pinned to 8.7 via the wrapper (see `android/gradle/wrapper/gradle-wrapper.properties`)

Set up the PC client:

```bash
cd pc-client
python -m venv .venv
.venv\Scripts\activate          # Windows; macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
```

## 3. Python tests

Run the full PC test suite (offscreen, no display needed):

```bash
cd pc-client
export QT_QPA_PLATFORM=offscreen   # Windows PowerShell: $env:QT_QPA_PLATFORM="offscreen"
python -m unittest discover -s tests -t tests
```

Or run a single module while iterating:

```bash
python -m unittest tests.test_mjpeg_reader -v
```

- Qt UI tests run headless via `QT_QPA_PLATFORM=offscreen`; they never need a
  display or a phone.
- Before finishing, check: `git diff --check` and `git status --short`.

## 4. Android build

Only needed when you modify `android/`. On Windows (Git Bash / cmd):

```bash
cd android
# Ensure JDK 17 and the Android SDK are on PATH / set JAVA_HOME, ANDROID_HOME
cmd //c gradlew.bat assembleDebug
```

The APK lands in `android/app/build/outputs/apk/debug/`. You do not need to build
Android for PC-only changes.

## 5. Commit conventions

- Commits are conventional-commit style, e.g. `feat(pc): ...`, `fix(android): ...`,
  `docs: ...`, `test(...): ...`, `build(...): ...`.
- Keep each commit focused; use a clear subject line that states the **why**.
- Follow the existing history style — read `git log --oneline` first.

## 6. Branching

- Use short topic branches off `main`, e.g. `feat/pc-window-resize`.
- Open a PR and keep it small enough to review in one sitting.

## 7. PR checklist

Before opening a pull request, confirm:

- [ ] Tests pass: `python -m unittest discover -s tests -t tests` (offscreen)
- [ ] `git diff --check` is clean (no trailing whitespace / conflict markers)
- [ ] Android impact considered: if you touched `android/`, `gradlew assembleDebug`
      builds; otherwise state "PC-only".
- [ ] Screenshots added only if the UI changed and are synthetic / contain no
      personal data.
- [ ] Docs updated if behavior changed (README, docs/, release checklist).
- [ ] Privacy: no real IP, username, path, serial number, or log dumps are
      committed; no secrets (`*.key`, `.env`) are added.
- [ ] Licensing: if you add a dependency, update the third-party notices
      (`pc-client/packaging/THIRD_PARTY_NOTICES.md` and `licenses/`) and state the
      dependency's license in the PR.

## 8. Real-device validation

Streaming code should ideally be verified against a real phone:

1. Start the app on the phone and tap "Start Streaming".
2. On the PC, run `python main.py --host <phone-IP> --port 8080`.
3. Confirm the five modes (Original / Gray / Canny / HSV / Contours) render.

If you cannot test on a real device, say so in the PR; mock-based tests still cover
the parsing and UI logic.

## 9. What not to commit

- Local logs (`*.log`, `*logcat*.txt`), screenshots from a real device, captures
  and dumps.
- Machine-specific paths (`C:\Users\...`, `D:\...`) and usernames.
- Secrets: `.env`, `*.keystore`, `*.jks`, API keys, tokens.
- Large binaries / archives (`.zip`, `.apk`, `.mjpeg`).

## 10. Beginner tasks

New to open source? Look for issues labelled `good first issue`. Suggested starter
areas: documentation fixes, test coverage, small UX polish. Ask questions in the
issue thread before coding — maintainers and fellow contributors are happy to
guide.

## 11. Bilingual docs

User-facing docs and this file are maintained in both Simplified Chinese and
English. When you change one, update the other (key sections must stay in sync —
see `tests/test_repository_health.py`).
