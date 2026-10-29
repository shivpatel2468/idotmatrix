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
./gradlew assembleDebug             # → app/build/outputs/apk/debug/DeskDot-<version>-debug.apk
./gradlew assembleRelease           # → app/build/outputs/apk/release/DeskDot-<version>.apk (the one for GitHub)
```

The version comes from `src/deskdot/__init__.py`: `versionName` = that version, `versionCode` = `major*10000 +
minor*100 + patch` (3.8.0 → 30800), so every release is higher than the last and Android accepts it as an update.

### Release signing

Release APKs are signed with the DeskDot release key, read from **`android/keystore.properties`** (git-ignored, never
committed, never given to CI):

```properties
storeFile=C:/Users/<you>/AppData/Local/DotDeckAndroid/release/deskdot-release.jks
storePassword=…
keyAlias=deskdot
keyPassword=…
```

The keystore and its password live outside the repo (`%LOCALAPPDATA%\DotDeckAndroid\release\`, with a
README-BACKUP.txt). **Back both up.** Every future update must be signed with the same key: if it's lost, phones
can't update in place and everyone has to uninstall and reinstall. Without `keystore.properties` a release build
falls back to the debug key and Gradle warns — fine for testing, never for GitHub.

Builds before 3.8 were signed with a debug key, so going from one of those to 3.8 needs one uninstall first.

### Updates

The app updates itself (Settings → Device → Updates): the engine finds the new `DeskDot-<version>.apk` on the latest
GitHub release, downloads it into `files/data/updates/`, checks its SHA-256 against the release's `checksums.txt`,
and `Updater.kt` opens Android's installer for it (FileProvider authority `com.deskdot.app.updates`,
`REQUEST_INSTALL_PACKAGES`). It refuses an APK signed with another key. The first time, Android asks to allow
DeskDot to install apps. After the update, `BootReceiver` (MY_PACKAGE_REPLACED) starts the engine again.

## Install on the phone

1. On the phone: **Settings → About phone → tap "Build number" 7 times**, then **Developer options → USB debugging** on.
2. Plug it into the laptop, accept the "Allow USB debugging?" prompt on the phone.
3. `adb install -r app/build/outputs/apk/release/DeskDot-<version>.apk` (adb is in the SDK's `platform-tools`), or
   download the APK from the [latest release](https://github.com/shivpatel2468/idotmatrix/releases/latest) on the phone.
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
