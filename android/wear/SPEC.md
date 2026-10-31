# Watch spec (`android/wear/`)

Parent: [root SPEC.md](../../SPEC.md). Taste: [docs/DESIGN_TASTE.md](../../docs/DESIGN_TASTE.md) §1 and §5
"Watch app". Phone host: [android spec](../SPEC.md).

## Purpose

DeskDot on a Wear OS watch (first target: Fossil Gen 6, Wear OS 3 / API 30, 32-bit, 416×416 round OLED, small
battery). The watch is a **light remote of the phone**: it shows what's on the panel, switches apps and presets,
plays and pauses, and works as a small casino remote, while the phone app runs the engine. The watch app ships as
`com.deskdot.app` with the same release signature as the phone app, so Google's Wearable Data Layer links the two;
it talks to the phone only (Message / Data / Channel clients), never to the laptop over Wi-Fi.

This PR adds the shared piece every watch surface needs first: the casino's table themes as generated Kotlin. The
Gradle module itself lands in a following PR.

## Requirements

- **R-WEAR-1** The watch wears the 21 casino table themes with the same ids, names and order as the studio and the
  phone, generated from `TABLE_THEMES` (`scripts/gen_watch_themes.py` → `WatchThemes.gen.kt`), never a separate
  palette; Cyber grid dark is the default, and an unknown or old theme id falls back to it.
  Tests: `tests/test_watch_themes.py::test_generated_watch_themes_are_current`,
  `tests/test_watch_themes.py::test_every_table_is_on_the_watch_in_the_studio_order`.
- **R-WEAR-2** Every colour the watch draws with is a plain, opaque colour, and each table's accent is bright enough
  to read as a rim on OLED black. Tests: `tests/test_watch_themes.py::test_watch_palette_is_usable_on_oled`,
  `tests/test_watch_themes.py::test_argb_reads_css_colours`, `tests/test_watch_themes.py::test_argb_refuses_gradients`.
- **R-WEAR-3** Other watch apps (the Orbit launcher, the watch faces) take their copy of the themes from the same
  generator under their own package. Tests: `tests/test_watch_themes.py::test_another_apps_copy_uses_its_own_package`.
- **R-WEAR-4** The watch follows the phone's theme choice (table and light/dark), synced over the Data Layer;
  switching cross-fades. Dark is forced in ambient, with Battery Saver and below 20 % battery, and the option says so
  in plain words. Tests: none yet (gap).
- **R-WEAR-5** Low energy: ambient is low-bit and burn-in safe with at most one update a minute and at most 15 % lit
  pixels; nothing polls (event-driven Data Layer messages, WorkManager with constraints for anything periodic); no
  wake locks; Tiles and Complications before an always-running activity. Every change reports measured numbers
  (`dumpsys batterystats`, the Energy profiler). Tests: none yet (gap).

## Invariants

- **I-WEAR-1** OLED black first: the table's accent and felt tone appear as rims, rings, tiles and the glass edge,
  never as a full-screen fill; glass is static (baked), on floating chrome only.
- **I-WEAR-2** The watch never owns the panel's BLE link; the phone's engine does (root I-ROOT-1).
- **I-WEAR-3** The watch app and the phone app share one applicationId and one release signature; the release
  keystore stays outside git (root I-ROOT-5).

## Interfaces

- `WatchThemes.gen.kt` (package `com.deskdot.wear.theme`): `WatchThemes.ALL`, `WatchThemes.get(id)`,
  `WatchThemes.DEFAULT`, `WatchTheme.palette(dark)`; colours are ARGB ints (`android.graphics.Color` or Compose
  `Color(Int)`).
- Planned: Data Layer paths between the phone app and the watch app (to be specified with the module).

## Open questions

- The exact Data Layer messages (panel preview frames, app and preset lists, casino chip bets) and how often the
  preview may update without costing battery.
- Distribution: a separate `DeskDot-Watch-<version>.apk` in each GitHub release now; one Google Play listing later.

Last verified: 2026-10-31
