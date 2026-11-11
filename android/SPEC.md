# Android spec (`android/`, `device/android.py`, `android_main.py`)

Parent: [root SPEC.md](../SPEC.md). How: [android/README.md](README.md), ADR
[0011](../docs/adr/0011-android-host-app.md). Releases: [packaging spec](../packaging/SPEC.md).

## Purpose

The whole DeskDot engine on an Android phone (8.0+, arm64), so the panel keeps playing with the laptop off. Python
runs unchanged in Chaquopy; only the BLE backend differs (`device/android.py` ↔ `BleBridge.kt`). The app shows the
studio full screen.

## Requirements

- **R-AND-1** The Android BLE backend follows the same link physics: paced packets one message at a time, reconnect
  and replay after a link loss, retry with an error when the panel isn't found, recover after a failed write.
  Tests: `tests/test_android_device.py::test_frames_are_split_into_paced_packets_one_at_a_time`,
  `tests/test_android_device.py::test_link_loss_reconnects_and_replays_the_screen`,
  `tests/test_android_device.py::test_panel_not_found_retries_with_an_error`,
  `tests/test_android_device.py::test_a_failed_write_marks_the_link_down_and_recovers`,
  `tests/test_android_device.py::test_connects_and_reports_the_panel`.
- **R-AND-2** The config builds the Android device on Android. Tests: `tests/test_android_device.py::test_config_builds_the_android_device`.
- **R-AND-3** `GET /api/meta` marks the host features Android lacks as unsupported. Tests:
  `tests/test_compat.py::test_meta_on_android_marks_unsupported`.
- **R-AND-4** Runs on its own: `EngineService` is a foreground service that restarts a crashed engine, and
  `BootReceiver` starts it after a reboot and after an update. Its wake, Wi-Fi and multicast locks belong to
  `PowerGate` (R-AND-12), not to the service's lifetime. Tests: none yet for the service (gap — verified on the phone).
- **R-AND-12** The phone sleeps when there is nothing to drive (ADR 0016). The engine (`keepawake.py`) reports
  awake / asleep to `PowerGate.kt`: awake while the app is on screen, a hand-over or pairing runs, a LAN device called
  in the last 2 minutes, something is being written, the panel is connected and the engine streams live content
  (a stream app, an overlay, a playlist, background alerts), or the panel was lost under 3 minutes ago; asleep (no wake
  or Wi-Fi lock, after 30 s) when the panel is released, held by another DeskDot, missing for 3 minutes, or runs a
  baked clip / its firmware clock. Asleep, the BLE link stays up and an inexact alarm wakes the engine for its next
  reconnect attempt, a clip re-bake or a look every 15 minutes; the event loop's clock counts deep sleep
  (`BootClockLoop`). Opening the app wakes it and restarts the reconnect back-off. Tests:
  `tests/test_keepawake.py::test_decide_awake_only_when_there_is_something_to_drive`,
  `tests/test_keepawake.py::test_static_clip_lets_the_phone_sleep_after_the_grace_and_live_content_wakes_it`,
  `tests/test_keepawake.py::test_released_panel_sleeps_and_reports_only_changes`,
  `tests/test_keepawake.py::test_missing_panel_sleeps_between_attempts_with_an_alarm_for_the_next`,
  `tests/test_keepawake.py::test_a_clip_that_rebakes_with_time_asks_for_an_alarm`,
  `tests/test_keepawake.py::test_opening_the_app_wakes_and_retries_the_panel_now`,
  `tests/test_keepawake.py::test_lan_request_middleware_keeps_it_awake`, `tests/test_keepawake.py::test_boot_clock_loop_runs_timers`
  (the Kotlin locks and alarm: verified on the phone).
- **R-AND-13** The multicast lock is held only while the hand-over setting is on and the screen is on or a hand-over
  or pairing runs; off means no lock. Beacons are still sent, and release requests arrive over HTTP, so another
  DeskDot can always take the panel. Tests: `tests/test_keepawake.py::test_handover_holds_multicast_and_the_setting_off_never_does`,
  `tests/test_keepawake.py::test_take_asks_the_quiet_last_holder_to_let_go` (the lock itself: verified on the phone).
- **R-AND-14** Finding the panel: `BleBridge` connects directly by MAC (the engine's, else the last panel the phone
  connected to), and its fallback scan is filtered by that MAC (Android delivers no results from an unfiltered scan
  while the screen is off), else — screen off, no MAC yet — by the panel's manufacturer id (`0x5254`); only with the
  screen on is it unfiltered (any `IDM-` name). Scan mode: low-latency only while the app is on screen, balanced
  with the screen on, low-power (20 s window) with it off. Tests: none yet (gap — Kotlin `PowerPolicy`; verified on
  the phone).
