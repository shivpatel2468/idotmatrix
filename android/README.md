# DeskDot for Android

The whole DeskDot engine running on an Android phone (8.0+, 64-bit ARM): an app that stays connected to the panel
and keeps playing with the laptop off. Why and how: [docs/adr/0011-android-host-app.md](../docs/adr/0011-android-host-app.md).

- **Python engine, unchanged**: `src/deskdot` is packaged with [Chaquopy](https://chaquo.com/chaquopy/) (CPython 3.13
  inside the app). Only the BLE backend differs: `device/android.py` drives `BleBridge.kt`.
- **Always on**: `EngineService` is a foreground service (persistent notification, partial wake lock, Wi-Fi
  lock), restarts the engine if it ever crashes, and `BootReceiver` starts it after a reboot.
- **Studio**: the app shows the studio full screen (`http://127.0.0.1:8765` on the phone). Phone controllers for
  multiplayer work on the Wi-Fi exactly as on the laptop (`/p/<code>`).

## The app shell (`MainActivity.kt`)

- **Refresh rate:** the window asks for the fastest display mode at the current resolution
  (`preferredDisplayModeId` + `preferredRefreshRate`, again on resume because some skins reset it) — 120 Hz on a
  120 Hz phone. The window is hardware accelerated; the WebView keeps the default layer type on purpose (it already
  draws on the GPU; `LAYER_TYPE_HARDWARE` would add an off-screen copy of the whole page per frame). It rasters
  tiles just off screen (`offscreenPreRaster`) and runs at important renderer priority. Android may still lower the
  rate: on Xiaomi / MIUI / HyperOS set **Settings → Display → Refresh rate → High (120 Hz)** ("Default" lets the
  system drop apps to 60 Hz). Settings → Display & colour → App icon shows the rate now and the best available.
- **Only the studio opens inside the app.** Links to anything but `127.0.0.1` / `localhost` open in the browser.
- **`window.DeskDotAndroid`** (the `Bridge` inner class; web side `web/src/lib/android.ts`):

  | Call | What |
  | --- | --- |
  | `setBars(status, nav, page, lightIcons)` | system bar colours (`#rrggbb`) + icon contrast and the window background for the studio theme on screen; remembered in `deskdot.ui` prefs for the next cold start |
  | `icons()` / `getIcon()` / `setIcon(id)` | launcher icon ids (JSON), the enabled one, switch (returns false for an unknown id) |
  | `display()` | `{"hz", "max", "modes"}` — the refresh rate now, the best, all at this resolution |
  | `version()` | `1` |

  The studio calls `setBars` on every theme change (light / dark / Auto), so status bar, navigation bar and the
  window behind the page always match. Before the studio loads, `values/` (light) and `values-night/` (dark)
  colour the window like the studio's Auto default; after the first run the remembered theme is used. Android 15+
  draws apps edge to edge: there the root view is padded by the bar insets and the window background (the theme's
  page colour) shows behind the bars.

## Launcher icons

