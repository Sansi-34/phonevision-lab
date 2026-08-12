# Troubleshooting

Common issues and fixes for PhoneVision Lab. Before opening an issue, walk through
the relevant section. If you still hit a problem, open a bug report and include
the **summary** of the log lines (not the full log) — see [SUPPORT.md](../SUPPORT.md).

> 中文问题可看 PC 端 `pc-client/README.md` 与本仓库 `README.zh-CN.md`；用 Issue
> 提问时可用中文。

## The connection dialog says the phone is not streaming

1. On the phone app, tap **Start Streaming** first, then connect from the PC.
2. Confirm the phone and PC are on the **same WiFi network**.
3. Check the phone shows a LAN IP (it displays its address on the preview screen).
   A `wlan` / `10.` / `192.168.` IP is normal; a `USB`-tied interface is not a
   valid stream source yet.

## "Connection failed" on `/ping` or `/stream`

- **Wrong IP or port** — re-enter the IP shown in the phone app (not an example
  IP). Port defaults to 8080; keep it unless you changed `Config.kt`.
- **Firewall** — Windows Firewall may block the Python process on private
  networks. Allow it on the private profile only.
- **Phone firewall / hotspot** — if the phone is the hotspot, its own DHCP
  usually assigns IPs; ensure the PC joined the phone's hotspot network.
- **Stream dropped mid-viewing** — the client auto-reconnects with backoff. If it
  stays stuck on "Video stream interrupted", the phone app likely stopped or lost
  network. Restart streaming on the phone.

## Image problems

| Symptom | Likely cause / fix |
| --- | --- |
| Frozen/blocky image, high invalid-frame count | Weak WiFi or high resolution. Lower the capture rate (fewer FPS) or reduce distance to router |
| Image very dark/bright | Camera AE — adjust lighting; JPEG quality 70 in `Config.kt` is a size/quality trade-off |
| Canny/HSV shows nothing | Parameters out of range. Start wide (Canny low/high, full HSV range) then narrow |
| Only black frame in HSV mode | No pixels match the current HSV range; widen H/S/V limits |

## The Windows portable package triggers SmartScreen

The package is unsigned, so SmartScreen warns "Windows protected your PC".
Click **More info → Run anyway**, or verify the SHA-256 first (PowerShell):

```powershell
Get-FileHash .\PhoneVisionLab.exe -Algorithm SHA256
```

Compare against `SHA256SUMS.txt` in the package. If the hash matches, the file has
not been tampered with.

## Logs

- Location (Windows): `%LOCALAPPDATA%\PhoneVisionLab\logs\phonevision.log`
  (rolling, keeps ~3 files of ~1 MB each).
- Logs are local-only and record version/start/connection state/errors. They do
  not record image content, screenshots, parameter values, or secrets.

## Windows: config directory

Settings (last successful address, language) are saved per-user in
`%LOCALAPPDATA%\PhoneVisionLab\PhoneVisionLab\` (QSettings). Deleting that
directory resets the app to first-run state.

## Building from source

```bash
cd pc-client
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python main.py --host <phone-IP>
```

If `PySide6` fails to import, reinstall with a wheel for your platform:

```bash
pip install "PySide6>=6.8,<7"
```

## Still stuck?

Open an issue with the bug template and include:

- Version and launch method (source or portable package)
- Platform (Windows / Android / other)
- Steps to reproduce, expected vs. actual
- A summary of relevant log lines (no full logs, no screenshots of private content)
