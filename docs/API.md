# HTTP & WebSocket API

Base URL `http://127.0.0.1:8765`. Interactive OpenAPI docs: **`/docs`**. JSON in and out.
Errors: `400` bad request · `404` unknown app/media · `422` validation (`detail` lists fields).

## Read

| Method | Path | Returns |
| --- | --- | --- |
| GET | `/api/health` | `{ok, version, device}` |
| GET | `/api/meta` | apps (id, name, description, icon, category, **schema**, actions; games also `max_players`, `controls` and `modes: [{id, name, min_players, max_players, teams}]` with `teams` = solo/coop/ffa/versus), palette, fonts, icons, leagues, plugins |
| GET | `/api/state` | full snapshot: `device`, `engine` (mode, current, playlist, overlay, render_ms, takeover, onair, eyebreak, indicators, custom), `settings` (incl. `integrations`, tokens masked), `apps` (settings per app), `providers` |
| GET | `/api/frame.png?scale=1..32` | exactly what the panel shows |
| GET | `/api/frame` | `{width, height, rgb: base64(3072 bytes)}` |
| GET | `/api/fly` | the fruit-fly brain while a fly plays (the Fly Brain app, or a game with `pilot: "fly"`): `{active, app, driving, step, eye, on, off, mh, mv, hs, looming, gf, dn, light, spikes, keys: [[step, key]…], anchor, world?}`. The maps are 256 values (16×16). Otherwise `{active: false, app}`. Studio only; never drawn on the panel. |

## Apps

| Method | Path | Body |
| --- | --- | --- |
| POST | `/api/apps/{id}/activate` | `{settings?: {...}, revert_after?: seconds}` — show now (pauses playlist); with `revert_after` the previous content returns |
| PATCH | `/api/apps/{id}/settings` | partial settings; returns the full validated settings |
| POST | `/api/apps/{id}/actions/{action}` | action payload, e.g. timer `toggle`, nowplaying `next`, canvas `paint` |

## Shortcuts

| Method | Path | Body |
| --- | --- | --- |
| POST | `/api/text` | `{text, color?, effect?: solid|rainbow|gradient, revert_after?}` |
| POST | `/api/pixels` | `{rows?: [..], palette?: {char: "#hex"}, rgb?: base64, pixels?: [[x,y,"#hex"]], clear?, revert_after?}` → Canvas |
| POST | `/api/agent/{state}?hold=seconds` | state ∈ `idle thinking working waiting done error sleeping` |
| POST | `/api/notify` | `{title, message, color, icon, duration (1–120), style: banner|full|celebrate}` |
| DELETE | `/api/notify` | dismiss current + queued |

## Status indicators

Three small squares on the right edge (AWTRIX 3 style), drawn **on top of every app**: `1` top-right,
`2` right-middle, `3` bottom-right. Kept in memory (not persisted across restarts).

| Method | Path | Body |
| --- | --- | --- |
| GET | `/api/indicators` | `{"1": {color, blink, fade, lifetime_s, size, remaining_s}, …}` (lit ones only) |
| POST | `/api/indicators/{1-3}` | `{color: "#rrggbb" \| palette name \| [r,g,b], blink?: ms (true = 1000), fade?: ms (true = 2000), lifetime_s?: seconds (0 = until cleared), size?: 2 \| 3}` |
| DELETE | `/api/indicators/{1-3}` | turn it off |

While an indicator is lit the frame is streamed (a clip app plays from its baked frames), so use them for
state, not decoration. Blinking/fading ones tick the engine at 10 Hz.

```powershell
curl -X POST localhost:8765/api/indicators/1 -H "content-type: application/json" -d '{"color":"#00ff78","lifetime_s":900}'
curl -X POST localhost:8765/api/indicators/3 -H "content-type: application/json" -d '{"color":"#ff143c","blink":500}'
curl -X DELETE localhost:8765/api/indicators/3
```

## Custom push apps (AWTRIX 3 compatible)

