# iDotMatrix hardware & BLE protocol

Source of truth: `src/dotdeck/device/protocol.py`, pinned by `tests/test_protocol.py`. Every encoder was verified
byte-for-byte against the reference `idotmatrix` 0.0.9 Python library (derived from the vendor's
`BleProtocolN.java`) on 2026-09-24.

## The device

| Property | Value |
| --- | --- |
| Model | iDotMatrix 32×32 RGB (sold under several brands, e.g. Apex Light) |
| Resolution | 32 × 32, origin top-left |
| Link | Bluetooth LE, advertised name `IDM-…` |
| Our unit | `AA:BB:CC:DD:EE:01` |
| Write characteristic | `0000fa02-0000-1000-8000-00805f9b34fb` |
| Notify characteristic | `0000fa03-0000-1000-8000-00805f9b34fb` (acks — used for flow control) |
| Write size | `max_write_without_response_size` (514 B on our unit with MTU 517; min 20) |
| Brightness range | 5–100 % |

## Framing

Short commands: `[len_lo, len_hi, cmd, sub, args…]`, `len` = total packet length.
Bulk uploads are split into **4096-byte chunks** with a header each; the transport then splits every chunk to the
write size.

## Command reference

| Function | Bytes | Notes |
| --- | --- | --- |
| Screen on / off | `05 00 07 01 01` / `…00` | |
| Brightness | `05 00 04 80 PP` | PP = 5..100 |
| Flip 180° | `05 00 06 80 01/00` | |
| Freeze toggle | `04 00 03 00` | |
| Set time | `0B 00 01 80 YY MM DD WD hh mm ss` | YY = year % 100, WD = ISO weekday 1..7 |
| Reset | `04 00 03 80`, then `05 00 04 80 50` | fixes a panel that stops accepting uploads |
| **DIY mode** | `05 00 04 01 MM` | MM 1 = enter. Required before PNG frames / pixels. **Blanks the panel ~200–400 ms** |
| Pixel (graffiti) | `0A 00 05 01 00 RR GG BB XX YY` | DIY mode |
| Clock | `08 00 06 01 FF RR GG BB` | FF = style(0..7) \| 0x80 show date \| 0x40 24 h |
| Countdown | `07 00 08 80 MM mm ss` | MM 0 off, 1 start, 2 pause, 3 restart |
| Chronograph | `05 00 09 80 MM` | 0 reset, 1 start, 2 pause, 3 continue |
| Scoreboard | `08 00 0A 80 aL aH bL bH` | 0..999 each |
| Solid colour | `07 00 02 02 RR GG BB` | |
| Effect | `LL 00 03 02 SS 5A NN [RGB×NN]` | SS 0..6, NN 2..7 colours, LL = 6 + NN |
| Eco / night | `0A 00 02 80 EN sh sm eh em BB` | |

### PNG frame (DIY mode) — `image_upload`

Per 4 KiB chunk: `uint16 LE packet length (chunk + 9)`, `00 00`, `00` first / `02` continuation,
`uint32 LE len(png)`, then the PNG bytes. A 32×32 PNG is 100 B – 3 KB, always one chunk.
Written **without response, paced** (see below). The panel acks each image with `05 00 00 00 01`.

> The reference library writes `len(png) + n_chunks` in the length field. That only works for PNGs that fit
> in one BLE packet; the true packet length works for all sizes (verified 2026-09-24).

### GIF (native playback) — `gif_upload`

16-byte header per chunk: `uint16 LE chunk_len`, `01 00`, `00`/`02`, `uint32 LE len(gif)`, `uint32 LE crc32(gif)`,
`05 00 0D`. The panel acks every 4 KiB chunk with `05 00 01 00 01` and the final chunk with `05 00 01 00 03`;
DotDeck waits for each ack before sending the next chunk. The panel stores the GIF and loops it by itself.

## Hard-won behaviour (keep these true)

1. **Pairing screen on disconnect.** If the link drops the panel shows a blinking Bluetooth icon. Keep one
   persistent connection; never disconnect between updates. (`BleDevice` reconnects with backoff 1→20 s.)
