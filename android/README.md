# DotDeck for Android

The whole DotDeck engine running on an Android phone (8.0+, 64-bit ARM): an app that stays connected to the panel
and keeps playing with the laptop off. Why and how: [docs/adr/0011-android-host-app.md](../docs/adr/0011-android-host-app.md).

- **Python engine, unchanged**: `src/dotdeck` is packaged with [Chaquopy](https://chaquo.com/chaquopy/) (CPython 3.13
  inside the app). Only the BLE backend differs: `device/android.py` drives `BleBridge.kt`.
- **Always on**: `EngineService` is a foreground service (persistent notification, partial wake lock, Wi-Fi
  lock), restarts the engine if it ever crashes, and `BootReceiver` starts it after a reboot.
- **Studio**: the app shows the studio full screen (`http://127.0.0.1:8765` on the phone). Phone controllers for
  multiplayer work on the Wi-Fi exactly as on the laptop (`/p/<code>`).

## Build

Needs JDK 17, the Android SDK (platform 35, build-tools 35) and a Python 3.13 on the build machine.

```powershell
cd web; npm run build; cd ..        # the studio is bundled into the APK
cd android
# local.properties (not committed):
#   sdk.dir=C:/path/to/Android/sdk
#   dotdeck.buildPython=C:/path/to/python3.13.exe
./gradlew assembleDebug             # → app/build/outputs/apk/debug/app-debug.apk
```

## Install on the phone

1. On the phone: **Settings → About phone → tap "Build number" 7 times**, then **Developer options → USB debugging** on.
2. Plug it into the laptop, accept the "Allow USB debugging?" prompt on the phone.
3. `adb install -r app/build/outputs/apk/debug/app-debug.apk` (adb is in the SDK's `platform-tools`).
4. Open **DotDeck**, allow **Nearby devices** (and notifications), and allow it to **ignore battery optimisation**.

Only one thing can hold the panel's Bluetooth link: **stop the engine on the laptop first**, and don't open the
iDotMatrix app while DotDeck runs.

Some vendors (Xiaomi, Oppo, Vivo, Samsung…) add their own background killers on top of Android's: also set the app
to **"No restrictions" / "Allow background activity" / "Autostart"** in the phone's battery settings.

## Settings on the phone

Same `dotdeck.toml` keys as the desktop, in the app's files directory
(`adb shell run-as com.dotdeck.app` → `files/dotdeck.toml`). For example, to open the studio to your laptop over
Wi-Fi: `lan_studio = true`, then browse to `http://<phone-ip>:8765`.

## The vendored pydantic-core wheel

`app/wheels/pydantic_core-*-android_24_arm64_v8a.whl` — pydantic-core is a Rust extension with no official Android
build. Rebuild it whenever `pydantic` is upgraded (the versions must match exactly):
`tools/build-pydantic-core.sh` (Rust + `rustup target add aarch64-linux-android`, the Android NDK, maturin, and
Chaquopy's Python target for `libpython3.13.so` and `_sysconfigdata`).