Anything can push a small "icon + one value" screen by name. While fresh it **joins the playlist rotation**
(after your own items, only while the playlist is playing) and the built-in `custom` app renders it.
Pushing the same name again replaces it and restarts its lifetime. Apps persist across restarts
(store key `custom_apps`, max 24).

| Method | Path | Body |
| --- | --- | --- |
| GET | `/api/custom` | `[{name, text, icon, duration, expires_in}]` (fresh apps only) |
| POST | `/api/custom/{name}?show=false` | the app (below). `name`: 1–32 of `A-Z a-z 0-9 _ -`. **An empty body `{}` removes it** (AWTRIX semantics). `show=true` also pins it on screen now |
| DELETE | `/api/custom/{name}` | remove (404 if unknown) |

Body — the AWTRIX 3 custom-app subset; unknown AWTRIX keys are ignored:

| Key | Type | Meaning |
| --- | --- | --- |
| `text` | string ≤ 500 | the value / message. Fits in `small` type → centred; longer → smooth scroll (baked as a native loop) |
| `icon` | string | a DotDeck icon name (`GET /api/meta` → `icons`: bell info warn ok error mail chat heart home bolt drop temp sun cloud bulb battery door lock person fire star music clock eye mic cam claude), drawn 2× |
| `rows` + `palette` | `["..##..", …]`, `{"#": "#ffd600"}` | pixel-art icon instead, up to 16×16 (≤ 8×8 is drawn 2×); `.` and space are off |
| `color` | `"#rrggbb"` \| palette name \| `[r,g,b]` | text colour (and named-icon colour); default white |
| `progress` | 0–100, `-1` = none | progress bar on the bottom rows |
| `progressC` / `progressBC` | colour | bar / bar background colour |
| `duration` | 3–3600 s (default 10) | time on screen per rotation |
| `lifetime` | seconds, `0` = never (default) | stale after this long → removed automatically |
| `textCase` | 0 default (upper) · 1 upper · 2 as sent | the panel fonts are upper-case, so 2 only matters for symbols |
| `rainbow` | bool | per-letter rainbow |
| `pushIcon` | 0 fixed · 1 icon scrolls away with the text each pass · 2 scrolls away once | only for scrolling text |

```powershell
# curl: a temperature with a thermometer, stale after 15 minutes
curl -X POST localhost:8765/api/custom/office -H "content-type: application/json" `
  -d '{"text":"21.5°","icon":"temp","color":"#ffaa00","lifetime":900}'

# a progress screen with pixel art
curl -X POST localhost:8765/api/custom/print -H "content-type: application/json" `
  -d '{"text":"PRINT","rows":["#####","#...#","#####"],"palette":{"#":"#00dcff"},"progress":42,"progressC":"#00ff8c"}'

curl -X POST localhost:8765/api/custom/print -d '{}' -H "content-type: application/json"   # remove
```

## Integrations: On Air, Eye break, ntfy, Home Assistant

| Method | Path | Body |
| --- | --- | --- |
| GET | `/api/integrations` | `{onair, eyebreak, ntfy, homeassistant, status}` — tokens masked |
| PATCH | `/api/integrations/{onair\|eyebreak\|ntfy\|homeassistant}` | partial section (below); returns the section, tokens masked |
| POST | `/api/integrations/homeassistant/test` | `{ok, message}` — calls HA's `GET /api/` with the stored token |
| POST | `/api/onair/simulate` | `{seconds: 0–600}` — preview the On-Air look (0 stops); works while disabled |
| POST | `/api/eyebreak/now` | show the eye-break nudge now |

Sections (stored in `data/state.json` under the same keys):

- **onair** `{enabled, style: full|badge|glow, look: sign|outline, webcam, microphone, exclude: "obs64, voicemeeter"}` —
  Windows: reads `HKCU\…\CapabilityAccessManager\ConsentStore\{webcam,microphone}` (incl. `NonPackaged`) every 2 s;
  an app whose `LastUsedTimeStop` is 0 is using the device now. DotDeck's own Python is ignored. `full` takes over the
  playlist with a native loop and hands it back when the call ends; `badge` / `glow` draw over every app.
