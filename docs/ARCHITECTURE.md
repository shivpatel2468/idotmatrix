# Architecture

```mermaid
flowchart LR
  subgraph Clients
    UI[Studio<br/>React · Vite]
    MCP[MCP server<br/>deskdot-mcp]
    SCR[Scripts · CI · Claude Code hooks]
  end
  subgraph Engine["Engine process (uv run deskdot serve)"]
    API[FastAPI<br/>REST + /ws]
    ENG[Engine runtime<br/>scheduler · playlist · overlay · transitions]
    APPS[Apps<br/>render(Frame, t)]
    PROV[Providers<br/>system · weather · markets · sports · media · lyrics]
    GFX[gfx<br/>Frame · fonts · colour · GIF]
    DEV[Device<br/>latest-frame-wins scheduler]
    BLE[BLE backend · bleak]
    SIM[Simulator]
  end
  PANEL[(iDotMatrix 32×32)]
  NET[(Open-Meteo · Binance · ESPN · lrclib/…)]
  WIN[(Windows media session)]

  UI -- REST / WebSocket --> API
  MCP -- HTTP --> API
  SCR -- HTTP --> API
  API --> ENG
  ENG --> APPS
  APPS -. read cached value .-> PROV
  PROV --> NET
  PROV --> WIN
  APPS --> GFX
  ENG -- PNG frame / GIF / command --> DEV
  DEV --> BLE --> PANEL
  DEV --> SIM
  ENG -- raw RGB frames + state --> API
```

## Layers and their contracts

| Layer | Module | Contract |
| --- | --- | --- |
| **gfx** | `deskdot/gfx` | Pure. `Frame` = numpy `(32, 32, 3) uint8`; every primitive clips. Bitmap fonts, palette, photo calibration, GIF encode with one shared palette. |
| **device** | `deskdot/device` | `protocol.py` = pure byte encoders (pinned by tests). `base.Device` = the only writer to the link: work slots, reconnect supervisor, replay after reconnect. Backends implement `_connect/_disconnect/_write`. |
| **providers** | `deskdot/providers` | Background fetch loops, **ref-counted**: they poll only while an app (or the studio) holds them, linger 30 s, then stop. `value` is last-good; `error` is the last failure. |
| **engine** | `deskdot/engine` | `App` SDK, `Engine` runtime, overlays/transitions. Owns *what* is on screen. |
| **apps** | `deskdot/apps`, `plugins/` | `render(f, t)` pure and fast. Declare `Settings`, `uses`, `kind()`. |
| **server** | `deskdot/server.py` | HTTP + WebSocket. Stateless over the engine. Serves `web/dist`. |
| **mcp** | `deskdot/mcp_server.py` | Thin HTTP client exposing tools to agents. Never touches BLE. |
| **studio** | `web/` | Renders state; frames bypass React and paint straight to a canvas. |

## The tick

One asyncio task runs `Engine._tick()`; the delay to the next tick is `1/fps` of the visible app
(20 Hz during overlays/transitions, 0.5 s for clips when nobody is watching the preview).

0. **Upkeep** (`_platform`): expire indicators and stale custom push apps, follow On Air and the eye-break timer.
1. **Select** the slot: a *takeover* (hidden `onair` / `eyebreak` app while a call is live or a break is due),
   else the manual app, or a playlist item (with *focus* take-over and *relevance* skipping). Fresh custom push
   apps join the rotation after the user's items.
2. **Render** into a fresh `Frame` (or sample the baked clip). Exceptions become an error frame; the loop lives.
3. **Compose** notification overlay and app-switch transition, then the *persistent* overlays
   (`engine/persistent.py`: status indicators, On-Air badge / glow) on top of everything.
