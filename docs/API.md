# HTTP & WebSocket API

Base URL `http://127.0.0.1:8765`. Interactive OpenAPI docs: **`/docs`**. JSON in and out.
Errors: `400` bad request · `404` unknown app/media · `422` validation (`detail` lists fields).

## Read

| Method | Path | Returns |
| --- | --- | --- |
| GET | `/api/health` | `{ok, version, device}` |
| GET | `/api/meta` | apps (id, name, description, icon, category, **schema**, actions; games also `max_players`, `controls` and `modes: [{id, name, min_players, max_players, teams}]` with `teams` = solo/coop/ffa/versus; every app also `platforms` (hosts it works on, `null` = everywhere) and `supported` on this host), palette, fonts, icons, leagues, plugins, and the host: `platform` (`windows`/`macos`/`linux`/`android`), `platform_label`, `features` ({feature: bool}, see [COMPATIBILITY.md](COMPATIBILITY.md)) |
| GET | `/api/state` | full snapshot: `device`, `engine` (mode, current, playlist, overlay, render_ms, takeover, onair, eyebreak, indicators, custom), `settings` (incl. `integrations`, tokens masked), `apps` (settings per app), `providers` |
| GET | `/api/frame.png?scale=1..32` | exactly what the panel shows |
| GET | `/api/frame` | `{width, height, rgb: base64(3072 bytes)}` |
| GET | `/launcher` | the system search bar page (used by `deskdot launcher`; see docs/LAUNCHERS.md) |
| GET | `/api/fly` | the fruit-fly brain while a fly plays (the Fly Brain app, or a game with `pilot: "fly"`): `{active, app, driving, step, eye, on, off, mh, mv, hs, looming, gf, dn, light, spikes, keys: [[step, key]…], anchor, lures: [[x, y, strength]…], odour, preset, world?}`. The maps are 256 values (16×16). Otherwise `{active: false, app}`. Studio only; never drawn on the panel. |
| GET | `/api/fly/config` | the brain's tuning, shared by every game the fly plays and the Fly Brain app: `{phototaxis: 0.3, looming: 1.0, motion: 1.0, leak: 0.8, threshold: 1.0, refractory: 2, noise: 0.06, escape: 1.0, lure: 1.0, preset: "default"}` (these defaults are the original brain). Bounds: phototaxis 0–1, looming / motion / escape / lure 0–3, leak 0.3–0.99, threshold 0.3–3, refractory 0–10 (int), noise 0–0.5. Stored in `state.json` under `fly`. |
| PATCH | `/api/fly/config` | partial update, returns the full config; 422 on an out-of-range value or an unknown preset. `{"preset": "calm"}` loads a preset (other fields in the same patch then override it); `preset` in the reply names the preset the values match, or `"custom"`. Applies at once to every running brain; the Fly Brain app re-bakes its loop. |
| GET | `/api/fly/presets` | `[{id, name, description, config}]`: `default`, `calm`, `curious`, `twitchy`, `hunter`, `daredevil`. |

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
| `icon` | string | a DeskDot icon name (`GET /api/meta` → `icons`: bell info warn ok error mail chat heart home bolt drop temp sun cloud bulb battery door lock person fire star music clock eye mic cam claude), drawn 2× |
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
  an app whose `LastUsedTimeStop` is 0 is using the device now. DeskDot's own Python is ignored. `full` takes over the
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
curl -X PATCH localhost:8765/api/integrations/ntfy -H "content-type: application/json" -d '{"enabled":true,"topics":"deskdot-7f3k2q"}'
curl -H "Title: Laundry" -H "Tags: white_check_mark" -d "Dryer done" ntfy.sh/deskdot-7f3k2q
curl -H "Priority: 5" -H "Tags: rotating_light" -d "Water leak in the basement" ntfy.sh/deskdot-7f3k2q
curl -H "Tags: door,app-garage" -d "OPEN" ntfy.sh/deskdot-7f3k2q         # → custom app "garage"
```

## Home Assistant → DeskDot (inbound control)

Home Assistant drives the panel through the REST API with `rest_command` (DeskDot has no auth: keep it on your LAN
and set `host = "0.0.0.0"` in `deskdot.toml` only on a trusted network). In `configuration.yaml`:

```yaml
rest_command:
  deskdot_notify:          # pop a notification
    url: "http://192.168.1.50:8765/api/notify"
    method: POST
    content_type: "application/json"
    payload: '{"title":"{{ title }}","message":"{{ message }}","icon":"{{ icon | default(''bell'') }}","color":"{{ color | default(''#00dcff'') }}","style":"{{ style | default(''banner'') }}"}'
  deskdot_show_app:        # switch app, optionally for a while
    url: "http://192.168.1.50:8765/api/apps/{{ app }}/activate"
    method: POST
    content_type: "application/json"
    payload: '{"revert_after": {{ seconds | default(60) }}}'
  deskdot_custom:          # a custom app in the rotation (AWTRIX-style)
    url: "http://192.168.1.50:8765/api/custom/{{ name }}"
    method: POST
    content_type: "application/json"
    payload: '{"text":"{{ text }}","icon":"{{ icon }}","color":"{{ color | default(''#ffffff'') }}","lifetime":{{ lifetime | default(900) }}}'
  deskdot_indicator:       # corner status square
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
      - service: rest_command.deskdot_custom
        data: { name: outside, text: "{{ states('sensor.outdoor_temperature') }}°", icon: temp, color: "#ffaa00" }
  - alias: "Panel: garage open"
    trigger: [{ platform: state, entity_id: cover.garage, to: open, for: "00:05:00" }]
    action:
      - service: rest_command.deskdot_notify
        data: { title: GARAGE, message: "Open for 5 minutes", icon: warn, color: "#ffaa00", style: full }
      - service: rest_command.deskdot_indicator
        data: { slot: 2, color: "#ffaa00", blink: 1000 }
