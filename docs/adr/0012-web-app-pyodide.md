# ADR 0012: A web app — the real engine in the browser (Pyodide) with a Web Bluetooth bridge

- **Status:** Accepted (first version; real-panel verification pending)
- **Date:** 2026-10-03

## Context

Users want to try DeskDot without installing Python, Node or an APK: open idotmatrix.com, click, and the panel
lights up. Chromium browsers (desktop and Android) ship Web Bluetooth, which can write the panel's `fa02`
characteristic and receive `fa03` acks.

Options considered:

- **Rewrite the engine in TypeScript.** Loses the 90+ apps, providers and tests, and doubles every future change.
- **A thin JS client that streams frames rendered elsewhere.** Still needs a server; not "no install".
- **Run the Python engine in the browser with Pyodide.** Pyodide 0.29.5 is CPython 3.13.2 and ships numpy 2.2,
  Pillow 11.3, pydantic 2.12 / pydantic-core 2.41, FastAPI 0.116 / Starlette 0.47 and httpx 0.28 as wasm/pure
  wheels. Feasibility check: the unchanged package imports and boots (`create_app` + ASGI lifespan) in ~3 s under
  Node and ~6 s in a browser worker, renders apps, encodes PNG/GIF.

## Decision

- Run `src/deskdot` unchanged in a **Web Worker** under Pyodide (pinned, official jsDelivr CDN). A new entry point
  `web_main.py` (like `android_main.py`) builds the app with `device="web"` and serves requests by calling the
  ASGI app directly — no sockets.
- Keep the studio unchanged: a page host script shims `fetch("/api/…")` and `new WebSocket("/ws")` into worker
  messages; a service worker does the same for `<img src="/api/…">` and caches the runtime.
- Add `device/web.py` (`WebBleDevice`), the same bridge shape as the Android backend: the page owns the GATT session,
  writes are acknowledged one at a time by token, acks forwarded, link loss reported. Everything panel-specific stays
  in `device/base.py` (rules 5–7, 13 unchanged).
- Add a `"web"` platform to `platforms.py` with no host features; the existing greying-out machinery hides what
  can't work in a tab.
- Persist the data dir in IndexedDB (Emscripten IDBFS). Fetch provider data from the tab; fall back to a
  host-allowlisted Netlify Function for the APIs without CORS.
- Serve it at `/app/` of the existing Netlify site with its own CSP.

## Consequences

+ No install; the same apps, settings and panel behaviour as the desktop; one code base.
+ The bridge is unit-tested on the desktop (`tests/test_web_device.py`) and end-to-end with a mock Web Bluetooth
  device in a headless browser.
− First visit downloads ~18 MB and start-up takes ~10 s (CPU-bound import); the service worker makes repeat visits
  network-free but not instant.
− The panel runs only while the tab is open; OS features (media, screen, audio, system stats, notifications),
  LAN multiplayer and MCP are unavailable in the browser.
− Browsers hide the BLE MTU: packet size is guessed per OS, stepped down on refusal, and user-overridable.
− A CORS proxy function is now part of the site (allowlist must follow the providers' hosts).
− Pyodide upgrades must keep the engine's dependencies available; the engine ships as CPython 3.13 byte-code, so
  the build pins the Python minor version.
