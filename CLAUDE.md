# DotDeck — rules for working on this codebase

DotDeck turns an **iDotMatrix 32×32 RGB LED panel** (BLE; its MAC lives in the local `dotdeck.toml`) into a live desktop
companion: an async Python engine, a React studio, and an MCP server so AI agents can see and drive the panel.

Read before changing anything:
[docs/VISION.md](docs/VISION.md) · [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) ·
[docs/DISPLAY_DESIGN.md](docs/DISPLAY_DESIGN.md) · [docs/APP_SDK.md](docs/APP_SDK.md) ·
[docs/CODING_STANDARDS.md](docs/CODING_STANDARDS.md) · [docs/INSPIRATION_AND_TECH_SPECS.md](docs/INSPIRATION_AND_TECH_SPECS.md).
Decisions and their reasons: [docs/adr/](docs/adr/).

## Commands

```powershell
uv sync --extra mcp                 # install / update Python deps (Python 3.13 via uv)
uv run dotdeck serve --sim          # engine + studio with the simulated panel  → http://127.0.0.1:8765
uv run dotdeck serve                # real panel over Bluetooth
uv run dotdeck doctor               # connect and draw a test pattern on the real panel
uv run dotdeck preview clock --settings '{"style":"analog"}' --out clock.png
uv run pytest -q                    # all tests (must pass before you say "done")
uv run ruff check src tests && uv run ruff format src tests
cd web; npm install; npm run dev    # studio with hot reload on :5173 (proxies to :8765)
cd web; npm run build               # typecheck + production build → web/dist (served by the engine)
```

## Non-negotiable rules

1. **Nothing leaves the 32×32 grid.** Draw only through `Frame` primitives; they clip. Never index `px` with
   unchecked coordinates. Leave a 1 px margin for text unless the design says otherwise.
2. **`render()` is pure, synchronous and fast** (< 2 ms, test limit 50 ms). No I/O, no `sleep`, no network, no
   file reads per frame. Data comes from providers; handle `value is None` with `_kit.loading()`/`offline()`.
3. **Never block the event loop.** No `time.sleep`, no sync HTTP, no `psutil.cpu_percent(interval>0)`.
   Blocking library calls go through `asyncio.to_thread`.
4. **The BLE link is owned by exactly one process: the engine.** Everything else (studio, MCP, scripts,
   Claude Code hooks) goes through the HTTP API. Never import `bleak` outside `dotdeck/device/`.
5. **Never disconnect the panel voluntarily** (it shows a pairing screen). The device layer reconnects itself.
6. **Latest frame wins.** Never queue frames FIFO toward the device. Use `Device.show_frame/show_gif/command`.
7. **Protocol bytes are pinned.** Any change to `device/protocol.py` needs a test in `tests/test_protocol.py`
   with bytes verified against the reference library or a hardware capture.
8. **1-bit type only.** Text uses the bitmap fonts in `gfx/font.py` (`tiny` 5 px, `small` 7 px, `big` 10 px
   digits). No TrueType / antialiasing on the panel.
9. **Design colours are for LEDs; photos get calibrated.** Use `PALETTE` tokens for UI. Only photographic
   content (uploads, album art) passes through `color.calibrate()`, once, at import.
10. **Loops are clips.** Any deterministic animation should be a `clip` app (baked GIF, native playback),
    not a high-fps stream. Stream only what changes with live data.
11. **Settings are pydantic models.** The studio renders forms from the JSON schema: use `Field(title=…)`,
    `Choice(...)`, `Color`, `ge/le` bounds. Never hand-build UI for a single app.
12. **Every app renders every option without data.** `tests/test_apps.py` enforces it automatically.
13. **Respect the link's physics** (verified on hardware, docs/HARDWARE_PROTOCOL.md): packets of one message are
    paced (`packet_gap_ms`), frames keep at most one un-acked frame in flight, GIF chunks wait for their ack, and
    baked GIFs stay under the 40 KB budget. Never "optimise" these away without re-testing on the panel.
14. **High-rate providers don't announce.** Anything polling faster than ~1 Hz overrides `announce()`.
15. **Stored settings may be stale.** Never assume `state.json` matches the current schema; the engine drops
    invalid stored keys, so schema changes are safe — but give new fields defaults.

## Where things go

| You want to…                          | Put it in                                         |
| ------------------------------------- | ------------------------------------------------- |
| show something new on the panel       | `src/dotdeck/apps/<name>.py` (+ import in `apps/__init__.py`) or `plugins/<name>.py` |
| fetch external/live data              | `src/dotdeck/providers/<name>.py`, register in `providers/__init__.py` |
| a drawing primitive / glyph           | `src/dotdeck/gfx/`                                 |
| a panel command                       | `src/dotdeck/device/protocol.py` + test           |
| an HTTP endpoint                      | `src/dotdeck/server.py` (+ docs/API.md, + MCP tool if agents need it) |
| an agent capability                   | `src/dotdeck/mcp_server.py` (thin wrapper over HTTP) |
| studio UI                             | `web/src/components/` — follow docs/STUDIO_UI.md  |
| a decision with trade-offs            | `docs/adr/NNNN-title.md`                          |

## Definition of done

- `uv run pytest -q` and `uv run ruff check src tests` pass; `cd web && npm run build` passes if the studio changed.
- New app: renders in `dotdeck preview`, looks right in the studio preview (and on the panel if available),
  follows DISPLAY_DESIGN.md (margins, type scale, palette, one hero element).
- Docs updated when behaviour, API or rules change. `legacy/` is reference only — never import from it.
