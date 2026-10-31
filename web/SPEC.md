# Studio spec (`web/`)

Parent: [root SPEC.md](../SPEC.md). How: [docs/STUDIO_UI.md](../docs/STUDIO_UI.md) (the whole UI system),
ADR [0007](../docs/adr/0007-react-vite-tailwind-studio.md). Browser version: [web/webapp/SPEC.md](webapp/SPEC.md).

## Purpose

The studio is the controller, and its centrepiece is the panel itself: a live, LED-accurate preview plus a schema-driven
inspector, library, playlist, play mode, casino mode and settings. It renders engine state; it never owns it.

## Requirements

- **R-STU-1** Themes: one switch `light` · `dark` · `system` (default), applied before first paint, kept live across
  tabs and OS changes; every DeskDot page (casino.html, controller.html, join pages, the TV) reads the same key.
  Tests: none yet (gap) — `tests/js/tv_core.test.mjs` covers only the TV's theme.
- **R-STU-2** Page themes: 21 curated themes, each with light and dark variants, stored on the engine
  (`POST /api/theme`) so every device shows the same one; the studio's seed table mirrors `gfx/themes.py` exactly;
  no flash on load. Tests: `tests/test_page_themes.py::test_page_themes_are_the_casino_tables`,
  `tests/test_page_themes.py::test_generated_studio_themes_are_current`, `tests/test_page_themes.py::test_screen_tokens_read_like_the_casino`.
- **R-STU-3** Paper panel: in light mode the preview maps every LED colour to ink on porcelain (`paperColor`, ≥ 4.5:1
  against the unlit LED), changing only the studio's drawing — never the engine's frames, `/api/frame.png` or GIFs.
  Tests: none yet (gap).
- **R-STU-4** Liquid Glass is the navigation and control layer only (never content, never glass on glass);
  `backdrop-filter` only on floating chrome, never on a scrolling area; frosted fallback where blur is missing or slow
  (the Android app). Tests: none yet (gap).
- **R-STU-5** Connection: the status pill and the Connection sheet describe where the panel is connected with one
  `summarize()` function, show the engine's `reason` / `hint`, and offer one primary action; *Release the panel…*
  explains the pairing screen first. Tests: `tests/test_device_connection.py::test_reconnect_endpoint` (engine side only).
- **R-STU-6** Updates UI (Settings → Device → Updates, the top-bar pill) shows the WHATS_NEW notes of a newer release,
  installs only through the engine's verified path, and tells source installs to `git pull`.
  Tests: `tests/test_updates.py::test_updates_api` (engine side only).
- **R-STU-7** Casino mode follows the table theme everywhere and the studio's theme list mirrors the engine.
  Tests: `tests/test_casino_themes.py::test_studio_casino_follows_the_theme_everywhere`,
  `tests/test_casino_themes.py::test_studio_theme_list_mirrors_the_engine`.
- **R-STU-8** Every app's icon exists in the studio icon set. Tests:
  `tests/test_apps.py::test_app_icons_exist_in_the_studio_icon_set`.
- **R-STU-9** The built studio is served by the engine with revalidating HTML and cacheable assets.
  Tests: `tests/test_api.py::test_studio_page_revalidates_and_assets_cache`.
- **R-STU-10** `npm run build` (typecheck + production build) passes. Tests: CI job "Studio — typecheck & build"
  (`.github/workflows/ci.yml`); no unit test file.

## Invariants

- **I-STU-1** No hand-built UI for one app: forms come from the settings JSON schema (`SchemaForm`).
- **I-STU-2** Components never hardcode colour: tokens, `--m-*` materials, `light:` / `dark:` variants. Light mode
  has no dark chrome.
- **I-STU-3** Frames never go through React state; `LedPanel` draws only new frames, at most once per vsync, nothing
  while hidden or off screen.
- **I-STU-4** The phone app holds the screen's full refresh rate: nothing animates layout or paint per frame.
- **I-STU-5** Zustand selectors return stable references.
- **I-STU-6** Accessibility: visible focus ring, labels on icon-only keys, `role="switch"` toggles,
  `prefers-reduced-motion` honoured, colour never the only signal.
- **I-STU-7** Apple's design kits are never downloaded or embedded; Liquid Glass is our own CSS/SVG.

## Interfaces

Consumes the HTTP API and `WS /ws` ([engine spec](../src/deskdot/engine/SPEC.md)); `localStorage` keys
`deskdot.theme`, `deskdot.pageTheme`, `deskdot.pageThemeCss`; `window.DeskDotAndroid` bridge
([android spec](../android/SPEC.md)); deep links (`#connection`, docs/LAUNCHERS.md).

## Open questions

- The studio has no unit or component test runner; R-STU-1, 3, 4 and the UI halves of 5 and 6 are verified by hand.

Last verified: 2026-10-29
