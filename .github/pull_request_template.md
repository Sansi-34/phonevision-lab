## What does this PR do?

Short description of the change and why.

## Test plan

- [ ] `python -m unittest discover -s tests -t tests` passes (offscreen:
      `QT_QPA_PLATFORM=offscreen`)
- [ ] `git diff --check` is clean
- [ ] Android impact: if `android/` changed, `gradlew assembleDebug` builds;
      otherwise mark **PC-only**
- [ ] `python -m py_compile` passes on touched Python files

## UI / docs

- [ ] Screenshots added only if the UI changed, and are **synthetic** (no personal
      data)
- [ ] Docs updated if behavior changed (README, docs/, release checklist)
- [ ] This is a UI change: **No** (or) **Yes** — screenshot attached

## Privacy

- [ ] No real IPs, usernames, paths, serial numbers, or log dumps committed
- [ ] No secrets (`.env`, `*.key`, tokens) added
- [ ] No telemetry/analytics code added

## Licensing

- [ ] No new third-party dependency added
  (or) New dependency added — license stated below and bundled into
  `pc-client/packaging/THIRD_PARTY_NOTICES.md` + `licenses/`:
      Dependency: \_\_\_  License: \_\_\_

## Notes

Anything the reviewer should know (real-device testing limitations, follow-up
work, etc.).
