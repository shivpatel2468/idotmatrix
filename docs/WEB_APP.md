# The web app — DeskDot in a browser tab (idotmatrix.com/app/)

Open **https://idotmatrix.com/app/**, click **Connect panel**, pick your `IDM-…` panel: the full studio drives the
panel straight from the tab. Nothing to install. Decision record: [adr/0012-web-app-pyodide.md](adr/0012-web-app-pyodide.md).

## How it works

```
 page (main thread)                                   Web Worker
 ┌──────────────────────────────────────────┐        ┌───────────────────────────────────────────┐
 │ studio (React, unchanged, base /app/)    │        │ Pyodide 0.29.5 (CPython 3.13, WebAssembly)│
 │   fetch("/api/…")  ─┐                    │ post-  │   deskdot.web_main                        │
 │   new WebSocket("/ws") ─┤ host.js shims ─┼─Message─┼─▶ server.create_app(cfg) — the same FastAPI │
 │   <img src="/api/…"> ─ sw.js ───────────┘ │        │     app, called through ASGI directly      │
 │                                          │        │   Engine · providers · 90+ apps            │
 │ Web Bluetooth GATT session (host.js) ◀───┼────────┼── device/web.py (WebBleDevice)             │
 │   fa02 writes · fa03 acks                │        │   pacing, acks, latest-frame-wins (base.py)│
 └──────────────────────────────────────────┘        └───────────────────────────────────────────┘
        state.json, uploads → IndexedDB (Emscripten IDBFS, synced after every save)
```

- **Same engine.** The worker runs the real `src/deskdot` package; only the transport differs. Requests from the
  studio reach `server.create_app()` through the ASGI protocol (`web_main.http()` / `ws_open()`), so every endpoint,
  setting and app behaves as on the desktop.
- **Same panel physics (rules 5–7, 13).** `device/web.py` implements the three `Device` hooks on top of a message
  bridge to the page (Web Bluetooth only exists on the main thread). All pacing (`packet_gap_ms`), the one-frame
  ack pipeline, GIF chunk acks, the GIF cool-down and latest-frame-wins stay in `device/base.py`. Protocol bytes
  are untouched. The engine never disconnects on its own; a link loss reconnects to the same device without a click.
- **One owner (rule 4).** A Web Lock (`deskdot-web-engine`) lets only one tab run the engine; a second tab says so.
- **Browser differences** are handled once in `web_main.patch_runtime()`: no threads (`asyncio.to_thread` runs inline),
  no sockets (`httpx.AsyncClient` gets a `fetch()` transport), and the unvendored `sqlite3` gets a stand-in (only
  the unsupported OS-notifications provider imports it).
- **Packet size.** Browsers don't expose the BLE MTU. The page guesses per OS (Windows/ChromeOS/Linux 512 B,
  macOS 182 B, Android 20 B — Chrome on Android doesn't raise the MTU and would silently truncate longer writes)
  and, when the stack refuses a write, re-sends it in smaller paced pieces and tells the engine (`onWriteSize`).
  The connection pill has a manual override (20 / 182 / 244 / 512 B).
- **Live data & CORS.** Providers fetch from the tab, so each API must allow browsers (most do). The rest — and
  plain-http APIs like ip-api.com — go through `/app/proxy`, a Netlify Function with a fixed host allowlist
  (`netlify/functions/cors-proxy.mjs`, GET only, no cookies, 3 MB cap). The engine tries direct first and remembers
  which hosts need the proxy.
- **Library thumbnails** come from the website's prebuilt reels (`/media/apps/<id>.gif`, served by the service
  worker for `/api/apps/<id>/preview.gif`) instead of rendering 90 GIFs in WebAssembly. They show default settings.
