# DeskDot — root spec

Living spec: the durable statement of what DeskDot must do and must never do. Code says *how*; this says *why and
what*. How to use and change these files: [docs/SPECS.md](docs/SPECS.md).

## Purpose

DeskDot makes a 32×32 iDotMatrix RGB LED panel the most glanceable screen on a desk: alive with what the user cares
about, programmable by people and by AI agents, beautiful at 1,024 pixels. Vision and personas:
[docs/VISION.md](docs/VISION.md). Architecture: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

**Users.** The builder at a desk (ambient status), the music listener (lyrics, now playing), the AI-agent user
(agent state on the panel, MCP), the pixel artist / tinkerer (canvas, SDK, plugins), and a room of friends (games and
the play-money casino from their phones, the TV view).

**Platforms.** One Python engine, four hosts: the desktop (Windows verified, macOS, Linux, Raspberry Pi), the Android
app (Chaquopy), the browser tab (Pyodide + Web Bluetooth at idotmatrix.com/app/), and the simulator. Screens that read
the engine: the studio (React), phones (`/p/<code>`), TVs (`/tv/<code>`), the launcher, MCP agents and scripts.

## Requirements

- **R-ROOT-1** Every app renders every one of its options at 32×32 without data, fast.
  Tests: `tests/test_apps.py::test_render_all_variants`.
- **R-ROOT-2** A click in the studio reaches the panel in well under 200 ms; the panel is never more than one frame
  behind the engine. Tests: `tests/test_engine.py::test_latest_frame_wins`.
- **R-ROOT-3** Anything a person can do in the studio, an agent can do over the HTTP API / MCP, and it can see the
  result (`panel_snapshot`, `/api/frame.png`). Tests: `tests/test_api.py::test_meta_state_and_frame`.
- **R-ROOT-4** The same engine runs unchanged on desktop, Android and the browser; only the BLE transport and host
  features differ, and unsupported features say so instead of failing.
  Tests: `tests/test_compat.py::test_apps_render_unsupported_state`, `tests/test_web_device.py`,
  `tests/test_android_device.py`.
- **R-ROOT-5** Local-first: built-in apps need no accounts or API keys; nothing about the user leaves the machine
  except the data-feed requests apps make. Tests: `tests/test_api.py::test_secrets_never_leave_the_engine`.

## Invariants

- **I-ROOT-1** The BLE link is owned by exactly one process (the engine); everything else goes through the HTTP API.
  `bleak` is imported only inside `src/deskdot/device/`. (Detail: [device spec](src/deskdot/device/SPEC.md).)
- **I-ROOT-2** Nothing is drawn outside the 32×32 grid; panel text is 1-bit bitmap type only.
- **I-ROOT-3** `render()` is pure, synchronous and fast; the event loop is never blocked.
- **I-ROOT-4** Casino credits are play money: never bought, sold, cashed out or tied to real value.
- **I-ROOT-5** Secrets (tokens, keys, `deskdot.toml`, `data/`, the Android release keystore) never enter git or an API
  response.
- **I-ROOT-6** `main` changes only through pull requests; releases are tags on `main` (see CLAUDE.md § How we work).

The full list of non-negotiable rules is [CLAUDE.md](CLAUDE.md); each child spec restates the ones it owns.

## Map of child specs

| Area | Spec | Owns |
| --- | --- | --- |
| Engine | [src/deskdot/engine/SPEC.md](src/deskdot/engine/SPEC.md) | tick, routing, overlays, playlist, hand-off, state, HTTP/WS server, LanGate |
| Device | [src/deskdot/device/SPEC.md](src/deskdot/device/SPEC.md) | BLE link, protocol bytes, scheduler, reconnects, release |
| Apps | [src/deskdot/apps/SPEC.md](src/deskdot/apps/SPEC.md) | the app contract, design rules, page themes on the panel |
| Providers | [src/deskdot/providers/SPEC.md](src/deskdot/providers/SPEC.md) | live data, ref-counting, endpoints, API health |
| Casino | [src/deskdot/casino/SPEC.md](src/deskdot/casino/SPEC.md) | fairness, credits, phases, shared clock, themes, chips, dolly |
| TV view | [src/deskdot/tv/SPEC.md](src/deskdot/tv/SPEC.md) | `/tv/<code>`, the TV socket, scenes, perf budget |
| Studio | [web/SPEC.md](web/SPEC.md) | themes, page themes, paper panel, Liquid Glass, connection, updates UI |
| Web app | [web/webapp/SPEC.md](web/webapp/SPEC.md) | the engine in a browser tab, Web Bluetooth, two tabs, online play |
| Android | [android/SPEC.md](android/SPEC.md) | the phone host app, BLE bridge, system bars, self-update |
| Packaging & updates | [packaging/SPEC.md](packaging/SPEC.md) | installers, release workflow, in-app updates, signing |
| Website & Netlify | [netlify/SPEC.md](netlify/SPEC.md) | idotmatrix.com, functions, CSP, legal copy |

`tests/test_specs.py` checks this map, every test path the specs cite, and that requirement ids are unique.

## Interfaces

The public surface is the HTTP + WebSocket API ([docs/API.md](docs/API.md)), owned by the engine spec; the MCP tools
([docs/MCP.md](docs/MCP.md)) are a thin client of it.

## Open questions

- No automated check yet that the MCP server never imports the device layer (I-ROOT-1 is enforced by review).
- `tests/js/*.test.mjs` run with `node --test` locally but not in CI.

Last verified: 2026-10-29