- **eyebreak** `{enabled, interval_min: 5–120, style: breathe|ring}` — after `interval_min` of continuous input
  (Windows `GetLastInputInfo`; 2 min idle resets the timer) a 24 s 20-20-20 takeover. Postponed while On Air (camera or
  mic in use, even with the On-Air display off) and while a full-screen app or game runs (`SHQueryUserNotificationState`).
- **ntfy** `{enabled, server: "https://ntfy.sh", topics: "a,b", token, style: auto|banner|full, duration, route_prefix: "app-", lifetime}` —
  streams `{server}/{topics}/json`; each message becomes a notification (priority 1–2 grey/blue banner, 3 cyan banner,
  4 amber full screen, 5 red full screen; emoji tags such as `warning`, `white_check_mark`, `house` pick the icon). A
  message tagged `app-<name>` goes into custom app `<name>` for `lifetime` seconds instead of popping up.
  Reconnects resume with `since=<last id>`.
- **homeassistant** `{url: "http://homeassistant.local:8123", token: "<long-lived access token>"}` — used by the
  `hassentity` app (polls `/api/states/{entity}` every `poll` s, `/api/history/period` for the sparkline).

Secrets (`token`) are write-only: responses and `/api/state` carry `"token": "••••last4", "token_set": true`. Sending the
mask back keeps the stored token; `""` clears it. Tokens are never logged.

```powershell
# phone → panel with ntfy (no account): subscribe, then post from anywhere
curl -X PATCH localhost:8765/api/integrations/ntfy -H "content-type: application/json" -d '{"enabled":true,"topics":"dotdeck-7f3k2q"}'
curl -H "Title: Laundry" -H "Tags: white_check_mark" -d "Dryer done" ntfy.sh/dotdeck-7f3k2q
curl -H "Priority: 5" -H "Tags: rotating_light" -d "Water leak in the basement" ntfy.sh/dotdeck-7f3k2q
curl -H "Tags: door,app-garage" -d "OPEN" ntfy.sh/dotdeck-7f3k2q         # → custom app "garage"
```

## Home Assistant → DotDeck (inbound control)

Home Assistant drives the panel through the REST API with `rest_command` (DotDeck has no auth: keep it on your LAN
and set `host = "0.0.0.0"` in `dotdeck.toml` only on a trusted network). In `configuration.yaml`:

```yaml
rest_command:
  dotdeck_notify:          # pop a notification
    url: "http://192.168.1.50:8765/api/notify"
    method: POST
    content_type: "application/json"
    payload: '{"title":"{{ title }}","message":"{{ message }}","icon":"{{ icon | default(''bell'') }}","color":"{{ color | default(''#00dcff'') }}","style":"{{ style | default(''banner'') }}"}'
  dotdeck_show_app:        # switch app, optionally for a while
    url: "http://192.168.1.50:8765/api/apps/{{ app }}/activate"
    method: POST
    content_type: "application/json"
    payload: '{"revert_after": {{ seconds | default(60) }}}'
  dotdeck_custom:          # a custom app in the rotation (AWTRIX-style)
    url: "http://192.168.1.50:8765/api/custom/{{ name }}"
    method: POST
    content_type: "application/json"
    payload: '{"text":"{{ text }}","icon":"{{ icon }}","color":"{{ color | default(''#ffffff'') }}","lifetime":{{ lifetime | default(900) }}}'
  dotdeck_indicator:       # corner status square
    url: "http://192.168.1.50:8765/api/indicators/{{ slot }}"
    method: POST
    content_type: "application/json"
    payload: '{"color":"{{ color }}","blink":{{ blink | default(0) }}}'
```

```yaml
# automation: keep the outside temperature in the rotation
automation:
  - alias: "Panel: outside temperature"
    trigger: [{ platform: state, entity_id: sensor.outdoor_temperature }]
    action:
      - service: rest_command.dotdeck_custom
        data: { name: outside, text: "{{ states('sensor.outdoor_temperature') }}°", icon: temp, color: "#ffaa00" }
  - alias: "Panel: garage open"
    trigger: [{ platform: state, entity_id: cover.garage, to: open, for: "00:05:00" }]
    action:
      - service: rest_command.dotdeck_notify
        data: { title: GARAGE, message: "Open for 5 minutes", icon: warn, color: "#ffaa00", style: full }
      - service: rest_command.dotdeck_indicator
        data: { slot: 2, color: "#ffaa00", blink: 1000 }
```

