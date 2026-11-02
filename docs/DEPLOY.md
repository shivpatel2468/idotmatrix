# Where to run DeskDot

The engine must run on a machine that is **within Bluetooth range of the panel** (~5–10 m) and has
**Bluetooth LE**. Everything else (studio, MCP, scripts) talks to it over HTTP, from any device on your network.

| Host | Works? | Notes |
| --- | --- | --- |
| **Raspberry Pi Zero 2 W / 3 / 4 / 5** | ✅ Recommended | Built-in BLE, ~1–3 W, runs the same code on Linux/BlueZ. One-command install below. |
| Old laptop / mini PC (Windows or Linux) | ✅ | Same as your laptop; set it to never sleep. |
| Your laptop | ✅ | With **hand-off** (below) the panel keeps showing a clock or animation while it sleeps. |
| Spare Android phone (8.0+, 64-bit) | 🧪 New | The **DeskDot Android app** runs the whole engine on the phone as an always-on service — see [android/README.md](../android/README.md). Keep it plugged in. (Termux alone can't use Bluetooth LE.) |
| iPhone | ❌ | iOS suspends background apps; it can't keep the panel's link open. |
| Wi-Fi router | ❌ | No Bluetooth and far too little RAM/CPU on typical routers. |
| Alexa / Google Home | ❌ as a host | Closed platforms. They *can* control DeskDot via Home Assistant (see ROADMAP). |
| ESP32 | ⚠️ Future | Could act as a Wi-Fi→BLE bridge that pulls baked GIFs from a DeskDot server (Tronbyt-style). |

Only **one** device can hold the panel's Bluetooth link. Stop DeskDot on the laptop when the Pi or phone runs it.

## Hand-off: the panel keeps going without a computer

The panel's firmware can run by itself: its **clock keeps time** and it **loops the last GIF** it was given.
DeskDot uses that (Settings → Panel → *When the computer is off*):

- **On exit** (Ctrl+C, closing the terminal, `systemctl stop`): uploads the chosen hand-off — the firmware
  clock (default) or a looping GIF baked from any app (e.g. Pet World, Ambient, Weather) — then disconnects.
- **On sleep** (Windows): sends the firmware clock (there's only a moment before the computer suspends) and
  takes the panel back on wake.
- **Hand over now** button / `POST /api/handoff/now`: do it manually, e.g. before closing the lid.
  Showing any app afterwards takes the panel back.

## Raspberry Pi install

1. Flash **Raspberry Pi OS Lite (64-bit)** with Raspberry Pi Imager; in its settings set the hostname,
   your Wi-Fi and enable SSH.
2. On the laptop, build the studio once: `cd web; npm run build`.
3. Copy the project to the Pi (the Pi doesn't need Node):
   ```powershell
   scp -r C:\Users\<you>\Downloads\idotmatrix pi@raspberrypi.local:~/deskdot
   ```
4. On the Pi:
   ```bash
   cd ~/deskdot && bash scripts/install-pi.sh
   ```
5. Stop DeskDot on the laptop, then open `http://raspberrypi.local:8765` from any device.

The installer adds BlueZ, installs `uv` (which brings its own Python 3.13), installs dependencies, sets
`host = "0.0.0.0"` and `lan_studio = true` so the studio is reachable on the LAN, and registers a `deskdot` systemd service that starts
at boot, restarts on failure and hands off gracefully on stop. Logs: `journalctl -u deskdot -f`.

Things that read *the computer itself* switch off on a headless Pi: now playing, the active app, OS notifications,
screen and camera mirror, On Air (on a Pi desktop with X11, `playerctl` and `xdotool`, now playing and the active app
work). The full matrix: [COMPATIBILITY.md](COMPATIBILITY.md). Everything network-based — weather,
sports, stocks, flights, space, radar, the games, pets, clocks — works the same.

## Playing with friends (local Wi-Fi)

Open a multiplayer game in the studio's Play mode and choose **Play with friends**: the panel shows a QR code,
friends on the same Wi-Fi scan it and get a controller on their phone. The first time, Windows asks whether Python
may use the network — choose **private networks**. Only the controller page is reachable from other devices.

## Laptop checklist (if the laptop stays the host)

- Run with `.venv\Scripts\python -m deskdot serve` and leave the terminal open.
- By default the studio only opens on this laptop (other devices can only reach game controllers). To use the
  studio from your phone too, set `lan_studio = true` in `deskdot.toml`, allow Python through the Windows firewall,
  and open `http://<laptop-ip>:8765` on the phone. There's no login, so only do this on a network you trust.

## Installers

People who don't want a terminal install DeskDot from the
[latest release](https://github.com/shivpatel2468/idotmatrix/releases/latest) (first-run steps in plain words:
README § Download). What gets built, all from `packaging/`:

| File | Built by | What it is |
| --- | --- | --- |
| `DeskDot-Setup-<v>-x64.exe` | CI (`release.yml`) or `packaging\windows\build.ps1` | Inno Setup installer (`packaging/windows/DeskDot.iss`): per-user into `%LOCALAPPDATA%\Programs\DeskDot`, no admin. Start menu entry (+ "simulated panel" entry), optional desktop icon, optional start-with-login (`HKCU\…\Run\DeskDot Launcher`, the value the tray's "Start with login" toggles), uninstaller. |
| `DeskDot-<v>-macOS-arm64.dmg`, `…-x64.dmg` | CI (Apple silicon on `macos-latest`, Intel on `macos-15-intel`) | `DeskDot.app` (PyInstaller `BUNDLE`, Info.plist with the Bluetooth / microphone / camera / Apple events / local network reasons) on a drag-to-Applications disk image (`packaging/macos/build_dmg.sh`). |
| `DeskDot-<v>.apk` | `scripts/release.py` on the owner's machine, or CI when the optional `ANDROID_*` secrets exist (docs/RELEASING.md) | the Android app, signed with the release key (`DeskDot-Wear-<v>.apk` for the watch, once `android/wear` exists) |
| `checksums.txt` | CI | `sha256sum` of every file; the in-app updater refuses anything that doesn't match |

Both desktop builds are one PyInstaller spec (`packaging/deskdot.spec`, onedir) with the built studio, the package's
html/js/fonts and `deskdot.example.toml`; tests, `legacy/`, the MCP server and the Android/browser-only modules
are left out. The frozen program is `src/deskdot/desktop.py`:

- **Its own folder for everything it writes**: `%LOCALAPPDATA%\DeskDot` (Windows), `~/Library/Application Support/DeskDot`
  (macOS); `DESKDOT_HOME` overrides it. First run copies `deskdot.example.toml` there as `deskdot.toml`. The install
  folder is never written to, so updates and uninstalls keep settings, `data/` and `plugins/`.
- **Double-click** = start the engine in the background (`DeskDot serve`, detached), open the studio in the browser,
  run the launcher (tray icon on Windows, the Ctrl+Alt+Space bar). `--background` (start with login) skips the browser.
- **Any CLI command still works**: `DeskDot.exe serve --sim --port 8799`, and on Windows `deskdot-cli.exe` is the same
  program with a console (`deskdot-cli scan`, `deskdot-cli doctor`). The windowed exe logs to `data/deskdot.log`.

Build the Windows installer locally (its own venv in `packaging\build\venv`; your `.venv` isn't touched; needs
Inno Setup 6: `winget install JRSoftware.InnoSetup`):

```powershell
powershell -ExecutionPolicy Bypass -File packaging\windows\build.ps1            # studio + PyInstaller + installer
powershell -ExecutionPolicy Bypass -File packaging\windows\build.ps1 -SkipStudio -SkipInstaller   # just the app
packaging\build\dist\DeskDot\deskdot-cli.exe serve --sim --port 8799          # try the frozen engine
```

On a Mac: `UV_PROJECT_ENVIRONMENT=packaging/build/venv uv sync --frozen --no-dev --extra launcher --group packaging`,
`uv run --no-sync python packaging/prepare.py`, `uv run --no-sync pyinstaller packaging/deskdot.spec --noconfirm
--distpath packaging/build/dist --workpath packaging/build/work`, then `bash packaging/macos/build_dmg.sh <v> arm64`.

### Unsigned builds

The builds aren't code-signed (that needs paid certificates), so the first start shows a warning once:

- **Windows SmartScreen** ("Windows protected your PC"): **More info → Run anyway**. Signed builds that many people
  download stop showing it.
- **macOS Gatekeeper** ("can't be opened because Apple cannot check it"): right-click the app → **Open → Open**; on
  macOS 15+ **System Settings → Privacy & Security → Open Anyway**. The app is ad-hoc signed, not notarized.
- **Android** asks to allow installing unknown apps, for the browser the first time and for DeskDot when it updates
  itself.

In-app updates download with Python, not a browser, so the update itself doesn't trigger these warnings again.

### Code signing later (optional repository secrets)

`release.yml` signs automatically when these secrets exist (Settings → Secrets and variables → Actions); without them
it builds unsigned exactly as now:

| Secret | For |
| --- | --- |
| `WINDOWS_CERT_PFX_BASE64`, `WINDOWS_CERT_PASSWORD` | an Authenticode code-signing certificate (`.pfx`, base64): `signtool` signs `DeskDot.exe`, `deskdot-cli.exe` and the installer |
| `MACOS_CERT_P12_BASE64`, `MACOS_CERT_PASSWORD`, `MACOS_SIGN_IDENTITY` | an Apple "Developer ID Application" certificate (`.p12`, base64) and its identity name: hardened-runtime signing of the app and the dmg |
| `APPLE_ID`, `APPLE_TEAM_ID`, `APPLE_APP_PASSWORD` | notarization with `notarytool` + stapling (needs the three above; an app-specific password) |

The Android release key stays on the maintainer's machine unless the owner deliberately adds the four `ANDROID_*`
secrets (docs/RELEASING.md § Signing the APK on GitHub); then the `android` job signs the APK in CI.

## Releases

**Use `uv run python scripts/release.py <version>`** — it does every step below, resumes if interrupted and asks
before merging or deploying: [RELEASING.md](RELEASING.md). The manual steps, for reference:

1. Bump the version in `pyproject.toml` and `src/deskdot/__init__.py` (the Android app reads it from there:
   `versionCode = major*10000 + minor*100 + patch`), `uv lock`, the README badge; write the plain-words
   `## <v> — <date> · <headline>` section in `WHATS_NEW.md` (it becomes the release notes and what the studio's
   Updates block shows) and the CHANGELOG entry. Commit on a `release/v<v>` branch, open a pull request, squash-merge it once CI is green.
2. Tag the merged `main` and push only the tag: `git switch main && git pull && git tag -a v<v> -m "DeskDot <v>" && git push origin v<v>`. `release.yml` checks that the tag
   matches the code and WHATS_NEW, runs ruff + the fast tests, builds the studio, the Windows installer and both
   dmgs (each smoke-tested: the frozen engine must answer `/api/health`), writes `checksums.txt` and creates a
   **draft** release with that WHATS_NEW section.
3. Build the APK locally and add it, with its checksum, to the draft:

   ```powershell
   cd web; npm run build; cd ..\android; .\gradlew assembleRelease; cd ..
   gh release download v<v> -p checksums.txt -D tmp\release --clobber
   $apk = "android\app\build\outputs\apk\release\DeskDot-<v>.apk"
   "$((Get-FileHash $apk -Algorithm SHA256).Hash.ToLower())  DeskDot-<v>.apk" | Add-Content tmp\release\checksums.txt -Encoding ascii
   gh release upload v<v> $apk tmp\release\checksums.txt --clobber
   ```

4. Check the draft (files, notes), then publish it: `gh release edit v<v> --draft=false --latest`. From that moment
   every installed DeskDot that checks for updates offers it.

### How in-app updates work

`src/deskdot/updates.py` (API: docs/API.md § Updates). The engine asks GitHub for the latest release at most every
6 h (opt-out: Settings → Device → Updates). "Install" downloads the asset for this system into `data/updates/`,
checks its SHA-256 against `checksums.txt`, then:

| Installed as | Hand-off |
| --- | --- |
| Windows installer | quits the launcher, starts the new installer with `/SILENT /SUPPRESSMSGBOXES /CLOSEAPPLICATIONS` and exits the engine the normal way (the panel gets its hand-off); the installer waits up to 20 s for DeskDot to close, replaces the program folder and starts DeskDot again |
| macOS app | a small script waits for the engine to exit, mounts the dmg, swaps the `.app` where it is (e.g. `/Applications`) and opens it; if that folder isn't writable it just opens the dmg to drag across |
| Android app | `Updater.kt` checks the APK is signed with the same key, then opens Android's installer (the first time, Android asks to let DeskDot install apps) |
| From source (`uv run`, the Pi service) | nothing is installed: the studio says `git pull`, `uv sync`, `cd web && npm run build`, restart |
