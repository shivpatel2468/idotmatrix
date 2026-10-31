# Web app spec (`web/webapp/`, `web_main.py`, `device/web.py`)

Parent: [root SPEC.md](../../SPEC.md). How: [docs/WEB_APP.md](../../docs/WEB_APP.md), ADR
[0012](../../docs/adr/0012-web-app-pyodide.md). Hosting: [netlify spec](../../netlify/SPEC.md).

## Purpose

DeskDot in a browser tab at idotmatrix.com/app/: the real `src/deskdot` engine runs in Pyodide in a Web Worker, the
unchanged studio talks to it through shims, and the page drives the panel over Web Bluetooth. Nothing to install.

## Requirements

- **R-WEB-1** Same engine and same panel physics: the worker runs the real package; `device/web.py` implements only
  the three transport hooks; pacing, acks, GIF chunk acks and latest-frame-wins stay in `device/base.py`.
  Tests: `tests/test_web_device.py::test_frames_are_split_into_paced_packets_one_at_a_time`,
  `tests/test_web_device.py::test_gif_chunks_wait_for_their_ack`, `tests/test_web_device.py::test_latest_frame_wins`.
- **R-WEB-2** Connecting waits for the user's gesture (no retry storm); a remembered panel reconnects silently after a
  drop; a new pick cuts the wait short. Tests: `tests/test_web_device.py::test_waits_for_the_user_gesture_without_retrying`,
  `tests/test_web_device.py::test_link_loss_reconnects_and_replays_the_screen`,
  `tests/test_web_device.py::test_unreachable_panel_retries_and_a_new_pick_cuts_the_wait_short`.
- **R-WEB-3** One engine per browser: a Web Lock lets one tab run it; *Use it here* moves the panel without a reload
  and the old tab finishes its write in flight first (never a half-sent GIF).
  Tests: `tests/test_device_connection.py::test_pause_writes_finishes_the_item_in_flight_then_sends_nothing`
  (engine side; the tab hand-over itself is verified by hand).
- **R-WEB-4** `GET /api/meta` reports `platform: "web"` with only the browser's features; apps that can't run in a tab
  say why. Tests: `tests/test_web_device.py::test_web_platform_has_only_the_browser_media_features`,
  `tests/test_web_apps.py::test_apps_that_cant_run_in_a_tab_say_why`, `tests/test_web_apps.py::test_blocked_messages_say_why`.
- **R-WEB-5** Live data: every provider host is reachable by CORS or through `/app/proxy`, a strict GET-only host
  allowlist (no cookies, 3 MB cap, redirects only within the allowlist). Tests:
  `tests/test_web_apps.py::test_every_provider_host_works_from_the_browser`,
  `tests/test_web_apps.py::test_the_proxy_is_a_strict_get_only_allowlist`, `tests/js/cors_proxy.test.mjs`.
- **R-WEB-6** Online play: phones and TVs join a tab over WebRTC through `/app/signal`; lobby URLs point at the website;
  large messages are split and reassembled. Tests: `tests/test_web_play.py::test_lobby_url_points_at_the_website_with_public_url`,
  `tests/test_web_play.py::test_join_sources_exist_and_signal_route`, `tests/js/signal_core.test.mjs`,
  `tests/js/wire.test.mjs`.
- **R-WEB-7** Camera, screen and sound work through the browser's own permission prompts.
  Tests: `tests/test_web_media.py`.
- **R-WEB-8** If DeskDot on this computer holds the panel, the page says so and links to its Connection sheet
  (`http://127.0.0.1:8765/api/health`, never on page load). Tests:
  `tests/test_device_connection.py::test_health_probe_for_the_web_app`.

## Invariants

- **I-WEB-1** Protocol bytes and link physics are identical to the desktop; never a browser-only shortcut.
- **I-WEB-2** No inline scripts in any page served under `/app/`, `/p/`, `/tv/` (their CSP forbids them).
- **I-WEB-3** The desktop build (`web/dist`) is untouched by the web build (only `DESKDOT_WEBAPP=1` builds it).
- **I-WEB-4** `site/app/` is committed fully built (`scripts/build_webapp.py`); Pyodide is pinned.
- **I-WEB-5** The proxy never becomes an open proxy: new hosts are added to its allowlist one by one.

## Interfaces

`web_main.http()` / `ws_open()` (ASGI from the page), worker ↔ page messages (`ble-*`, `onWriteSize`, `onRetry`),
`BroadcastChannel("deskdot-web")`, Web Lock `deskdot-web-engine`, `/app/proxy`, `/app/signal`, `/p/*`, `/tv/*`.

## Open questions

- Two-tab hand-over and Web Bluetooth flows are verified with `web/webapp/dev/mock-bluetooth.js` by hand, not in CI.

Last verified: 2026-10-29
