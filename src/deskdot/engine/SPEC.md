# Engine spec (`src/deskdot/engine/`, `server.py`)

Parent: [root SPEC.md](../../../SPEC.md). How: [docs/ARCHITECTURE.md](../../../docs/ARCHITECTURE.md) § The tick,
[docs/API.md](../../../docs/API.md).

## Purpose

Own *what* is on the panel: pick the slot, render it, compose overlays, route the result to the device as the
cheapest output (stream / clip / native), publish frames and state to every screen, and persist the user's setup.
The HTTP + WebSocket server in `server.py` is a stateless view over the engine.

## Requirements

- **R-ENG-1** One tick picks the slot in this order: a takeover (On Air, eye break) → the manually activated app → the
  playlist item (focus take-over, relevance skipping, fresh custom push apps after the user's items). A temporary
  activation reverts by itself. Tests: `tests/test_engine.py::test_playlist_rotates_and_skips`,
  `tests/test_engine.py::test_temporary_activation_reverts`,
  `tests/test_platform.py::test_onair_simulation_takes_over_and_releases`,
  `tests/test_platform.py::test_custom_apps_join_playlist_while_fresh`.
- **R-ENG-2** A `render()` that raises shows an error frame; the loop keeps running.
  Tests: `tests/test_engine.py::test_bad_render_shows_error_frame`.
- **R-ENG-3** Routing: a stream app sends a frame only when it changed; a clip app is baked once per `clip_key()` and
  uploaded once; a native app sends its command once per settings change.
  Tests: `tests/test_engine.py::test_stream_app_reaches_device`, `tests/test_engine.py::test_clip_app_uploads_gif_once`.
- **R-ENG-4** Notification overlays and transitions stream over any app and expire; persistent overlays (indicators,
  On-Air badge) draw on top of everything and force streaming while visible.
  Tests: `tests/test_engine.py::test_notification_overlays_and_expires`,
  `tests/test_platform.py::test_persistent_overlays_force_streaming`,
  `tests/test_platform.py::test_indicator_blink_fade_and_lifetime`.
- **R-ENG-5** Hand-off: on exit, on sleep and on demand the panel is left running the firmware clock or a baked loop of
  an app, and the engine can take it back. Tests: `tests/test_engine.py::test_handoff_on_exit`,
  `tests/test_engine.py::test_handoff_clock_then_take_back`, `tests/test_engine.py::test_handoff_app_uploads_a_loop`,
  `tests/test_api.py::test_handoff_api`.
- **R-ENG-6** State persists to `data/state.json`; a stale or invalid stored value falls back to its default and never
  blocks start-up or later updates. Tests: `tests/test_api.py::test_stale_stored_settings_do_not_block_updates`,
  `tests/test_calibration.py::test_store_with_stale_calibration_still_boots`.
- **R-ENG-7** Settings updates are validated against the app's pydantic model; invalid input is refused with 4xx.
  Tests: `tests/test_api.py::test_settings_validation`, `tests/test_api.py::test_playlist_put_validates`.
- **R-ENG-8** `/ws` pushes coalesced state and raw frames; each client holds only the newest frame.
  Tests: `tests/test_api.py::test_websocket_streams_state_and_frames`.
- **R-ENG-9** Secrets (integration tokens, keys) are masked in every API response and never logged.
  Tests: `tests/test_api.py::test_secrets_never_leave_the_engine`,
  `tests/test_platform.py::test_integrations_mask_and_keep_secrets`,
  `tests/test_platform.py::test_ha_errors_never_leak_the_token`.
- **R-ENG-10** `LanGate`: from the LAN only `/p/`, `/ws/p/`, `/tv/`, `/ws/tv/` are reachable (never a path with `..`)
  unless the user sets `lan_studio = true`. Tests: `tests/test_multiplayer.py::test_lan_gate`,
  `tests/test_tv.py::test_lan_gate_tv`.
- **R-ENG-11** AWTRIX-compatible custom push apps join the rotation while fresh, expire when stale and survive a
  restart. Tests: `tests/test_platform.py::test_custom_app_endpoints`, `tests/test_platform.py::test_custom_app_expiry`,
  `tests/test_platform.py::test_custom_apps_survive_restart`.
- **R-ENG-12** The page theme is an engine setting shared by every screen (`POST /api/theme`) and recolours themed
  apps on the panel. Tests: `tests/test_page_themes.py::test_theme_api`,
  `tests/test_page_themes.py::test_engine_switches_the_panel_theme`.

## Invariants

- **I-ENG-1** One asyncio task runs the tick; only it mutates what is on screen. CPU-heavy work (GIF bakes, image
  import) goes through `asyncio.to_thread`; nothing calls `time.sleep` or sync HTTP on the loop. Tests:
  `tests/test_event_loop.py::test_no_blocking_calls_on_the_event_loop` (static; its allowlist documents the calls
  that run in threads or loop-less processes), `tests/test_event_loop.py::test_requests_library_is_never_imported`,
  `tests/test_event_loop.py::test_engine_never_blocks_the_loop` (the engine under asyncio debug mode, no step
  over 0.1 s).
- **I-ENG-2** The engine writes to the panel only through `Device.show_frame / show_gif / command` (never a FIFO of
  frames).
- **I-ENG-3** Every endpoint the studio uses exists in the HTTP API so scripts and MCP can do the same; a new endpoint
  gets an API test and a line in docs/API.md.
- **I-ENG-4** Providers never raise into the loop; their errors are stored on the provider.

## Interfaces

`GET /api/health|meta|state|frame|frame.png`, `/api/apps/*`, `/api/playlist*`, `/api/presets*`, `/api/autopilot`,
`/api/notify`, `/api/text`, `/api/agent/{state}`, `/api/pixels`, `/api/indicators*`, `/api/custom*`,
`/api/integrations*`, `/api/settings`, `/api/theme`, `/api/display`, `/api/calibration*`, `/api/handoff*`,
`/api/media*`, `/api/nowplaying/*`, `/api/play/lobby*`, `/p/{code}`, `WS /ws`, `WS /ws/p/{code}`. Full reference:
[docs/API.md](../../../docs/API.md). Device endpoints belong to the [device spec](../device/SPEC.md), TV endpoints to
the [TV spec](../tv/SPEC.md), updates to the [packaging spec](../../../packaging/SPEC.md).

## Open questions

- The < 200 ms click-to-panel budget (R-ROOT-2) is measured by hand on hardware only.
- I-ENG-1's runtime check covers a handful of apps (stream, clip, casino, game, a network provider); a blocking
  call in a rarely shown app is caught only by the static scan.

Last verified: 2026-10-29