2. **DIY mode blink.** `diy_mode(1)` blanks the panel. Send it only on entering DIY from another mode — the
   scheduler tracks `info.mode` (`unknown/diy/gif/native`).
3. **Only one central.** The phone app and DotDeck can't both be connected. Close the vendor app.
4. **GIF colour flicker.** Per-frame palettes make colours jump; `encode_gif` uses one palette for all frames.
5. **Raw LEDs wash out sRGB photos.** Photos need gamma 2.2 + white balance (1.0, 0.88, 0.82) + black crush;
   see `gfx/color.py`. UI colours must **not** be calibrated.
6. **Antialiased text is unreadable** at this density. 1-bit fonts only.
7. **Throughput.** Measured: ~9 fps for UI frames (1 packet), ~6–7 fps for photo-like frames (3 packets
   with pacing); GIF uploads ~16 KB/s. `max_fps` (default 10) caps streaming; the latest frame always wins.

## Verified on hardware — 2026-09-24 (IDM-XXXXXX, Windows 11, bleak/WinRT, MTU 517)

Each finding was confirmed by the user watching the physical panel during scripted tests.

| # | Finding | Evidence | What DotDeck does |
| --- | --- | --- | --- |
| 1 | **Unpaced write-without-response bursts are silently dropped.** Anything larger than one packet (~514 B) never displayed — the "512-byte limit" reported in derkalle4/python3-idotmatrix-client#50. The panel even acks the image. | 1.4 KB plasma PNG streamed at 11 fps: acks received, panel unchanged. Same frames with a 30 ms gap between packets: smooth. | `Device.packet_gap` (config `packet_gap_ms`, default 30) between packets of one message. |
| 2 | **PNG length field must be the true packet length** (payload + 9), not `len(png)+1`. | 822 B still image with the true length: displayed correctly. | `protocol.image_upload` (pinned in tests). |
| 3 | **Acks arrive on `fa03`**: image `05 00 00 00 01` (~200 ms after the write), GIF chunk `05 00 01 00 01`, GIF complete `05 00 01 00 03`, commands echo themselves. | Notification log during uploads. | Subscribed on connect; `info.last_ack` in state. |
| 4 | **Waiting for each frame's ack serialises the link at ~2.6 fps**; keeping one frame in flight gives ~9 fps and stays reliable. | Snake: 2.6 fps serial → 9.1 fps pipelined, user-confirmed smooth. | One-deep frame pipeline in `Device._write_next`. |
| 5 | **Big GIFs work when every 4 KiB chunk waits for its ack** — a 91 KB, 48-frame GIF uploaded in ~5 s and played — but the panel decodes large GIFs sluggishly ("a little laggy"). ~35–40 KB plays smoothly. | Plasma at 91 KB vs 39 KB. | `encode_gif_budget`: palette shrinks until ≤ 40 KB; `App.clip_colors`. |
| 6 | Small GIFs (0.5–1.5 KB) upload in < 0.4 s. | Mascot GIF. | Clips for all deterministic loops. |
| 7 | The panel can be left in "screen off" by other apps; DotDeck now sends screen-on (or off, per saved state) on every connect. | "Panel dark while studio says on" class of bug. | `Device._replay`. |

## Verified on hardware — 2026-09-27

