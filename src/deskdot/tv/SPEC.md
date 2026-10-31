# TV view spec (`src/deskdot/tv/`, `tv.html`, `tvlink.py`)

Parent: [root SPEC.md](../../../SPEC.md). How: [docs/TV_VIEW.md](../../../docs/TV_VIEW.md) (pairing, the page, the
socket, scenes, performance, the casino on the big screen, the web app).

## Purpose

Any screen with a browser (smart TV, Fire TV / Android TV, a cast tab, a tablet, a projector) shows a full-screen,
**read-only** view of what DeskDot is playing: the panel as a big LED matrix and, for games and casino tables, a
bespoke scene in sync with the panel.

## Requirements

- **R-TV-1** Pairing: `POST /api/tv` opens (or returns) one TV link with a 4-character code that never equals the
  lobby code; `{"renew": true}` replaces it and tells old TVs `closed`; `DELETE` closes it. Tests:
  `tests/test_tv.py::test_tv_link_routes_and_page`.
- **R-TV-2** The socket sends `hello` on connect and app change, `state` at ~5 Hz on change (2 s heartbeat) and binary
  3072-byte frames at ≤ 12 fps, latest wins. Tests: `tests/test_tv.py::test_tv_socket_hello_state_frames`.
- **R-TV-3** A TV receives exactly the app's public `status()` — never `private_status()`; the TV-only `tv_extra()`
  reveal exists only from the lock until the next round and never reaches phones; turn games and housie never reveal.
  Tests: `tests/test_tv.py::test_tv_never_gets_private_data`,
  `tests/test_tv_reveal.py::test_reveal_only_after_the_lock_and_never_for_phones`,
  `tests/test_tv_reveal.py::test_turn_games_and_housie_never_reveal`,
  `tests/test_tv_reveal.py::test_tv_state_carries_tv_but_the_status_stays_public`.
- **R-TV-4** The only TV → engine writes are ping and, at a casino table, one cosmetic house setting (dolly or chip
  set) with a known value, rate-limited per TV. Tests: `tests/test_tv.py::test_tv_house_display_settings_only`.
- **R-TV-5** The studio's display choice (look Pixel/LED/Glow, quality Auto/HQ/Lite, or "let each TV choose") reaches
  every TV and is validated. Tests: `tests/test_tv.py::test_tv_display_settings_validate_and_reach_every_tv`,
  `tests/js/tv_core.test.mjs`.
- **R-TV-6** Casino scenes evaluate every animation as a pure function of the shared clock, ported 1:1 from the panel
  apps, so the TV's ball lands in the same frame as the panel's. Tests:
  `tests/test_tv_reveal.py::test_roulette_reports_the_panels_wheel_angle`, `tests/js/tv_casino.test.mjs`.
- **R-TV-7** The web app serves the same TV page through the join page (`/tv/<code>` → `/app/join/`).
  Tests: `tests/test_tv.py::test_tv_page_built_for_the_join_page`.
- **R-TV-8** The options menu works with mouse, touch, keyboard and a TV remote. Tests: `tests/js/tv_menu.test.mjs`.

## Invariants (the perf budget — TV_VIEW.md § 6)

- **I-TV-1** Read-only: nothing on the panel, credits, limits, rules or other apps is controllable from a TV.
- **I-TV-2** One animation loop; motion is `transform` / `opacity` on pre-rendered canvases; unchanged style writes
  are skipped.
- **I-TV-3** No per-frame blur: no `filter: blur()` / `backdrop-filter`, no animated `box-shadow`; glows are cached
  sprites; Liquid Glass on the TV is static faux glass.
- **I-TV-4** Big canvases (≥ 200 k device px) are `OffscreenCanvas` surfaces redrawn only on change (or at the scene's
  slow rate); idle sprites are `display: none`.
- **I-TV-5** Both quality tiers keep picture quality; a perf change reports p50 / p95 frame intervals from the headless
  ×6-throttled 960×540 benchmark.
- **I-TV-6** `tv.html` has no inline script (the web app's CSP forbids it).

## Interfaces

`GET|POST|DELETE /api/tv`, `POST /api/tv/settings`, `GET /tv/{code}`, `GET /tv/static/{name}` (TV scripts and font
only), `WS /ws/tv/{code}` (`hello`, `state`, frames, `closed`; from the TV: `ping`, `house`).

## Open questions

- The perf budget (I-TV-2…5) is verified by the manual benchmark, not in CI. `tests/js/*` run in CI
  (job `js` in `.github/workflows/ci.yml`) except `tests/js/tv_menu.test.mjs`, which skips without playwright-core.

Last verified: 2026-10-29
