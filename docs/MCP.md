# MCP server — let agents see and drive the panel

`deskdot-mcp` is a [Model Context Protocol](https://modelcontextprotocol.io) server. It lets Claude (Claude Code,
Claude Desktop, or any MCP client) talk to the live panel. It is a thin client over the engine's HTTP API,
because only the engine may own the Bluetooth link.

```
Claude ──MCP (stdio)──▶ deskdot-mcp ──HTTP──▶ DeskDot engine ──BLE──▶ panel
```

## Setup

1. Start the engine: `uv run deskdot serve` (or `--sim`).
2. **Claude Code in this folder:** `.mcp.json` already registers the server. Approve it when prompted, or run `/mcp`.
3. **Anywhere else:**
   ```powershell
   claude mcp add deskdot -- uv run --project C:\path\to\idotmatrix deskdot-mcp
   ```
   Claude Desktop (`claude_desktop_config.json`):
   ```json
   { "mcpServers": { "deskdot": { "command": "uv", "args": ["run", "--project", "C:\\path\\to\\idotmatrix", "deskdot-mcp"] } } }
   ```
4. Engine on another machine: set `DESKDOT_URL=http://host:8765` in the server's `env` (and run the engine
   with `host = "0.0.0.0"`).

## Tools

| Tool | What it does |
| --- | --- |
| `panel_snapshot(scale=12)` | **returns an image of the panel right now** — the agent can see its work |
| `panel_status()` | connection, current app + status, playlist, overlay, On Air, indicators, custom apps, brightness |
| `list_apps()` | every app with its settings (types, options, bounds, defaults) and actions |
| `show_app(app, settings?, revert_after_seconds?)` | switch app, optionally temporarily |
| `update_app_settings(app, settings)` | change saved settings |
| `app_action(app, action, payload?)` | timer start/reset, media next/prev, canvas clear, … |
| `show_text(text, color, effect, revert_after_seconds?)` | message, auto-fit or smooth scroll |
| `draw_pixel_art(rows, palette, revert_after_seconds?)` | ≤ 32×32 character art → panel; returns a snapshot |
| `set_pixels(pixels, clear_first)` | paint individual pixels on the canvas |
| `notify(message, title, color, icon, duration, style)` | overlay banner / full-screen card |
| `agent_state(state, hold_seconds?)` | Claude mascot: idle, thinking, working, waiting, done, error, sleeping |
| `set_display(brightness, power, flip, transition)` | panel-level settings |
| `playlist(op)` / `set_playlist(items, enabled)` | inspect, control or replace the rotation |
| `presets(action, preset?, shuffle?, name?)` | list / play / save / delete one-tap playlists ("play every game", "all pets", "chill") |
| `show_image(path)` | upload a local image/GIF and show it |
| `compose(layers, background)` | build a Text Studio layout (text + live values) and get a snapshot back |
| `autopilot(enabled?, rules?)` | read or set "when this app is in front, show that" rules |
| `set_indicator(slot, color, blink_ms, fade_ms, lifetime_s, size, clear)` | AWTRIX-style status square on the right edge (1 top, 2 middle, 3 bottom), over every app |
| `push_custom_app(name, text, icon?, color?, progress, duration, lifetime, rainbow, rows?, palette?, remove)` | push / replace / remove a named "icon + value" screen that joins the playlist rotation |

Resource: `deskdot://design-guide` — the condensed 32×32 design rules, so agents compose readable art.

## Example prompts

- "Draw a pixel-art rocket on my panel, then check the snapshot and fix anything that looks off."
- "Make a playlist: clock 20 s, weather 10 s, BTC and ETH tickers, and now-playing that takes over when music plays."
- "When you finish this refactor, set the mascot to done and send a green notification with the test count."
- "Show 'LUNCH' in rainbow for 5 minutes, then go back to what was showing."
- "Light indicator 1 green while the test suite passes and red when it fails; push a custom app 'ci' with the count."

## Mascot from Claude Code hooks (no MCP needed)

Merge `integrations/claude-code/hooks.json` into `.claude/settings.json`: prompts → *thinking*, edits/commands →
*working*, permission prompts → *waiting*, end of turn → *done* for 8 s, then the previous screen returns.

## Adding a tool

Tools live in `src/deskdot/mcp_server.py`. Rules: call the HTTP API via `_call()` (never import engine
internals), write the docstring for an agent (what, units, ranges, an example), return small JSON or an
`Image`, and prefer returning a `panel_snapshot()` after visual changes so the agent can verify itself.