- **Caching.** The service worker (`/app/sw.js`, scope `/app/`) caches the pinned Pyodide CDN files, the engine
  archive and the studio; the second visit downloads nothing and the app opens offline (live data still needs the
  network, the panel doesn't).

## What works in the browser

Everything that doesn't need the computer itself, plus the camera, a shared screen and sound through the
browser's own permission prompts — `GET /api/meta` reports `platform: "web"` with `screen`, `camera`, `audio` and
`audio_loopback` `true` and every other host feature `false`, so the studio greys out the rest with its usual badges
("Windows/macOS/Linux only", "Not on Browser"):

| Works | Doesn't (needs the desktop app, a Pi or the Android app) | Why |
| --- | --- | --- |
| All games, clocks, timers, pets, loops, ambient and creative apps | Now Playing, Active App | no access to the OS media session / windows |
| Live-data apps (weather, sports, markets, stocks, flights, space, quakes, rain radar, news, trivia…) | Screen Mirror on phones / tablets | no `getDisplayMedia` on Android / iOS |
| Playlists, presets, autopilot, notifications, text, agent states | Camera Mirror's face tracking and webcam hardware controls | no OpenCV in the browser (the picture is centre-cropped; zoom / pan work) |
| **Camera Mirror, Screen Mirror, Visualizer, pets' "dance to music"** — after the browser asks (see below) | Screen Mirror "Active window" / "Around cursor" | the browser's picker chooses the window instead |
| Canvas drawing, photo/GIF upload, Font Lab (bitmap fonts), AI creator (your Gemini key) | System Monitor, Composer CPU/RAM layers | no psutil in a tab |
| Calibration wizard, brightness, night mode, display & motion settings | On Air, idle eye-break, OS notification mirroring, sleep hand-off | Windows/macOS system APIs |
| Integrations reachable over https (ntfy, GitHub CI, iCal URLs, Home Assistant **with an https URL** that allows CORS) | MCP / Claude Code hooks | no server an agent could reach |
| **Play with friends** (multiplayer games, casino rooms): phones join from anywhere by the QR code — see below | | |
| Settings, uploads and calibration persist (IndexedDB) | LAN services on plain http (OBS, printers, AnkiConnect, local Home Assistant) | an https page may not call http LAN addresses — app by app: [App support in the browser](#app-support-in-the-browser) |

### Camera, screen and sound

The engine can't open devices from its worker, so it asks the page: while an app that needs one is on the panel,
`providers/webmedia.py` sends `want(kind)` through the worker's `deskdotMedia` bridge, `web/webapp/host-media.js`
captures, shrinks and sends back, and `stop(kind)` releases the device the moment the app leaves the panel (the
camera light goes off). The studio shows a card under the panel (`web/src/components/MediaPrompt.tsx`):
"Allow camera" / "Choose screen" / "Allow microphone" / "Share sound", then "Stop sharing" while live, and a
friendly message with **Try again** after a refusal. Nothing is recorded or uploaded; frames go from the page to
the worker in the same tab.

| Message | Direction | Payload |
| --- | --- | --- |
| `{t:"media", op:"want", kind, opts}` | worker → page | camera `{index}`, screen `{}`, audio `{source: "system" or "mic"}` |
| `{t:"media", op:"stop", kind}` | worker → page | the app left the panel |
| `{t:"media-frame", kind, w, h, data}` | page → worker | RGB bytes (transferred), ≤ 160 px (camera) / 192 px (screen) on the long side, ≤ 10 / 8 fps |
| `{t:"media-audio", sr, source, data}` | page → worker | the newest 2048 float32 samples, ~23×/s (a ScriptProcessorNode) |
| `{t:"media-state", kind, state, detail}` | page → worker | `waiting` (needs a click) · `starting` · `live` · `denied` · `error` · `stopped` · `unsupported` |
| `{t:"media-hello"}` | page → worker | the add-on loaded: the engine repeats what it still wants |

The providers produce exactly what the desktop ones do (32×32 RGB frames through the same image controls; the same
32-band spectrum, peaks, level, waveform, beat and bpm analysis), so the apps are unchanged.

- **Camera** (`getUserMedia`): Chrome, Edge, Firefox, Safari, on computers and phones. Camera index 0 = the front /
  default camera, 1+ = the next camera (the back camera on a phone). Once allowed, it starts without a click.
- **Screen** (`getDisplayMedia`): desktop Chrome, Edge, Firefox, Safari — always from a click ("Choose screen"); the
  browser's picker offers a screen, a window or a tab (not the studio's own tab). Not on Android / iOS: the card
  says so. Stopping from the browser's own "Stop sharing" bar works too.
- **Sound**: Settings → Audio → Listen to. *Microphone* = `getUserMedia({audio})` everywhere. *System audio* =
  share a tab (or, on Windows / ChromeOS, the entire screen) with **Share audio** on (`getDisplayMedia`, Chrome /
  Edge on a computer); phones and Firefox fall back to the microphone. The card also offers "Use microphone".
- **Background tab**: frames come from `MediaStreamTrackProcessor` (Chrome / Edge) and sound from the audio clock,
  so mirroring keeps going while you work in another window; browsers without it sample a `<video>` with a timer,
  which drops to ~1 fps while the tab is hidden.
- Not done: idle / eye-break (the Idle Detection API needs its own permission; not wired).

Test: open `/app/`, show Camera Mirror → the card asks → allow → your face on the panel; Camera index 1 on a phone
→ the back camera. Screen Mirror → "Choose screen" → pick a window → it's on the panel; press the browser's "Stop
sharing" → the card offers "Choose screen" again. Visualizer with *Microphone* → bars follow your voice; with
*System audio* → share a YouTube tab with "Share audio". Deny once → the card explains how to allow it again. Leave
the app → the camera light goes off. On Android Chrome: Camera and Visualizer (mic) work, Screen Mirror says it
can't.

The panel runs only while the tab is open (it may be in the background). For 24/7 use the desktop app, a
Raspberry Pi or the Android app — and close the tab first: a panel accepts one connection at a time.

**Browsers:** Chrome, Edge, Opera (and other Chromium browsers) on Windows, macOS, ChromeOS and Android. Linux
Chrome needs `chrome://flags/#enable-experimental-web-platform-features`. Brave needs
`brave://flags/#brave-web-bluetooth-api`. Firefox and Safari have no Web Bluetooth: the page explains it and the
studio still runs (preview only). iPhone/iPad: use the **Bluefy** browser.

## Play with friends over the internet

On the desktop, friends' phones join a game at `http://<laptop>:8765/p/<code>` over the local Wi-Fi. In the web app
there is no server (the engine is inside the tab), so the lobby works differently — same QR, same phone pages:

```
 host's tab (idotmatrix.com/app/)                        friend's phone (idotmatrix.com/p/<code>)
 ┌────────────────────────────────────┐                  ┌─────────────────────────────────────────┐
 │ engine (worker) ── lobby, seats     │                  │ join page (/app/join/, rewritten from /p/*)│
 │ host-rtc.js                         │  1 offer/answer   │ join.js                                  │
 │   polls /app/signal while a lobby ──┼──── /app/signal ──┼── (Netlify Function + Netlify Blobs)      │
 │   is open; answers each phone       │                  │                                          │
 │   RTCDataChannel "deskdot" ◀────────┼── peer-to-peer ──┼──▶ fetch/WebSocket shims → controller.html │
 │   → DeskDotHost.request/socket      │  (STUN, no relay) │    or casino.html, unchanged             │
 │     as client 10.88.0.<n>           │                  │                                          │
 └────────────────────────────────────┘                  └─────────────────────────────────────────┘
```

- **The QR.** `web_main.boot()` passes the page origin as config `public_url`, so `Lobby.url()` is
  `https://idotmatrix.com/p/<code>` and `lan_ready` is true (no "phones can't reach this computer" warning). The
  desktop has no `public_url` and is unchanged.
- **Signalling** (`netlify/functions/signal.mjs`, logic in `netlify/lib/signal-core.mjs`): `POST /app/signal` with
  JSON `{op}` — the host tab `poll`s `{code, secret}` every ~2 s while the engine has an open lobby (the first poll
  registers the room; only the tab holding the secret can read its offers or answer), `answer`s and `close`s; a phone
  sends one `offer {code, peer, sdp}` and `wait`s for the answer (every 1 s, at most 30 s). ICE is non-trickle (each
  side waits for gathering, capped at 3 s), so it's one round trip. Not a relay: codes `[A-Z0-9]{4}`, peer ids
  `[A-Za-z0-9_-]{8,40}`, only SDP-shaped ASCII ≤ 16 KB, ≤ 12 pending offers per room; rooms expire 10 min after the
  host's last poll, offers and answers after 60 s, and a 1 % sweep clears rooms whose tab vanished.
- **The tunnel** (`web/webapp/host-rtc-wire.js`, shared by both ends): one ordered, reliable data channel per phone
  carrying JSON envelopes — `req`/`res` (HTTP, GET `/p/…` only), `ws-open`/`ws-ev`/`ws-send`/`ws-close` (a WebSocket
  session, text or base64 bytes), `hello`/`bye`. Envelopes over 16 KB travel as flagged binary parts. The host gives
  each phone its own client address `10.88.0.<n>`, so the engine's LanGate treats it exactly like a phone on the
  Wi-Fi (phone routes only), and seats come back by `?cid=` after a reconnect.
- **The phone page** (`web/webapp/join/`): "Connecting to the host's table…", the handshake, then
  `GET /p/<code>` through the tunnel (404 → "link expired"; the HTML tells a casino room from a game pad), then it
  writes `/app/join/<kind>.html` into the document. Those are the engine's `controller.html` / `casino.html`, built
  with their inline script moved to `<kind>.js` because the website's CSP allows no inline script (and so the phone
  never runs code sent by a peer). The controller builds its socket URL from `location` (`wss://idotmatrix.com/ws/p/…`),
  which the WebSocket shim routes over the channel. If the link drops, an overlay says "Reconnecting…" and the
  handshake runs again (about a minute of retries); the controller's own reconnect gets its seat back.