```

Outbound (DeskDot reading HA): set the URL and token in Settings → Integrations → Home Assistant, then add the
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

In the web app (engine in a browser tab, `public_url` set) the QR is `https://idotmatrix.com/p/<code>` instead and
phones reach these same routes over a WebRTC tunnel to the tab; the website's `POST /app/signal` (a Netlify Function,
not an engine endpoint) does the offer/answer swap — see docs/WEB_APP.md, "Play with friends over the internet".

| Method | Path | Body / notes |
| --- | --- | --- |
| GET | `/api/play/lobby` | `{lobby: null | {code, app, url, max_players, lan_ready, seats: [{seat, name, color}]}, lan_ready, games: [{id, name, max_players}]}` |
| POST | `/api/play/lobby` | `{"app": "<game id>"}` — opens a lobby, shows the game with the join QR |
| POST | `/api/play/lobby/start` | hide the QR, play with whoever joined (the host's A key does the same) |
| POST | `/api/play/lobby/switch` | `{"app": "<casino id>"}` — casino rooms only: move the open room to another casino table; phones stay connected on their seats (their socket follows the room's app), wallets carry over, the join QR moves along while the lobby still waits. 404 without a room, 422 for a non-casino app |
| DELETE | `/api/play/lobby` | close it and disconnect the phones |
| GET | `/p/{code}` | the phone controller page (reachable from the LAN) |
| WS | `/ws/p/{code}?cid=<client id>` | phone → `{"k": "up|down|left|right|a|b"}`, `{"type": "ping", "t"}`, `{"type": "profile", name?, color?, avatar?, team?, ready?}` (sanitised: name ≤ 10 drawable chars, colour from the palette and not used by another seat, known avatar id, team 0/1/null, boolean ready); server → `hello {seat, color, game, controls, cid, resumed, profile, max_players, palette, avatars, modes, rulebook}` (`rulebook`: `{game id: {id, title, tagline, how: [step], rules: [{h, items}]}}` from `casino/rulebook.py` — every casino game for a casino room, the app's own guide for Rock Paper Scissors, else `{}`; `**bold**` is the only markup), `state {status}` (on change, ≥ every 2 s), `roster {players: [{seat, name, color, avatar, team, ready, host}]}` (after every join / leave / profile change), `pong`, `full`, `closed`, `replaced`. A dropped phone keeps its seat and profile for 20 s for a reconnect with the same `cid` |

### Casino tables (`category: "casino"`, docs/CASINO.md)

`GET /p/{code}` serves the phone casino page (`casino.html`) instead of the controller when the lobby's app is a
casino table. Same socket, same `hello` / `profile` / `roster`; in addition:

| Direction | Message |
| --- | --- |
| phone → | `{"type": "casino", "op": "bet", "spot": "n:17", "amount": 25}` · `{"op": "unbet", "spot", "amount"?}` (all of it without `amount`) · `{"op": "clear"}` · `{"op": "rebet"}` · `{"op": "done"}` (locks early once everyone with chips is done) · `{"op": "seed", "client_seed": "≤64 printable chars, no ':'"}` · game ops (`hit`, `fold`, `pull`, …; Housie: `buy {count}`, `claim {prize, ticket?}` / `claim_<prize>`, prizes `early5 top middle bottom corners full`). Any op may carry `seq` (an increasing integer); the socket echoes the last applied one as `ack` in every later `state`. The server overwrites `player` with the socket's seat; host ops from a phone are refused |
| → phone | `state {status, private, ack?}` — `status` is public (every phone + the studio); `private` (from `App.private_status(seat)`) only ever reaches that seat's socket |

`status` (casino): `{casino, game, name, table_theme {id, name, css {felt, felt2, felt3, accent, accent_hi, accent_lo, accent_deep, accent_rgb, ink, wing, wing2, wing3}}, phase, round, hash (commitment of this round), ends_in (whole s, null =
waiting for the first chip), reveal_in, next_in, paused, rules, totals {spot: credits, all players}, spot_bets {spot: [{seat, name, color, amount}]} (who is on each spot, table order — phones and the studio draw the same dots from it), rev (the session's change counter: keep the newest status when two feeds race), deal? (Andar Bahar while dealing: {joker, first, cards so far, matched}), bettors, done
(seats, the host `"host"` first),
house {base_credits, min_bet, max_bet, bet_seconds, result_seconds, turn_seconds, auto_next}, edges {bet kind: house
edge}, players [{seat, name, color, avatar, online, credits, staked, net, biggest}] (leaderboard order), history
[{round, game, label, tone, outcome, rules, proof {nonce, hash, client_seed, server_seed}}], lobby, max_players,
result? {round, outcome, label, tone, winners [{seat, name, net}]} (result phase only)}`. The outcome is never in
`status` before the result phase.

`private`: `{seated, pid, seat, name, credits, escrow, net, biggest, client_seed, kicked, notice {id, text, kind:
error|info|result}, bets {spot: credits}, staked, last_bets, can_bet, done, ops, result? {round, stake, payout, net,
wins}}`.

**Bets are frozen from the lock until settlement:** every bet op outside `phase == "betting"` is refused ("Bets are
closed") and changes nothing.

Host ops: `POST /api/apps/{id}/actions/casino` with `{"op": …}` (local only; `player` defaults to `"host"`):

| op | payload | effect |
| --- | --- | --- |
| `start_round` | | open betting (from idle / result) |
| `lock` | | close betting now ("spin now") |
| `settings` | any `house` keys | table settings for every casino game |
| `credits` | `{seat \| pid \| all: true, set \| add}` | set / top up a wallet (logged in the ledger) |
| `kick` | `{seat \| pid, on?: bool}` | take a player off the table (open bets refunded while betting) |
| `pause` | `{on?: bool}` | freeze every timer (toggle without `on`) |
| `reset_session` | `{base_credits?}` | everyone back to base credits, history cleared |
| `pace` | `{seconds}` or `{delta}` | Housie (a game's own `host_ops`): seconds between calls (3–20), applied at once → `{call_seconds}` |
| `verify` | `{round}` | recompute a past round from its revealed seeds → `{ok, hash_ok, matches, outcome, proof}` |
| `view` | `{spots?: bool}` | read-only, for the studio's casino mode: `{status (fresh), private (the host seat's own view; `{seated: false}` until the host first plays — looking never seats the host), players (leaderboard + `pid`, `kicked`), spots? [{id, label, kind, pays, numbers}], avatars? {id: {name, px}}, guide? (this game's rulebook, with `spots`), themes? [table_theme…] (with `spots`)}` |

The host can also play from the studio with the player ops (`{"op": "bet", …}` → seat `"host"`).

**LAN access.** The engine listens on all interfaces (`host = "0.0.0.0"`) so phones can join, but the `LanGate`
middleware only lets other devices reach `/p/…` and `/ws/p/…` with a valid room code; the studio and every other
endpoint answer 403 to non-local clients. Set `lan_studio = true` in deskdot.toml to use the full studio from other
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
| PATCH | `/api/display` | `{max_fps?: 0.5–30 (the panel "Hz"), packet_gap_ms?: 0–200, smoothing?: 0–0.6 (temporal smoothing of streamed frames, 0 = off), motion_preset?: str, night?: {enabled, start: "HH:MM", end, brightness}}` → the merged display config |
| GET / PUT | `/api/calibration` | panel colour calibration `{red, green, blue (0.3–1.2), gamma (0.5–2.5), gamma_red/green/blue (0.7–1.4), black_level, lift (0–40), saturation (0–2), contrast (0.6–1.6), temperature (3000–9500 K, 6500 = neutral), level (0.5–1), dither (bool), preset (tag)}`; every field defaults to "no change"; PUT re-bakes clips |
| GET | `/api/calibration/presets` | `{presets: [{id, name, group: claude|inspired|standard, blurb, values, swatches: [7 hex]}], groups, disclaimer, current}` |
| POST | `/api/calibration/preset/{id}` | `{keep_balance?: true, apply?: true}` → the preset's calibration (keeps the measured RGB gains unless `keep_balance: false`); saved unless `apply: false` |
| POST | `/api/calibration/quick` | `{room: bright|dim|dark, use: mixed|text|photos|games, tint: neutral|blue|yellow|green|pink, apply?: false}` → "Quick match" calibration |
| POST | `/api/calibration/gains` | a calibration → `{gains, temperature_gains}` (effective per-channel gains) |
| GET | `/api/calibration/videos` | the animated calibration videos and motion tests `{videos, motion, fps}` |
| POST | `/api/calibration/test` | `{video: bars|ramp|pulse|white|skin|sky|wheel|card, a: calibration, b?: calibration, layout?: ab|wipe, split?: 0–32, labels?: [str, str], seconds?}` — plays an animated test video on the panel (`a` full screen; `a`+`b` "ab" = same content in both halves, A left / B right; "wipe" = before/after split at `split`). The studio preview receives the *uncorrected reference* frame meanwhile |
| POST | `/api/calibration/pattern/{white|gamma|black|saturation|rgb|preview}` | show a first-generation still test card on the panel (10 min or until cleared) |
| DELETE | `/api/calibration/pattern` | stop any test card / video / motion test |
| GET | `/api/motion` | `{presets, limits (fixed link physics), current: {max_fps, packet_gap_ms, smoothing, transition, preset}, tests}` |
| POST | `/api/motion/test` | `{test: ufo|ball|scroll|sweep|pan|live|transition, a: {fps 3–12, speed 1–24 px/s, soft, smoothing 0–0.6, transition}, b?: same, layout?: stack|alternate, mode?: stream|clip}`; `clip` bakes A as a native GIF (≤ 10 fps, ≤ 40 KB) — 429 if within 20 s of the last test upload |
| POST | `/api/motion/preset/{smoothest|balanced|ble_friendly|calm}` | applies `max_fps`, `packet_gap_ms` (never < 18), `transition`, `smoothing` |
| POST | `/api/motion/autotune` | `{seconds?: 2–8, apply?: false}` → streams the heaviest test at 12 fps, measures the delivered rate, returns `{max_fps, packet_gap_ms, transition, smoothing, measured_fps, frame_bytes}` |
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
