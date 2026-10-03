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

Everything that doesn't need the computer itself — `GET /api/meta` reports `platform: "web"` and every host
feature `false`, so the studio greys out the rest with its usual badges ("Windows/macOS/Linux only", "Not on
Browser"):

| Works | Doesn't (needs the desktop app, a Pi or the Android app) | Why |
| --- | --- | --- |
| All games, clocks, timers, pets, loops, ambient and creative apps | Now Playing, Active App | no access to the OS media session / windows |
| Live-data apps (weather, sports, markets, stocks, flights, space, quakes, rain radar, news, trivia…) | Screen Mirror, Camera Mirror | not wired to `getDisplayMedia`/`getUserMedia` (yet) |
| Playlists, presets, autopilot, notifications, text, agent states | Visualizer, pets' "dance to music" | no sound capture (`soundcard`) |
| Canvas drawing, photo/GIF upload, Font Lab (bitmap fonts), AI creator (your Gemini key) | System Monitor, Composer CPU/RAM layers | no psutil in a tab |
| Calibration wizard, brightness, night mode, display & motion settings | On Air, idle eye-break, OS notification mirroring, sleep hand-off | Windows/macOS system APIs |
| Integrations reachable over https (ntfy, GitHub CI, iCal URLs, Home Assistant **with an https URL** that allows CORS) | Phone multiplayer over Wi-Fi (`/p/<code>`), MCP / Claude Code hooks | no server a phone or agent could reach |
| Settings, uploads and calibration persist (IndexedDB) | LAN services on plain http (OBS, printers, AnkiConnect, local Home Assistant) | an https page may not call http LAN addresses |

The panel runs only while the tab is open (it may be in the background). For 24/7 use the desktop app, a
Raspberry Pi or the Android app — and close the tab first: a panel accepts one connection at a time.

**Browsers:** Chrome, Edge, Opera (and other Chromium browsers) on Windows, macOS, ChromeOS and Android. Linux
Chrome needs `chrome://flags/#enable-experimental-web-platform-features`. Brave needs
`brave://flags/#brave-web-bluetooth-api`. Firefox and Safari have no Web Bluetooth: the page explains it and the
studio still runs (preview only). iPhone/iPad: use the **Bluefy** browser.

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
off it; `/app/proxy` is routed to the function by its own `config.path`. The normal desktop build (`web/dist`) is
untouched: the web build only happens with `DESKDOT_WEBAPP=1`.

Files: `src/deskdot/web_main.py`, `src/deskdot/device/web.py`, `web/webapp/{host.js,host.css,worker.js,sw.js}`,
`scripts/build_webapp.py`, `netlify/functions/cors-proxy.mjs`, tests in `tests/test_web_device.py`.

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
