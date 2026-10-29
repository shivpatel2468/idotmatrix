# Apps spec (`src/deskdot/apps/`, `plugins/`)

Parent: [root SPEC.md](../../../SPEC.md). How: [docs/APP_SDK.md](../../../docs/APP_SDK.md) (the SDK),
[docs/DISPLAY_DESIGN.md](../../../docs/DISPLAY_DESIGN.md) (designing for 32×32),
ADRs [0005](../../../docs/adr/0005-clips-baked-to-native-gif.md), [0006](../../../docs/adr/0006-schema-driven-apps.md).

## Purpose

Each app is one screen for the panel: a plugin class with pydantic `Settings`, the providers it `uses`, an output
`kind()` and a pure `render(frame, t)`. The studio and MCP discover apps from their schema; a new capability is one
Python file and zero frontend work.

## The app contract

| Part | Must |
| --- | --- |
| `id`, `name`, `category`, `icon` | unique id; a category from the engine's `Category`; an icon that exists in the studio set |
| `Settings` | a pydantic model; `Field(title=…)`, `Choice(...)`, `Color`, `ge/le` bounds; every field has a default |
| `uses` | the providers it reads; data comes only from them |
| `kind()` | `stream` (live data), `clip` (deterministic loop, baked GIF) or `native` (a firmware command) |
| `render(f, t)` | pure, synchronous, < 2 ms typical (test limit 50 ms); draws only through `Frame` primitives |
| states | `value is None` → `_kit.loading()` / `offline()`; unsupported host feature → the unsupported state |

## Requirements

- **R-APP-1** Every app × every `Choice` option renders without provider data, within 50 ms.
  Tests: `tests/test_apps.py::test_render_all_variants`.
- **R-APP-2** Settings schemas are valid JSON schema; unknown `Choice` values are refused.
  Tests: `tests/test_apps.py::test_settings_schemas_are_json`, `tests/test_apps.py::test_choice_rejects_unknown_option`.
- **R-APP-3** App ids are unique and every built-in is registered; every icon exists in the studio icon set.
  Tests: `tests/test_apps.py::test_ids_unique_and_complete`, `tests/test_apps.py::test_app_icons_exist_in_the_studio_icon_set`.
- **R-APP-4** Clip apps bake to a GIF within the 40 KB budget and their loops are seamless and deterministic.
  Tests: `tests/test_apps.py::test_clips_bake`, `tests/test_newapps.py::test_loops_are_seamless_and_deterministic`,
  `tests/test_apps.py::test_synthwave_loop_is_seamless`, `tests/test_gfx.py::test_gif_budget_is_a_hard_limit`.
- **R-APP-5** Drawing never leaves the grid: primitives and text clip.
  Tests: `tests/test_gfx.py::test_primitives_clip_to_panel`, `tests/test_gfx.py::test_text_never_draws_outside_clip`.
- **R-APP-6** Panel type is 1-bit bitmap fonts (`tiny` 5 px, `small` 7 px, `big` 10 px digits) with distinct glyphs.
  Tests: `tests/test_gfx.py::test_fonts_are_well_formed`, `tests/test_gfx.py::test_tiny_letters_distinct`.
- **R-APP-7** Photos (uploads, album art) are calibrated once at import; UI colours never are.
  Tests: `tests/test_gfx.py::test_calibration_crushes_black_and_keeps_white`.
- **R-APP-8** Apps that can't run on this host (OS feature, browser, Android) render an explicit unsupported state.
  Tests: `tests/test_compat.py::test_apps_render_unsupported_state`,
  `tests/test_compat.py::test_settings_marked_unsupported_still_render`,
  `tests/test_web_apps.py::test_apps_that_cant_run_in_a_tab_say_why`.
- **R-APP-9** Theme-aware apps follow the page theme's LED palette only where the user hasn't picked a colour; photos,
  flags, games and casino tables keep their own colours.
  Tests: `tests/test_page_themes.py::test_themed_settings_only_touch_untouched_colours`,
  `tests/test_page_themes.py::test_own_colours_stay_with_photos_flags_games_and_the_casino`,
  `tests/test_page_themes.py::test_aware_apps_render_every_option_in_a_theme`.
- **R-APP-10** UI colours are LED-safe (dark tones lit, saturated); page-theme panel palettes too.
  Tests: `tests/test_page_themes.py::test_panel_palette_is_led_safe`.

## Invariants

- **I-APP-1** `render()` does no I/O, no sleeping, no network, no file reads; randomness in clips has a fixed seed.
- **I-APP-2** Never index `Frame.px` with unchecked coordinates; leave a 1 px text margin unless the design says not.
- **I-APP-3** Deterministic animation is a `clip`, never a high-fps stream; stream only what changes with live data.
- **I-APP-4** No hand-built studio UI for a single app: the form comes from the schema.
- **I-APP-5** New settings fields have defaults (stored settings may be stale).
- **I-APP-6** Original art only: no copied sprites, fonts, characters or brand assets.

## Interfaces

`App` SDK (`engine/app.py`): `Settings`, `uses`, `kind()`, `render()`, `clip_key()`, `clip_colors`, `status()`,
`private_status()`, `tv_extra()`, `actions`, playlist hooks. HTTP: `/api/apps/{id}/activate|settings|actions/{a}|preview.gif`.
`deskdot preview <id>` renders any app to PNG without hardware.

## Open questions

- "One hero element readable from 2 m" (DISPLAY_DESIGN.md) is checked by eye in `deskdot preview`, not by a test.

Last verified: 2026-10-29
