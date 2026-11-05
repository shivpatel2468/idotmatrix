# Watch spec (`android/wear/`)

Parent: [root SPEC.md](../../SPEC.md). Taste: [docs/DESIGN_TASTE.md](../../docs/DESIGN_TASTE.md) §1 and §5
"Watch app". Phone host: [android spec](../SPEC.md).

## Purpose

DeskDot on a Wear OS watch (first target: Fossil Gen 6, Wear OS 3 / API 30, 32-bit, 416×416 round OLED, small
battery). The watch is a **light remote of the phone**: it shows what's on the panel, switches apps and presets,
plays and pauses, and works as a small casino remote, while the phone app runs the engine. The watch app ships as
`com.deskdot.app` with the same release signature as the phone app, so Google's Wearable Data Layer links the two;
it talks to the phone only (Message / Data / Channel clients), never to the laptop over Wi-Fi.

The `:wear` Gradle module is the watch app; the phone half is `WearBridgeService` in `android/app`, which answers the
watch from the engine running on the phone (`127.0.0.1:8765`).

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

- **R-WEAR-6** The watch is a remote only: it asks the phone over the Wearable Data Layer and the phone's
  `WearBridgeService` answers from its own engine. The phone answers **only** the paths listed under Interfaces
  (read the state, the frame, the app and preset lists; show an app; play a preset; set brightness 5–100) — never
  raw device, calibration, link or settings endpoints. App and preset ids must match `^[a-z0-9_-]{1,64}$`.
  Tests: none yet (gap: a bridge test against a fake engine).
- **R-WEAR-7** Home shows exactly what the panel shows (the engine's frame, drawn pixel for pixel), the app's name
  and whether the panel is connected, brightness, presets, and the apps grouped by kind; a kind opens its apps.
  Glass ‹ › beside the preview (or a sideways swipe on it) show the previous / next app, in the order the watch lists
  them (kinds in the studio's order, then by name), wrapping at the ends. The app's name is its real name, never the
  engine's raw `current` object (older phone builds sent it as text; the watch reads the app id out of it).
  Every list is the bubbly glass list in the Orbit launcher's look: glass pills with an icon per kind, jelly glass
  buttons, the table's accent and felt on the rims; rows curve away at the round edge, snap to the centre once, and a
  glass bubble floats above the centred row and moves with the scroll. The crown scrolls every list (Orbit's
  `rotaryScrollable` with a centre snap); the list asks for the crown's focus when shown and again on every resume.
  Tests: `android/wear/src/test/.../WatchScreensTest` (every screen in Cyber grid, Classic green, Royal blue and
  Cyber grid light; the crown case scrolls Home with the crown alone), `RemoteLogicTest` (stepping, the name).
- **R-WEAR-8** The watch asks the phone only while its screen is awake and visible (every 2 s on Home for the
  preview, 5 s elsewhere) and not at all in ambient, where it shows one dim, still line updated on the minute
  signal. When the phone or its engine can't be reached it says so in plain words with a retry. Tests: none yet (gap).

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
- Data Layer request/response paths (watch `PhoneLink` → phone `WearBridgeService`), JSON in and out, errors as
  `{"error": "engine" | ...}`: `/deskdot/summary` → `{connected, status, current, name, brightness, preset, theme}` ·
  `/deskdot/apps` → `[{id, name, category}]` · `/deskdot/presets` → `[{id, name}]` · `/deskdot/frame` → PNG
  (128 × 128) · `/deskdot/activate` ← `{id}` · `/deskdot/preset` ← `{id}` · `/deskdot/brightness` ← `{value}`.

## Open questions

- Casino chip bets from the watch, and measured battery cost of the 2 s preview (R-WEAR-5 asks for numbers).
- Distribution: a separate `DeskDot-Watch-<version>.apk` in each GitHub release now; one Google Play listing later.

Last verified: 2026-11-05
