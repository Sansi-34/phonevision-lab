# Protocol

This document specifies the wire protocol between the Android sensor app and the
Windows client. It is the contract both sides implement.

## Overview

The phone exposes an HTTP server (NanoHTTPD) on the LAN. Two endpoints matter:

- `GET /ping` — machine-readable status (JSON).
- `GET /stream` — a `multipart/x-mixed-replace` MJPEG stream.

There is **no authentication**. Anyone on the same LAN can read the stream while
the phone is streaming. Use only on a trusted local network.

## Defaults

| Parameter | Default |
| --- | --- |
| Port | `8080` |
| Resolution | `640 x 480` |
| Target capture rate | `10 FPS` |
| JPEG quality | `70` |

These live in `android/app/src/main/java/com/phonevisionlab/app/Config.kt`.

## `GET /ping`

Returns `application/json`:

```json
{
  "status": "streaming",
  "device": "Phone-Vision-Sensor",
  "width": 640,
  "height": 480,
  "requestedFps": 10,
  "actualFps": 9.8,
  "frameCount": 1234
}
```

| Field | Meaning |
| --- | --- |
| `status` | `idle` (preview only), `streaming`, or `stopped` |
| `device` | Device display name |
| `width` / `height` | Capture resolution in pixels |
| `requestedFps` | Target FPS configured on the phone |
| `actualFps` | Measured capture FPS (decimals) |
| `frameCount` | Total frames captured since stream start |

The PC client calls `/ping` before opening the stream to validate connectivity and
show device info. If `status != "streaming"`, the client tells the user to tap
"Start Streaming" first.

## `GET /stream`

Returns `multipart/x-mixed-replace; boundary=...` with one JPEG per part:

```
--<boundary>
Content-Type: image/jpeg
Content-Length: <bytes>

<JPEG payload>
--<boundary>
...
```

### Parsing rules (implemented in `pc-client/mjpeg_reader.py`)

The parser is intentionally strict:

1. **Boundary matching** — parts must be delimited by the advertised boundary.
2. **`Content-Length`** — each part is read to its exact byte length; the parser
   does not guess from the next boundary.
3. **JPEG markers** — each payload must start with `0xFF 0xD8` (SOI) and end with
   `0xFF 0xD9` (EOI). Corrupt frames are counted as `invalid` and dropped, not
   displayed.
4. **Latest-frame-only** — only the most recent complete frame is kept. If the
   consumer is slower than the source, older frames are skipped; latency does not
   accumulate.

### Reading and closing

- Streams are read in a background thread; the client aborts the request on stop
  or reconnect.
- On connection loss, the client retries with backoff (1/2/3 seconds) and keeps
  the last good frame until a fresh one arrives or staleness is detected (~3 s).

## Error handling

- Non-2xx responses on `/ping` or `/stream` surface as a connection error in the
  UI with a human-readable message.
- A phone that stopped streaming returns `status: stopped` on `/ping` and the
  stream connection drops; the client marks the stream stale and shows the
  "Video stream interrupted / reconnect" placeholder.

## Future work (not yet in this protocol)

- USB transport (`adb forward`) is being designed as a product feature; the HTTP
  protocol above is expected to remain the same over the forwarded local port.
- Secure pairing and authentication are planned but not implemented.