Seven options — **Classic** (today's ember dot D, the default), **Monogram** (DD in rose and gold LEDs), **Gold
leaf** (gold dot D on midnight ink), **Sunset** (brand gradient tile, white LEDs), **Porcelain** (the panel on an
ivory tile, rainbow D), **Casino chip** (ember chip on felt) and **Pixel heart**. Each is an adaptive icon
(`mipmap-anydpi-v26/ic_launcher_<id>.xml`: background + foreground vectors + a monochrome layer for Android 13
themed icons). All of them are drawn by `tools/gen_icons.py`, which also writes `web/src/lib/appIcons.ts` (the same
artwork as SVG, for the picker in Settings):

```powershell
uv run python android/tools/gen_icons.py   # after editing an icon there; never hand-edit the generated XML
```

The manifest has one `<activity-alias android:name=".Launcher<Id>">` per icon targeting `MainActivity`; exactly one
is enabled. **Settings → Display & colour → App icon** (shown only inside the app) calls `setIcon(id)`, which enables
the chosen alias first and then disables the others with `DONT_KILL_APP` — the engine keeps running and the panel
stays connected. The launcher redraws within a few seconds; some launchers (MIUI among them) remove the old
home-screen shortcut — add DeskDot to the home screen again from the app drawer.

**Changing the default:** set `android:enabled="true"` on that alias (and `false` on Classic) in
`AndroidManifest.xml` and `MainActivity.DEFAULT_ICON` to its id; `mipmap-anydpi-v26/ic_launcher.xml` (the app's own
icon in app info / recents) can point at the same layers. A choice made in Settings survives updates (PackageManager
keeps it). Adding an icon: draw it in `gen_icons.py`, run it, add its alias to the manifest and its id to
`MainActivity.ICONS`.

The first install with icon aliases replaces the launcher entry (`.MainActivity` no longer has the LAUNCHER filter),
so the home-screen shortcut from an older build may disappear once — re-add it from the app drawer.

## Build

Needs JDK 17, the Android SDK (platform 35, build-tools 35) and a Python 3.13 on the build machine.

```powershell
cd web; npm run build; cd ..        # the studio is bundled into the APK
cd android
# local.properties (not committed):
#   sdk.dir=C:/path/to/Android/sdk
#   deskdot.buildPython=C:/path/to/python3.13.exe
#   deskdot.buildPython311=C:/path/to/python3.11.exe   (only needed to build the `wear` flavor, see below)
./gradlew assembleMobileDebug        # → app/build/outputs/apk/mobile/debug/app-mobile-debug.apk (the phone build)
./gradlew assembleDebug              # builds every flavor, including `wear`
```

## Install on the phone

1. On the phone: **Settings → About phone → tap "Build number" 7 times**, then **Developer options → USB debugging** on.
2. Plug it into the laptop, accept the "Allow USB debugging?" prompt on the phone.
3. `adb install -r app/build/outputs/apk/mobile/debug/app-mobile-debug.apk` (adb is in the SDK's `platform-tools`).
4. Open **DeskDot**, allow **Nearby devices** (and notifications), and allow it to **ignore battery optimisation**.

Only one thing can hold the panel's Bluetooth link: **stop the engine on the laptop first**, and don't open the
iDotMatrix app while DeskDot runs.

Some vendors (Xiaomi, Oppo, Vivo, Samsung…) add their own background killers on top of Android's: also set the app
to **"No restrictions" / "Allow background activity" / "Autostart"** in the phone's battery settings.

## Settings on the phone

Same `deskdot.toml` keys as the desktop, in the app's files directory
(`adb shell run-as com.deskdot.app` → `files/deskdot.toml`). For example, to open the studio to your laptop over
Wi-Fi: `lan_studio = true`, then browse to `http://<phone-ip>:8765`.

## The vendored pydantic-core wheel

`app/wheels/pydantic_core-*-android_24_arm64_v8a.whl` — pydantic-core is a Rust extension with no official Android
build. Rebuild it whenever `pydantic` is upgraded (the versions must match exactly):
`tools/build-pydantic-core.sh` (Rust + `rustup target add aarch64-linux-android`, the Android NDK, maturin, and
Chaquopy's Python target for `libpython3.13.so` and `_sysconfigdata`).

## Wear (Fossil Gen 6 / Wear OS 3)

The `wear` product flavor runs the exact same `src/deskdot` engine on the watch, standalone (no paired-phone
companion app needed) — see [docs/adr/0012-wear-armv7-host.md](../docs/adr/0012-wear-armv7-host.md) for the
32-bit decision and what it cost. Summary:

- **Python 3.11, not 3.13.** Chaquopy dropped armeabi-v7a (and x86) for Python 3.12+, and the Fossil Gen 6 is
  **32-bit only** (`ro.product.cpu.abilist = armeabi-v7a,armeabi` — confirmed on the actual watch). The codebase's
  one 3.12-only construct (`def verify[T](...)` in `src/deskdot/casino/fair.py`, PEP 695) was rewritten to plain
  `TypeVar` syntax — same behaviour, now 3.11-compatible — and the whole suite passes under Python 3.11
  (`uv run --python 3.11 --extra mcp pytest -q`). `pyproject.toml`'s `requires-python` is now `>=3.11,<3.14`.
- **ABIs**: `armeabi-v7a` (the Fossil Gen 6) **and** `arm64-v8a` (other 64-bit Wear OS 3 watches), built as one
  universal `wear` APK — not split per ABI, to keep the build simple and because the watch takes v7a either way.
- **Build config**: unlike the phone (single ABI), `wear`'s `pip {}` block can't `install()` a hard-coded wheel
  path for pydantic-core — Chaquopy runs one pip install per target ABI, and a fixed path is fed to both, so the
  wrong-ABI wheel is rejected ("not a supported wheel on this platform"). Instead it adds
  `options("--find-links", "wheels")` and installs the bare `pydantic-core==2.46.5` requirement, so pip's own
  platform-compatibility check picks the matching-ABI file from `app/wheels/` for each sub-build. Also: Chaquopy's
  `pip {}` installs **accumulate** across `defaultConfig` and `productFlavors` (unlike scalar settings such as
  `version`, which override) — every dependency, even ones identical between flavors, is listed inside the
  `mobile`/`wear` flavor blocks, not in `defaultConfig`, so the phone's cp313 wheel is never fed to the wear
  (cp311) venv and vice versa.
- **Dependencies**: `numpy==1.26.2` and `psutil==7.1.3` have official cp311 wheels for both ABIs on Chaquopy's
  repository (`chaquo.com/pypi-13.1`) — same versions as the phone build. **Pillow is pinned to 9.2.0 for `wear`**
  (not 11.0.0): Chaquopy's repository has no cp311 Pillow wheel newer than 9.2.0 for either ABI. Audited: every
  Pillow API `deskdot` uses (`Image.Resampling`/`Transpose`, `ImageOps.fit`/`exif_transpose`,
  `ImageFilter.UnsharpMask`/`MedianFilter`/`GaussianBlur`, `Image.fromarray`/`frombuffer`) has existed since
  Pillow 9.1 — this is an older build of the same library, not a missing feature.
- **pydantic-core**: cross-compile for both ABIs with the generalised `tools/build-pydantic-core.sh`:
  ```powershell
  PYDANTIC_CORE=2.46.5 NDK=/path/to/ndk/27.x ARCH=armv7 PY_VERSION=3.11 HOST_PYTHON=python3.11 \
    PYTARGET=/path/to/chaquopy-target-3.11-armeabi-v7a ./build-pydantic-core.sh
  PYDANTIC_CORE=2.46.5 NDK=/path/to/ndk/27.x ARCH=arm64 PY_VERSION=3.11 HOST_PYTHON=python3.11 \
    PYTARGET=/path/to/chaquopy-target-3.11-arm64-v8a ./build-pydantic-core.sh
  ```
  **Not yet built in this repo** — needs `rustup`, `cargo` and `maturin` on the build machine, none of which were
  available in the environment this flavor was scaffolded in. `android/app/build.gradle.kts`'s `wear` flavor
  references the two resulting wheel filenames (`pydantic_core-2.46.5-cp311-cp311-android_21_armeabi_v7a.whl`,
  `...-android_24_arm64_v8a.whl`); until they exist, `assembleWearDebug` fails at the pip-install step with
  "`WARNING: ... looks like a filename, but the file does not exist`". This is the one real blocker left before the
  `wear` flavor produces an installable APK — it was confirmed to be the *only* blocker by temporarily dropping in
  two placeholder files with the right names (copies of the phone's cp313 wheel, which install but would crash at
  Python import time on a real device) and confirming `assembleWearDebug` then runs the full pipeline — pip install
  for both ABIs, manifest merge, resource merge, `compileWearDebugKotlin`, dexing, packaging — to `BUILD SUCCESSFUL`
  (placeholders were deleted afterwards; they are not, and must never be, committed).
- **Manifest**: `src/wear/AndroidManifest.xml` adds `<uses-feature android:name="android.hardware.type.watch"/>`
  and `com.google.android.wearable.standalone = true`, merged over `src/main/AndroidManifest.xml`.
- **UI**: `src/wear/java/com/deskdot/app/MainActivity.kt` replaces the phone's WebView-on-launch activity with a
  minimal round-safe placeholder (black background, a status line, an "Open Studio" button) — it never inflates a
  `WebView` until the button is tapped, to keep idle memory down on 1 GB of RAM. This is **not** the watch UI: the
  owner's round remote/studio screen is being designed separately and will replace this activity.
- **Network: identical to the phone, by design.** The owner's call: the watch is a primary host, not a crippled
  one — `lan_studio`, `host` ("0.0.0.0", gated per-route by `LanGate`), the studio reachable from other devices on
  the Wi-Fi, and multiplayer controllers joining `/p/<code>` (QR → `multiplayer.lan_ip()`, unchanged) all behave
  exactly as on the phone. `android_main.py` was not touched for this. The one real Wear-specific risk: left to
  itself, Wear OS drops the Wi-Fi radio and routes IP traffic over the Bluetooth-to-phone proxy once the screen
  sleeps — fine for a watch face checking a server, fatal for *hosting* a LAN service. `EngineService.onCreate`
  (gated by the `is_watch` bool resource, see below) calls `ConnectivityManager.requestNetwork` for a
  `TRANSPORT_WIFI` + `NET_CAPABILITY_INTERNET` network and `bindProcessToNetwork` once it's available, released in
  `onDestroy`; this is in addition to the existing `WifiManager.WifiLock` (shared with the phone), which alone is
  not enough to stop Wear OS's proxy routing. **Not tested on the watch** — no APK could be built (see pydantic-core
  below) or installed (not this session's job) to confirm the radio actually stays associated once the screen
  sleeps; this is the design based on Wear OS's documented behaviour, not a verified result.
- **Foreground service, BLE, boot receiver**: otherwise unchanged, shared with the phone (`EngineService.kt`,
  `BleBridge.kt`, `BootReceiver.kt`) — Wear OS 3 (API 30) honours `FOREGROUND_SERVICE_TYPE_CONNECTED_DEVICE`,
  wake/Wi-Fi locks and `BOOT_COMPLETED` the same way stock Android 11 does, and panel scan/connect/reconnect
  (`BleBridge`) is the same BLE GATT code on both flavors. The battery-optimisation exemption prompt
  (`MainActivity`'s `askBatteryExemption`, shared code — wear's activity calls the same path via
  `EngineService.start`) is the same mitigation against Wear OS's own Doze/App Standby as on vendor phones.
- **`R.bool.is_watch`**: `false` in `src/main/res/values/bools.xml`, `true` in `src/wear/res/values/bools.xml` —
  the one runtime flag that tells shared Kotlin code which flavor it's running as. On the watch it switches the
  engine to low power (`android_main.run(..., watch=True)`) and makes the wake lock, Wi-Fi lock and Wi-Fi network
  request follow the engine's demand (`EngineService.onPowerDemand`) instead of being held 24/7, and BleBridge
  re-links the panel through an autoConnect standby instead of periodic scans — see docs/adr/0014.
- **Build**: `cd android && ./gradlew assembleWearDebug` once the wheels above exist (needs
  `deskdot.buildPython311` in `local.properties`, see **Build** above).
- **Memory**: not yet measured on-device or on an emulator (no Wear OS emulator image and no installable APK were
  available in this session — see docs/adr/0012). `android_main.py`'s existing lazy imports (`uvicorn`, `config`,
  `server` imported inside `run()`, not at module load) already keep the engine's import-time footprint small on
  both flavors; the studio WebView is now lazy on `wear` too (see **UI** above).