Outbound (DotDeck reading HA): set the URL and token in Settings → Integrations → Home Assistant, then add the
**Home Assistant** app (`hassentity`) with an entity id, e.g. `sensor.living_room_temperature`.

## Autopilot

| Method | Path | Body |
| --- | --- | --- |
| GET | `/api/autopilot` | `{enabled, rules, active}` — `active` is the index of the rule in control |
| PUT | `/api/autopilot` | `{enabled, rules: [{match: "spotify" or "title:youtube", app, settings?}]}` — first match wins |

## Playlist

| Method | Path | Body |
| --- | --- | --- |
| GET | `/api/playlist` | |
| PUT | `/api/playlist` | `{enabled, items: [{app, duration (3–3600), settings?: overrides, enabled?}]}` — overrides validated per app |
| POST | `/api/playlist/{play|stop|next|prev}` | |

## Multiplayer (local Wi-Fi)

Friends join a game from their phones: the panel shows a join QR code for `http://<LAN IP>:<port>/p/<code>`, the
phone opens a controller page (d-pad + A/B, no install) and gets the next free seat. Seat 1 is the host (keyboard
in the studio); seats without a person are played by the AI. Games declare `max_players` (currently: X and 0 = 2,
Pong = 2, Light Cycles = 4).

| Method | Path | Body / notes |
| --- | --- | --- |
| GET | `/api/play/lobby` | `{lobby: null | {code, app, url, max_players, lan_ready, seats: [{seat, name, color}]}, lan_ready, games: [{id, name, max_players}]}` |
| POST | `/api/play/lobby` | `{"app": "<game id>"}` — opens a lobby, shows the game with the join QR |
| POST | `/api/play/lobby/start` | hide the QR, play with whoever joined (the host's A key does the same) |
| DELETE | `/api/play/lobby` | close it and disconnect the phones |
| GET | `/p/{code}` | the phone controller page (reachable from the LAN) |
| WS | `/ws/p/{code}` | phone → `{"k": "up|down|left|right|a|b"}`, `{"type": "ping", "t"}`; server → `hello {seat, color, game}`, `state {status}` (4 Hz), `pong`, `full`, `closed` |

**LAN access.** The engine listens on all interfaces (`host = "0.0.0.0"`) so phones can join, but the `LanGate`
middleware only lets other devices reach `/p/…` and `/ws/p/…` with a valid room code; the studio and every other
endpoint answer 403 to non-local clients. Set `lan_studio = true` in dotdeck.toml to use the full studio from other
devices. Windows asks once to allow Python on private networks — allow it, or phones can't connect.

**Latency.** Phone presses are sent on touch-down over the LAN (~5–20 ms, shown on the phone) and applied
in-process exactly like the host's keyboard, waking the engine immediately; the studio preview shows the result at
once. The panel itself is bounded by BLE flow control (~100–200 ms per full frame), so multiplayer games keep
frames small (dark arenas, few changing pixels) to stream at ~9 fps.

## Presets (one-tap playlists)

Built-in presets are generated from the app registry: one per category (`cat-games`, `cat-pets`, `cat-time`,
`cat-data`, `cat-media`, `cat-creative`, `cat-ambient`, `cat-productivity`), curated mixes (`dashboard`, `chill`,
`planet`) and `everything`. Apps that need setup first (repos, tokens, servers) or are interactive are left out.

| Method | Path | Body / notes |
| --- | --- | --- |
| GET | `/api/presets` | `[{id, name, icon, builtin, items: [{app, duration}]}]` — your own presets first |
| POST | `/api/presets/{id}/play` | `{shuffle?: bool}` — replaces the playlist and starts it |
| POST | `/api/presets` | `{name}` — saves the current playlist as your own preset |
| DELETE | `/api/presets/{id}` | your own presets only (404 for built-ins) |

`/api/state` → `engine.active_preset` (id or null) and `engine.preset` (`{id, name, shuffle}` or null) while a
preset drives the playlist.

## Global settings & device

| Method | Path | Body |
| --- | --- | --- |
| PATCH | `/api/settings` | `{brightness?: 5–100, power?, flip?, transition?: cut|push|fade|wipe, units?: metric|imperial, location?: {city} or {lat, lon, city}, audio_source?: system|mic, os_notifications?: {enabled, style: banner|full, duration, only, exclude}}` |
| PATCH | `/api/display` | `{max_fps?: 0.5–30 (the panel "Hz"), packet_gap_ms?: 0–200, night?: {enabled, start: "HH:MM", end, brightness}}` → the merged display config |
| GET / PUT | `/api/calibration` | panel colour calibration `{red, green, blue, gamma, black_level, lift, saturation}`; PUT re-bakes clips |
| POST | `/api/calibration/pattern/{white|gamma|black|saturation|rgb|preview}` | show a wizard test card on the panel (10 min or until cleared) |
| DELETE | `/api/calibration/pattern` | back to the current app |
| POST | `/api/device/link` | `{enabled}` — Bluetooth link on/off (separate from display `power`) |
| GET / PUT | `/api/autopilot` | `{enabled, rules: [{match, app, settings}]}` — foreground-app rules |
| POST | `/api/device/reconnect` | |
| GET | `/api/device/scan` | nearby `IDM-*` panels |
| POST | `/api/device/raw` | `{hex: "05 00 04 80 32"}` — advanced, sends raw protocol bytes |

## Media

| Method | Path | Notes |
| --- | --- | --- |
| GET | `/api/media` | library, newest first |
| POST | `/api/media?show=true` | multipart `file`; PNG/JPG/GIF/WEBP/BMP ≤ 12 MB; shows it in Gallery by default |
| GET | `/api/media/{id}/preview.png?fit=&profile=&scale=` | processed 32×32 first frame |
| GET | `/api/media/{id}/raw` | original file |
| DELETE | `/api/media/{id}` | |
| GET | `/api/nowplaying/art` | current album art (PNG or JPEG, content type sniffed) |
| GET | `/api/apps/{id}/preview.gif` | animated 32×32 library thumbnail, rendered in a sandbox through the panel calibration (cached 20 s) |
| POST | `/api/nowplaying/{toggle|play|pause|next|prev}` | Windows media controls |

## WebSocket `/ws`

Server → client:
- **text** `{"type": "state", "state": <same as GET /api/state>}` — on change (coalesced 50 ms) and every 2 s.
- **binary** 3072 bytes = 32×32 RGB, row-major — whenever the frame changes. Clients only ever receive the newest.

Client → server:
- `{"type": "paint", "pixels": [[x, y, "#rrggbb"], ...]}` — low-latency canvas strokes.
- `{"type": "input", "app": "<any game>", "key": "up|down|left|right|a|b"}` — game controls (the studio sends these
  for every app in category `games`; Space/Enter = `a`, Shift = `b`).
- `{"type": "ping"}` → `{"type": "pong", "t": epoch}`.

## Recipes

```powershell
# CI result banner
curl -X POST localhost:8765/api/notify -H "content-type: application/json" `
  -d '{"title":"CI","message":"main is green","icon":"ok","color":"#00ff78"}'

# show a scrolling message for 30 s, then go back
curl -X POST localhost:8765/api/text -H "content-type: application/json" -d '{"text":"STANDUP IN 5","revert_after":30}'

# BTC-only ticker
curl -X POST localhost:8765/api/apps/markets/activate -H "content-type: application/json" -d '{"settings":{"symbols":"BTC"}}'
```

```python
import httpx
httpx.post("http://127.0.0.1:8765/api/pixels", json={"rows": ["#.#", ".#.", "#.#"], "palette": {"#": "#ff4818"}})
```
