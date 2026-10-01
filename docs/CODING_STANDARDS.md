# Coding standards

## Python (engine, providers, apps, MCP)

- **Version:** Python 3.13 (supported 3.12–3.13), managed by `uv`. Dependencies only via `pyproject.toml`.
- **Style:** `ruff format` (line length 110) and `ruff check` (rules E, F, W, I, B, UP, ASYNC, SIM, RUF) must be clean.
- **Typing:** annotate every public function; `from __future__ import annotations` at the top of modules.
  Prefer `X | None`, `list[int]`, pydantic models for anything crossing a boundary (API, state, settings).
- **Async:** one event loop. No blocking calls in coroutines (see CLAUDE.md rule 3). Use `asyncio.to_thread` for
  CPU-heavy or blocking library work. Long-lived tasks are named (`create_task(..., name=)`) and cancelled on stop.
- **Errors:** providers and app renders never crash the loop — catch broadly there, log once, expose the error in
  state. Everywhere else, let exceptions propagate to the API layer, which maps `KeyError`→404,
  `ValidationError`→422, `ValueError`→400.
- **Logging:** `logging.getLogger("dotdeck.<area>")`. `info` for lifecycle, `warning` for recoverable faults,
  `exception` for bugs. No `print` outside the CLI.
- **Naming:** modules `snake_case`, classes `PascalCase`, app ids short lowercase (`nowplaying`).
- **Comments:** explain *why* (hardware quirks, trade-offs), not what. Every module starts with a docstring
  stating its role and contract.
- **Numbers on the panel:** integers for coordinates; `round()` not `int()` when converting fractions to pixels.
- **No magic hex in apps:** use `PALETTE` tokens or a named module constant.

## TypeScript / React (studio)

- **Stack:** React 19, TypeScript strict, Vite, Tailwind v4 (`@theme` tokens), zustand, lucide-react, clsx.
- **State:** server state arrives over the WebSocket into `useStore`; do not duplicate it in component state
  except for local edits in flight. Selectors return stable references.
- **Frames:** never in React state (see STUDIO_UI.md). Canvas drawing only.
- **API calls:** only through `lib/api.ts` (errors become toasts automatically).
- **Styling:** tokens and the component classes from `index.css`; Tailwind utilities for layout. No new colours
  outside `@theme`; no inline hex except for user-chosen colours.
- **Components:** one file per area, named exports, props typed inline. Keep components < ~250 lines; split
  sub-components in the same file before creating new files.
- `npm run build` (runs `tsc -b`) must pass.

## Testing

| Suite | Covers |
| --- | --- |
| `tests/test_protocol.py` | every packet byte-for-byte |
| `tests/test_gfx.py` | clipping, fonts (tabular digits, distinct glyphs), wrap/fit, calibration, GIF round-trip |
| `tests/test_apps.py` | **every app × every Choice option** renders fast without data; clips bake; schemas valid |
| `tests/test_engine.py` | stream/clip routing, latest-frame-wins, command priority, playlist, overlays, reverts, error frames |
| `tests/test_api.py` | endpoints, validation, media upload, playlist validation, WebSocket frames+state |

- Tests use the simulator (`SimDevice`) — never real hardware, never the network. Providers get fake values.
- Bug fix = failing test first. New protocol command = pinned bytes. New endpoint = API test.
- Hardware verification is manual: `uv run dotdeck doctor`, then the studio. Record findings in HARDWARE_PROTOCOL.md.

## Git & reviews

- Small, focused commits: `area: imperative summary` (e.g. `apps/weather: add snow animation`).
- A change is reviewable when: tests + lint pass, the studio builds, screenshots/`preview` PNGs are attached for
  visual changes, docs updated.
- Record decisions with real trade-offs as ADRs (`docs/adr/`), numbered, never edited after acceptance —
  supersede instead.