- **Cost.** Network traffic only while a lobby is open: the host's poll every 2 s (a read; the room record is
  rewritten every 2 min) and a phone's handful of requests while joining. The game itself is peer-to-peer.

**Relay (TURN).** A direct link fails on many real networks: Indian and other mobile carriers put phones behind
shared (CGNAT) addresses, and on the same Wi-Fi Chrome hides the computer's local address (mDNS) while most home
routers won't loop a connection back to themselves. So `/app/signal` also answers `{op:"ice", code}` — only for a
live room — with short-lived relay credentials, and both sides fall back to the relay when no direct path exists:

- **Cloudflare Realtime TURN** (free up to 1,000 GB a month): Cloudflare dashboard → Realtime → TURN → *Create* a
  TURN key; put its id and API token in Netlify → Site configuration → Environment variables as
  `CF_TURN_KEY_ID` and `CF_TURN_API_TOKEN` (scope: Functions), then redeploy. Credentials live 6 h.
- or any TURN service with static credentials: `TURN_URLS` (comma separated `turn:` / `turns:` URLs),
  `TURN_USERNAME`, `TURN_CREDENTIAL`.

Without either, only direct links work, and a blocked phone says so ("Couldn't reach the host's computer" — try
the same Wi-Fi as the host, or switch between Wi-Fi and mobile data). The game runs in the host's tab: if that tab
closes, phones see "The host's tab isn't answering"; a host tab hidden for a long time may be throttled by the
browser until a phone has connected (keep it in front while friends join). Room codes are 4 characters, as on the
LAN: anyone with the code can take a free seat while the lobby is open. The phone pages come from the website's
build, so a host tab running an older cached engine may briefly mismatch until it reloads.