- **R-AND-5** Only the studio (`127.0.0.1` / `localhost`) opens inside the app; other links open in the browser.
  Tests: none yet (gap).
- **R-AND-6** System bar icon contrast and the window background follow the studio theme (`DeskDotAndroid.setBars`),
  remembered for the next cold start (no black flash). The bars themselves are transparent (R-AND-9). Tests: none yet
  (gap — verified on the phone).
- **R-AND-7** Self-update: the engine downloads the APK from the latest release and checks the release's signed
  `checksums.txt` and the APK's SHA-256 (packaging/SPEC.md R-REL-17); `Updater.kt` checks the same signature and
  checksum again in Kotlin (`ReleaseVerifier`, the key built into the app; anything wrong → `unverified`, the APK is
  deleted), refuses an APK signed with another key, then opens Android's installer. Tests:
  `tests/test_updates.py::test_asset_selection_per_platform`, `tests/test_updates.py::test_checksum_mismatch_is_refused`,
  `tests/test_updates.py::test_android_refuses_when_updater_kt_says_unverified`,
  `android/app/src/test/java/com/deskdot/app/ReleaseVerifierTest.kt` (the APK-signer check is still untested).
- **R-AND-8** `versionCode = major*10000 + minor*100 + patch` from `src/deskdot/__init__.py`, so every release upgrades
  in place. Tests: none yet (gap — computed in `app/build.gradle.kts`).

- **R-AND-9** Full screen: the app draws edge to edge (`enableEdgeToEdge`, transparent status and navigation bars, no
  contrast scrim). The window insets reach the studio as CSS variables `--safe-top/bottom/left/right` (`insets()`
  before first paint, pushed again on every change); the keyboard shrinks the WebView instead, so no control or field
  hides under a bar or the keyboard. Tests: none yet (gap — verified on the phone); the studio side uses only
  `var(--safe-*)` (web/SPEC.md R-STU-11).
- **R-AND-10** Launch: the Android 12+ SplashScreen API (core-splashscreen) shows only the page colour and hands over at
  once to the native LED intro (`IntroView`): the logo builds itself out of dots in about 1.4 s, stays lit with a faint
  shimmer while the engine is still starting, and fades into the studio when it calls `introDone()`. No "starting"
  text; a real problem (no Bluetooth permission, no engine after 30 s) gets a kind message under the logo. Animations
  follow the system's animation scale (off = the lit logo at once). Tests: none yet (gap — verified on the phone).
- **R-AND-11** Back works innermost first (`window.__deskdotBack()`, `web/src/lib/backStep.ts`): it closes what is open
  in the studio (a sheet, dialog or menu); else, on the Apps, Presets or Settings tab, it goes to the Panel tab; only on
  the Panel tab with nothing open does it send the app to the background. Tests: `tests/js/back_step.test.mjs`.

## Invariants

- **I-AND-1** The release keystore and `android/keystore.properties` are never committed and never given to CI unless the
  owner adds the four `ANDROID_*` repository secrets on purpose (docs/RELEASING.md); otherwise the
  APK is built and signed on the maintainer's machine. Every release uses the same key.
- **I-AND-2** The Python engine is not forked for Android; Android-only code lives in `device/android.py`,
  `android_main.py` and the Kotlin shell.
- **I-AND-3** Only one central may hold the panel: the laptop's engine is stopped while the phone drives it.
- **I-AND-4** Launcher icons are generated by `android/tools/gen_icons.py`; the generated XML is never hand-edited.
- **I-AND-5** The vendored pydantic-core wheel matches the `pydantic` version exactly.

## Interfaces

`window.DeskDotAndroid` (`version()` = 2): `setBars(status, nav, page, lightIcons)`, `icons()`, `getIcon()`,
`setIcon(id)`, `display()`, `insets()`, `introDone()`; the app calls the studio's `window.__deskdotBack()`; FileProvider `com.deskdot.app.updates`; `BleBridge` ↔ `device/android.py`.

## Open questions

- Kotlin unit tests exist only for `ReleaseVerifier` (`android/app/src/test`, CI job "Android — JVM unit tests");
  the rest of the shell (R-AND-4…6, the APK-signer check in R-AND-7, the locks of R-AND-12…14) is verified on the
  user's phone.
- Connected but idle, the link keeps `CONNECTION_PRIORITY_HIGH`; a low-power connection interval while a clip plays
  would save radio power but changes link physics (rule 13): measure on the panel first.

Last verified: 2026-11-11