4. **Route**:
   - *stream* → PNG → `device.show_frame()` only if the frame changed (dedupe).
   - *clip* → bake once per `clip_key()` in a thread → `device.show_gif()` once. The panel loops it natively.
   - *native* → `device.command(native_command())` once per settings change.
   - overlays and transitions always stream, then the clip/native state is re-asserted. While a persistent
     overlay is visible the frame streams too (a clip app plays from its baked frames), so keep them few.
5. **Publish** the frame to WebSocket clients if it changed (each client holds only the newest frame).

## Why it is fast (and the old build wasn't)

| Old behaviour | New behaviour |
| --- | --- |
| Frames queued in order; the panel fell seconds behind | Single-slot mailbox per kind — at most one frame behind |
| `psutil.cpu_percent(interval=0.1)` inside async handlers | `interval=None`, sampled by a provider every 1 s |
| Weather/crypto/IP lookup fetched on every loop and every UI poll | Ref-counted providers with sensible intervals (weather 10 min, IP 6 h) |
| Lyrics searched every 1.8 s when a song had none | Per-track cache including misses; one background search |
| Library `send()` called `time.sleep()` | Own transport; everything awaits |
| PNG saved to disk, re-read, uploaded | In-memory PNG; deduped |
| Animations streamed frame-by-frame | Loops baked to GIF once; the panel plays them itself |
| UI polled 5 endpoints every 1.8 s | One WebSocket; state pushed on change (coalesced 50 ms) + raw frames |
| LUT rebuilt per image | `lru_cache` |

Measured on the dev machine: render 0.1–1.8 ms per app (tests fail above 50 ms); GIF bake for a 24-frame
mascot ≈ 20 ms and 1.1 KB.

## Device scheduler (`device/base.py`)

Priority on every write turn: **commands** (FIFO) → **gif** (slot) → **pixels** (merged map) → **frame** (slot,
paced by `max_fps`). Before a frame or pixels the scheduler sends `diy_mode(1)` only if the panel isn't already
in DIY mode (entering DIY blanks the panel for ~300 ms). After a reconnect it replays brightness and the last
visual. Link stats (`frames_sent`, `frames_dropped` = superseded, `link_fps`, `last_write_ms`) are exposed in state.

## Screens beyond the panel

The engine is no longer only a panel driver; every screen in the room reads the same state:

- **Phones** join a lobby by QR (`/p/<code>`, `/ws/p/<code>`; `multiplayer.py`, `casino.html`, `controller.html`) and
  may opt in to the live panel frames.
- **TVs** open a code-gated, read-only `/tv/<code>` (`tvlink.py`, `tv.html`, `tv/*.js`): the public `status()`, the
  panel frames, and an app's TV-only `tv_extra()` (a casino round's outcome from the lock on) — docs/TV_VIEW.md.
- **One clock:** casino statuses carry wall-clock anchors (`status.clock`) and sockets answer pings with
  `server_time`, so the studio, phones and TVs slew to the engine's time and flip at the same moment.
- `LanGate` keeps the studio/API local-only; from the LAN only `/p/`, `/ws/p/`, `/tv/`, `/ws/tv/` are reachable.
- In the browser build (docs/WEB_APP.md) the same routes run inside the tab and reach phones/TVs over WebRTC.

## State and persistence

`data/state.json` (debounced 0.4 s): brightness, power, flip, transition, units, location, per-app settings,
per-app data (canvas pixels), playlist, active app and mode. Uploaded media: `data/media/` + `index.json`.
Unknown keys are ignored and invalid stored settings fall back to defaults, so old files always load.

## Concurrency rules

- Everything runs on one event loop. CPU-heavy work (GIF baking, image import) goes to `asyncio.to_thread`.
- Only the device writer task writes to BLE. Only the engine task mutates what's on screen.
- Providers never raise into the loop; errors are stored on the provider.

## Extending

- New app → [APP_SDK.md](APP_SDK.md). New data source → subclass `Provider`, add to `providers.ALL`.
- New transport (USB, Wi-Fi panels, a second panel) → subclass `Device`; nothing above it changes.
