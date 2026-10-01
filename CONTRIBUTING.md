# Contributing to DeskDot

Thanks for helping! New apps, games, data sources, fixes and panel photos are all welcome.

## Setup

```bash
uv sync --extra mcp
(cd web && npm ci && npm run build)
uv run deskdot serve --sim          # no panel needed
uv run pytest -q                    # must pass
uv run ruff check src tests && uv run ruff format src tests
```

Studio with hot reload: `cd web && npm run dev` (port 5173, proxies to the engine on 8765).

## The rules (read before you write code)

[CLAUDE.md](CLAUDE.md) has the short, non-negotiable list. It applies to people and AI agents alike. The big ones:

1. **Nothing leaves the 32×32 grid**, so draw only through `Frame` primitives.
2. **`render()` is pure and fast** (< 2 ms). No I/O, no sleeping, no network; data comes from providers.
3. **Never block the event loop**, and **never import `bleak` outside `deskdot/device/`**.
4. **Deterministic animation is a baked clip**, not a stream. Respect the link's physics
   ([docs/HARDWARE_PROTOCOL.md](docs/HARDWARE_PROTOCOL.md)).
5. **1-bit bitmap fonts only** on the panel; **PALETTE** colours for UI; photos are calibrated once.
6. **Settings are pydantic models.** The studio renders the form; don't hand-build UI for one app.
7. **Every app renders every option without data**, which `tests/test_apps.py` checks for you.

Design guide: [docs/DISPLAY_DESIGN.md](docs/DISPLAY_DESIGN.md). App SDK: [docs/APP_SDK.md](docs/APP_SDK.md).

## Adding an app

One file in `src/deskdot/apps/` (and an import in `apps/__init__.py`), or a drop-in file in `plugins/`. Then:

- `uv run deskdot preview <id> --out x.png` renders it without hardware;
- add tests for its behaviour (loops seamless, readable on the panel, fits the GIF budget if it's a clip).

## Pull requests

- Keep them focused; describe what changed and how you checked it (on a real panel if you have one).
- `pytest`, `ruff` and `npm run build` (if the studio changed) must pass; CI runs them.
- Docs change with behaviour: API, rules, or user-visible features.
- Original work only: no copied sprites, fonts, characters or brand assets.
- Never commit secrets, `deskdot.toml`, `.env*` or `data/`.

## Photos of your panel

Real photos help more than anything else in the README. Drop them in `docs/media/photos/` (see the README there)
and open a PR.