**Test it end to end** (after `build_webapp.py` and a deploy, or `netlify dev` for the function):
1. Laptop: open `/app/`, wait for the engine, Play → a multiplayer game (Tic-tac-toe) → Play with friends. The QR
   shows `idotmatrix.com/p/<code>`; `window.deskdotRtc.state()` in the console shows the room `open`.
2. Phone on **mobile data** (not the laptop's Wi-Fi): scan the QR. Expect "Connecting to the host's table…", then
   the usual controller; the studio's seat fills in. `window.deskdotJoin.state()` on the phone shows `linked: true`.
3. Play a move; toggle the phone's airplane mode for 5 s: the overlay says "Reconnecting…", then the same seat.
4. Casino: open a casino room the same way; the phone gets the casino table page.
5. Close the lobby in the studio: the phone shows the controller's "Game over" card; rescanning says
   "No open game with this code".
6. Signalling only: `node --test tests/js/*.test.mjs`.

## App support in the browser

Audited app by app on 2026-10-04: what each app needs (providers, hosts, sockets, OS calls, files) and whether a
browser tab can give it that. Apps marked ❌ declare it in code (`platforms` without `"web"` plus a `web_reason`);
the library shows them dimmed with a **Not on Browser** badge, the settings banner says why, the panel shows
"NOT ON WEB" and the playlist skips them. `tests/test_web_apps.py` keeps this honest: every provider host is either
CORS-friendly or on the proxy allowlist, and every ❌ app has a reason.

Legend: ✅ works · 🟡 works with a limit · ❌ not available.

| Apps | Browser | Needs / why |
| --- | --- | --- |
| Games: Snake, Asteroids, Breakout, Light Cycles, Dig World, Dino Runner, Flappy, Four Up, 2048, Infinity, Invaders, Leaf Leap, Maze Chase, Mines, Neon Heat, Penguin Escape, Pong, Racer, Rock Paper Scissors, Starship, Street Surge, Tetris, X and 0, Player Card, 3D Dungeon Raycaster, 3D Wireframe | ✅ | nothing but the engine (numpy). Multiplayer: phones join over WebRTC (see "Play with friends") |
| Casino: Roulette, 7 Up 7 Down, Blackjack, Baccarat, Slots, Texas Hold'em, Teen Patti, Andar Bahar, Big Six | ✅ | same |
| Clock, Countdown, Focus Timer, Five O'Clock Somewhere, Progress, Habits, Focus Companion | ✅ | time zones from Pyodide's `tzdata` package |
| Claude Mascot, Ambient, Flocking Boids, Neuromorphic Cortex, Fly Brain, Emotes, Loops, Pixabots, QR Code, Falling Sand, Synthwave Horizon, Text, Canvas, Firmware Modes | ✅ | baked clips / native modes; clip bakes take ~0.1–0.4 s in WebAssembly |
| Gallery, Photo Frame (uploads) | ✅ | uploads live in IndexedDB |
| Weather, Air Quality, Tides & Surf, What to Wear, Sun & Moon, Day & Night, Planets Tonight, Pet World | ✅ | Open-Meteo, sunrise-sunset.org (CORS). Location by IP goes through the proxy (ip-api.com is http only) — set a city to skip it |
| Live Scores, Crypto Ticker, Currency, Earthquakes, Rain Radar, Space (+ ISS), Trivia, Pokédex, Chess Puzzle, Holidays, Headlines, Daily Dose, Game Deals, Pixel Avatar, GitHub Graph, Stocks | ✅ | direct where the API allows CORS; Yahoo/Stooq (stocks), Hacker News/Lobsters, ZenQuotes, CheapShark, Mojang, github.com, open-notify, Google holiday calendars through `/app/proxy` |
| Photo Frame (online sources) | ✅ | Met and Cleveland Museum images come from CDNs without CORS: proxied |
| Flight Radar | 🟡 | adsb.lol / airplanes.live / OpenSky have no CORS: every poll is a proxy call, so the browser polls every 15 s instead of 8 s |
| Calendar | 🟡 | Google, Outlook / Microsoft 365 and iCloud published `.ics` links go through the proxy (the secret URL passes through the site's function, never logged); other hosts must allow CORS |
| CI Radiator | ✅ | api.github.com allows CORS (a token is kept in this browser's storage) |
| Home Assistant | 🟡 | needs an **https** URL (Nabu Casa or your reverse proxy) with `https://idotmatrix.com` in HA's `http: cors_allowed_origins`; `http://homeassistant.local` is blocked (mixed content) and the error says so |
| Media Server (Plex / Jellyfin) | 🟡 | same: an https address that allows CORS (e.g. Plex's `https://…plex.direct:32400`) |
| Uptime Monitor | 🟡 | sites that allow CORS get their real status code; others only "reachable or not" (an opaque `no-cors` request, still UP/DOWN, no code); `tcp://host:port` targets show "NO TCP IN BROWSER" and never alert (no sockets) |
| Text Studio (Composer) | 🟡 | CPU / RAM layers show `--%` (no psutil); time, date, weather and prices work |
| Font Lab | 🟡 | the built-in bitmap fonts only (no `assets/fonts` / `data/fonts` folder in a tab) |
| Custom | 🟡 | pushes come from the studio only: scripts and agents can't reach an engine inside a tab (no `POST /api/custom`) |
| Camera Mirror, Screen Mirror, Visualizer, Pet's "Dance to music" | 🟡 | the browser's camera / screen / mic prompts — see "Camera, screen and sound" |
| ntfy pushes (Integrations) | 🟡 | a tab can't hold ntfy's endless stream: the engine polls (`?poll=1&since=…`) every 10 s while the tab is open; a token travels as ntfy's `auth` query parameter (ntfy refuses the `Authorization` preflight) |
| System Monitor | ❌ | no psutil: a tab can't read CPU, memory, disk or network counters |
| Active App | ❌ | a tab can't see the foreground window or app icons |
| Now Playing | ❌ | no access to the OS media session (Spotify, Music, browser players) |
| OBS Status | ❌ | obs-websocket is a plain `ws://` socket on your computer: an https page may not open it |
| 3D Printer (OctoPrint / Moonraker) | ❌ | plain http on the LAN: blocked from an https page (feature `lan`) |
| Anki | ❌ | AnkiConnect answers plain http on 127.0.0.1 and refuses other origins (feature `lan`) |

**Web-only behaviour** (desktop and Android unchanged):

- Requests that fail say why: a LAN address over plain http ("the browser app can't reach plain-http devices on your
  network"), an API without CORS that isn't on the proxy list, or offline — instead of a bare `TypeError`.
  `web_main.is_local_host()` recognises private / loopback / link-local IPs, `localhost`, `*.local` / `.lan` /
  `.home.arpa` and bare names like `octopi`; those are never sent to the proxy.
- The proxy (`netlify/functions/cors-proxy.mjs`) stays an exact-host allowlist (plus one anchored pattern for
  iCloud's numbered calendar hosts), GET only, and now follows redirects by hand so a redirect can't lead off the
  list.
- Settings → Connection hides "Find nearby panels" (Chrome's own chooser, **Connect panel**, does that); the
  Integrations tab explains the https/CORS needs of Home Assistant, ntfy's polling and that scripts can't set the
  status indicators.
- Performance: every app's `render()` stays under ~2 ms in CPython (≈2–3× that in WebAssembly) and the biggest
  clip bake is ~150 ms + ~40 ms GIF encoding, so no app needed a lighter web path.

### What a browser tab can't do (and why)

- **Read the computer** — media session, foreground window, CPU/RAM counters, idle time, OS notifications, the
  Windows privacy registry (On Air), sleep events: no web API exposes them.
- **Talk to plain-http / socket services on your network** — OBS, OctoPrint/Moonraker, AnkiConnect, a local Home
  Assistant or Plex at `http://192.168.…`: an https page may not load http content (mixed content), browsers have
  no raw TCP/UDP sockets (no TCP uptime checks, no mDNS discovery), and a public proxy can't reach your LAN anyway.
- **Be reached** — scripts, Claude Code hooks and the MCP server talk to the engine's HTTP API; inside a tab there
  is no server to call (phones still join games through WebRTC).
- **Hold endless streams** — `fetch()` hands the body over only when it ends, so long-lived streams (ntfy) are
  polled.

## Size and speed (measured 2026-10-03)

| | First visit | Second visit |
| --- | --- | --- |
| Pyodide core (wasm + stdlib, brotli from jsDelivr) | ~5.3 MB | from cache |
| Packages (numpy, Pillow, pydantic-core, FastAPI, ssl, tzdata…) | ~8.4 MB | from cache |
| `site/app` (studio 2.2 MB uncompressed + engine byte-code 2.1 MB + host) | ~4.4 MB | from cache |
| Engine ready (headless Chromium, low-RAM test laptop) | ~10–15 s | ~10–15 s |

Start-up is CPU-bound (starting CPython, importing numpy/FastAPI/pydantic and the 90 apps); the engine ships as
byte-code (`.pyc`), which cut the import from ~9.5 s to ~5.5 s. The studio is usable (preview mode) as soon as the
engine reports ready.

## Build and deploy

```powershell
uv run python scripts/build_webapp.py            # studio (vite, base /app/) + engine archive + host → site/app/
uv run python scripts/build_webapp.py --skip-studio   # after Python/host changes only
uv run python scripts/build_site_pages.py        # only if site pages changed (the "Open in browser" buttons)
uv run python -m http.server 8799 --directory site   # local test: http://localhost:8799/app/
```

`site/app/` is committed like the rest of `site/`; Netlify publishes it with no build step. Deploy = commit and
push (or `netlify deploy --prod --dir site`). `netlify.toml` gives `/app/*` its own Content-Security-Policy
(Pyodide CDN, `'wasm-unsafe-eval'`, a same-origin worker, https data APIs) and keeps the website's stricter policy
off it; `/app/proxy` and `/app/signal` are routed to their functions by their own `config.path`, and `/p/*` is
rewritten to the join page `/app/join/` (same policy). The functions' one dependency (`@netlify/blobs`, for
`/app/signal`) is in `netlify/package.json`: run `npm install` in `netlify/` once before `netlify deploy`, which
bundles it. The normal desktop build (`web/dist`) is
untouched: the web build only happens with `DESKDOT_WEBAPP=1`.

Files: `src/deskdot/web_main.py`, `src/deskdot/device/web.py`, `src/deskdot/providers/webmedia.py`,
`web/webapp/{host.js,host.css,host-media.js,worker.js,sw.js}`, `web/src/components/MediaPrompt.tsx`,
`web/webapp/{host-rtc.js,host-rtc-wire.js,join/}` (online play), `scripts/build_webapp.py`,
`netlify/functions/{cors-proxy,signal}.mjs`, `netlify/lib/signal-core.mjs`, tests in `tests/test_web_play.py`,
`tests/js/*.test.mjs`, `tests/test_web_device.py`, `tests/test_web_apps.py` (app support, proxy
allowlist) and `tests/test_web_media.py`.

### Testing without a panel

`web/webapp/dev/mock-bluetooth.js` is a fake panel for headless browsers (inject it with Playwright's
`page.addInitScript({ path })`): it records every GATT write in `window.__bleWrites`, refuses packets over 244 B
to exercise the step-down, and `window.__mockDevice.gatt.disconnect()` simulates a link loss. Verified with it:
connect → DIY mode → paced frames at ~6–7 fps → automatic step-down 512 → 244 B → reconnect after a link loss
without a click. `window.deskdotWeb.state()` reports engine, link and packet size.

### Upgrading Pyodide

Bump `PYODIDE_VERSION`/`PYODIDE_PYTHON` in `scripts/build_webapp.py` (the build refuses to run on another Python
minor version, because the engine ships as byte-code), then check the new `pyodide-lock.json` still has numpy,
pillow, pydantic(-core), fastapi, starlette, httpx/httpcore, tzdata; rebuild; open `/app/`; run the mock-panel check.

## Test on a real panel (user steps)

1. Deploy (or run `uv run python -m http.server 8799 --directory site` and open `http://localhost:8799/app/` —
   localhost counts as secure, so Web Bluetooth works there too; the CORS proxy only exists on Netlify).
2. **Stop every other host first**: quit DeskDot on the laptop (don't stop it mid-upload), close the iDotMatrix
   phone app and the DeskDot Android app. The panel should show its pairing/idle screen.
3. In Chrome or Edge on the laptop: open `/app/`, wait for "Engine running in this tab", click **Connect panel**,
   pick `IDM-…`. Expect: the pill turns green "IDM-… · 512-byte packets" and the panel shows the current app.
4. Check: brightness slider, switch apps (a clock, Snake, Synthwave as a baked GIF clip), draw on the canvas,
   upload a photo, run the calibration wizard's first card. Watch Settings → Device: frames sent rising,
   `link fps` ~6–9.
5. Link speed: if frames look corrupted or never show, pick **182 B** then **20 B** in the pill and press
   Settings → Device → Reconnect; note which size works for your OS (tell us: it becomes the default).
6. Link loss: switch the panel off and on. Expect "Link lost — reconnecting…" then green again with no click,
   and the same picture restored.
7. Reload the tab: Chrome remembers the panel (`getDevices()`) and reconnects without the chooser on
   Chrome/Edge 2023+ (otherwise click Connect panel once). Your settings and uploads are still there.
8. Background: switch to another tab for a few minutes; the panel keeps animating.
9. Android phone (Chrome): repeat 3–4. Default packet size is 20 B (slow but safe); try 182/244 B and report.
10. iPhone: open `/app/` in **Bluefy**; expect the same flow (Bluefy implements Web Bluetooth).
11. Busy panel: with the desktop app running, click Connect panel — the panel is missing from the chooser or
    the connect fails with "not connected to the iDotMatrix phone app, the DeskDot desktop app…".
