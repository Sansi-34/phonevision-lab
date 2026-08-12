# Release checklist

This checklist is the pre-release hard gate for PhoneVision Lab. It is written to
be followed **before** any public release. Some items are still pending (tracked
as P0-5x).

## 0. Hard gate — Qt/PySide6 licensing (P0-5B)

- [ ] `pc-client/packaging/THIRD_PARTY_NOTICES.md` states the **LGPL-3.0** path
      and marks Commercial texts as "not the adopted path, for reference only"
- [ ] `licenses/` contains `lgpl-3.0.txt` and `gpl-3.0.txt` (full texts) and the
      PyInstaller COPYING with the bootloader exception
- [ ] `docs/qt-lgpl-compliance.md` records exact versions (Qt 6.11.1 / PySide6
      6.11.1), dynamic-linking note, source-download URLs, and user-replacement
      instructions; it states the document is not legal advice
- [ ] License bundle tests pass: `python -m unittest tests.test_license_bundle`
      (items 23-25)

## 1. Repository health (P0-5C)

- [ ] README (en + zh-CN) has no local paths, fake release URLs/download buttons,
      or CI badges; both mark the project as pre-release
- [ ] SECURITY.md has no placeholder email and references GitHub Private
      Vulnerability Reporting
- [ ] **Enable GitHub Private Vulnerability Reporting** on the repository
      (Security tab → Vulnerability alerts → report a vulnerability)
- [ ] Issue templates and PR template have no fake labels/assignees
- [ ] Repository health tests pass: `python -m unittest tests.test_repository_health`
      (items 9-13)

## 2. Tests

- [ ] Full PC suite passes offscreen:
      `QT_QPA_PLATFORM=offscreen python -m unittest discover -s tests -t tests`
- [ ] `git diff --check` is clean
- [ ] Android builds when Android was touched: `cmd //c gradlew.bat assembleDebug`
      (JDK 17 + Android SDK on PATH)

## 3. Build artifacts

- [ ] `python -m py_compile` passes on all touched Python files
- [ ] Windows portable build succeeds and ZIP + SHA-256 are generated
      (`artifacts/windows/`)
- [ ] build-info.json records the exact versions and git commit
- [ ] The built package contains `THIRD_PARTY_NOTICES.md`, `licenses/`,
      `README.portable.txt`, and the repo `LICENSE`

## 4. Privacy & security

- [ ] No telemetry/analytics code added
- [ ] No secrets, real IPs, usernames, paths, or serial numbers committed
- [ ] Logs confirm they record only version/start/connection/error text
- [ ] Known limitations documented (no authentication on the stream, LAN-only)

## 5. Release docs

- [ ] CHANGELOG updated (Keep a Changelog style); version entry has a real date
- [ ] ROADMAP reflects current scope
- [ ] README/portable README instructions match the actual behavior
- [ ] Screenshots in `docs/images/` are synthetic (no real data) and under 500 KB

## 6. Signing (future, not yet in place)

- [ ] A signing identity is configured and the package is signed
- [ ] The release URL is real and the checksum is published

## Notes

This checklist is a living document. The **license (P0-5B)** and **repository
health (P0-5C)** gates are the current blockers for public release.
