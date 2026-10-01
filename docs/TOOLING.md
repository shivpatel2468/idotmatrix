# Tooling — what we use and how

## Stack at a glance

| Layer | Tool | Why |
| --- | --- | --- |
| Python runtime & deps | **uv** + Python 3.13 | fast, reproducible (`uv.lock`), manages the interpreter |
| BLE | **bleak** | the best cross-platform BLE library; WinRT backend on Windows |
| Web framework | **FastAPI** + **uvicorn[standard]** | async, pydantic-native, WebSockets, OpenAPI docs at `/docs` |
| Validation / schemas | **pydantic v2** | settings models → JSON Schema → studio forms |
| Imaging | **numpy** (frame buffers) + **Pillow** (decode/encode) | vectorised effects; GIF/PNG I/O |
| HTTP client | **httpx** (async) | one shared client for all providers |
| Telemetry | **psutil** | CPU/RAM/disk/net/battery |
| Media (Windows) | **winrt** `Windows.Media.Control` | now-playing from any app, no API keys |
| Lyrics | **syncedlyrics** | LRC from lrclib/Musixmatch/NetEase |
| Agent bridge | **mcp** (Python SDK 2.x `MCPServer`; 1.x `FastMCP` supported) | Model Context Protocol server |
| Lint/format | **ruff** | one fast tool |
| Tests | **pytest** + **pytest-asyncio** | async engine tests on the simulator |
| Studio | **React 19**, **TypeScript**, **Vite 8**, **Tailwind CSS 4**, **zustand**, **lucide-react** | fast builds, token-based styling, tiny state layer |
| Fonts | **@fontsource** Bricolage Grotesque + Martian Mono | bundled, offline |
| Browser QA | Playwright MCP / Chrome DevTools MCP | screenshots and interaction checks of the studio |

## Daily commands

```powershell
uv sync --extra mcp            # after pulling
uv run deskdot serve --sim     # develop without the panel
uv run deskdot serve           # with the panel
cd web; npm run dev            # studio hot reload at http://127.0.0.1:5173 (engine must be running)
uv run pytest -q               # tests
uv run ruff check src tests; uv run ruff format src tests
cd web; npm run build          # studio production build served by the engine at :8765
```

## Hardware tools

```powershell
uv run deskdot scan            # list IDM-* panels and RSSI
uv run deskdot doctor          # connect, draw test pattern, print link stats
```

Close the vendor phone app first — the panel accepts one connection.

## Designing screens

- `uv run deskdot preview <app> --settings '{...}' --t 1.5 --scale 12 --out x.png` — render without hardware.
- The studio preview is LED-accurate (bloom, off-LEDs); design there, confirm on the panel at 40 % brightness.
- `docs/assets/apps.png` is the gallery of every app; regenerate it when you change visuals.

## AI tooling

- **CLAUDE.md** is the rulebook for AI assistants working on this repo.
- **MCP**: `.mcp.json` registers the `deskdot` server for Claude Code in this folder (engine must be running).
  See [MCP.md](MCP.md).
- **Claude Code hooks**: `integrations/claude-code/hooks.json` drives the Claude mascot from your sessions.

## Configuration

`deskdot.toml` (copy `deskdot.example.toml`) or `DESKDOT_*` env vars: `host`, `port`, `device` (`ble`/`sim`),
`address`, `max_fps`, `data_dir`, `plugins_dir`, `log_level`. CLI flags override both.

## Running at login (Windows)

Create a shortcut in `shell:startup` to:

```
powershell -WindowStyle Hidden -Command "cd C:\path\to\idotmatrix; uv run deskdot serve"
```

(or register a Task Scheduler task "At log on" with the same command).