| # | Finding | Evidence | What DotDeck does |
| --- | --- | --- | --- |
| 8 | **Indexed-colour (palette) PNG frames render garbled.** The firmware decodes only truecolour PNGs correctly, even though palette PNGs are ~30 % smaller (would fit full-scene frames in one packet). | Pet World streamed as lossless palette PNGs: user saw a "glitching image"; switching back to RGB fixed it at once. | `Frame.to_png()` always emits RGB. Don't reintroduce palette frames. |
| 9 | **Full-scene frames of ~500–620 B (two packets) stream at ~5–6 fps**, vs ~9 fps for one-packet frames. Scrolling a whole scene at that rate reads as judder, so full-scene motion should move characters over still scenery rather than scroll the camera. | Pet World: follow-camera judder vs fixed screens. | Pet World's default "rooms" camera; animations use pose-stepped clocks (`gfx.characters.step_anim_time`). |
| 11 | **Native GIF playback is smooth and not limited by the link.** A 240-frame (30 s @ 8 fps, 38 KB) GIF plays correctly; 160 frames at 10 fps too. Uploading the next GIF causes a brief visible hiccup, so re-upload as rarely as the content allows. | Pet World as 16 s then 30 s baked chunks: "smooth, small hiccup" → "plays fine, rarer blip". | Pet World / Pet run as baked chunks (`kind() == "clip"`, chunked `clip_key`); stream only for live music sync. |
| 12 | **Hand-off works:** the firmware clock (`05 00 06 01 …` after `set_time`) and a baked app loop both keep running after DotDeck stops sending. | Scripted `POST /api/handoff/now` with the user watching. | `Engine.handoff()`; automatic on exit and Windows sleep. |
| 13 | **Smooth motion needs small steps per frame at ~8 fps.** The pixel-cat loop was choppy at 12 fps, choppy at 8 fps with bigger steps, borderline at 8 fps × 48 frames, and clearly smooth at 8 fps × 96 frames (half-size steps). It's the per-frame displacement that reads as judder, not decode speed. | Five A/B runs of `loops` "cat" with the user watching. | `apps/loops.py` `LOOP_SPEC`: 8 fps, loops long enough for small steps (cat 12 s / 96 frames). Design full-screen motion as ≤ ~1 px/frame at ≤ 8 fps. |
| 14 | A version-2 QR code (25×25 modules, 1 px each, dark on light) shown on the panel scans with a phone camera. | User scanned the `qr` app → opened https://claude.ai. | `apps/qr.py` defaults. |
| 15 | **Never abandon a GIF mid-upload.** A GIF cut off part-way (superseded by a newer one right after connecting) left the panel blank and ignoring the next GIF; a fresh complete upload fixed it. | Blank panel after an engine restart + immediate re-activation; re-upload restored it. | `Device._write_next` always finishes an in-flight GIF, then sends the newest visual. Test `test_gif_upload_is_never_abandoned_midway`. |
| 16 | **Frequent GIF uploads make the panel stop acking chunks** ("no ack for a GIF chunk"). After ~5 uploads in a minute each chunk timed out (3 s), an upload took ~30 s and the user saw freezes; the panel then took ~1 min to accept a reconnect, and the next upload still missed acks. Likely the firmware writing each GIF to flash. Once stuck, the panel stopped advertising entirely; **unplugging its power for ~5 s cleared it** (next upload 38 KB in 2.8 s, no missed acks). The final GIF ack can also read `05 00 01 00 00`, and that upload played fine. | Pet World park with 24 s chunks re-uploaded every 24 s, plus back-to-back bakes at start-up. | Chunk refresh rate-limited (`App.clip_refresh`, 90 s for Pet World/Pet), 3 s cool-down between GIF uploads (`GIF_COOLDOWN`), weather no longer triggers re-bakes. |
| 10 | Colour calibration wizard patterns display correctly (after fixing a newer frame losing to a queued GIF). User calibration: white A (neutral), gamma 1.5, no black lift, saturation 1.0, RGB balanced. | Scripted wizard with the user answering each card. | `Device.show_frame` supersedes a queued GIF; saved calibration in `state.json`. |

## Unverified / to explore

- Whether `packet_gap` can go below 30 ms (15–20 ms would raise the fps ceiling for large frames).
- Max GIF size/frame count the firmware accepts (we cap clips at 64 frames from media, ~160 for text).
- Whether pixel packets are faster than PNG frames for small diffs (a delta path is designed in `Device.set_pixels`).
- Text mode (`Text` module in the reference library) — we render text ourselves instead.

Add findings here with the date and how you verified them (`uv run dotdeck doctor`, sniffed traffic, etc.).
