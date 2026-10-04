# Compatibility

What works on which host, and in which browsers. The source of truth in code is
[`src/deskdot/platforms.py`](../src/deskdot/platforms.py) (`FEATURES`); `GET /api/meta` reports the host
(`platform`, `platform_label`, `features`) and each app's `platforms` / `supported`, and the studio greys out what the
host can't do (a banner on the app, a "Windows/macOS only" badge on a setting, disabled options).

Legend: ✅ works · 🟡 works with a condition (see notes) · ❌ not available (the app shows **NOT ON &lt;OS&gt;** and the
playlist skips it; the provider reports `not available on <OS>` and never polls) · — not applicable.

Hosts: **Windows 10/11** (verified on hardware) · **macOS 12+** · **Linux** desktop (X11 / Wayland) ·
**Raspberry Pi** (Pi OS 64-bit, usually headless as a systemd service) · **Android host** (the DeskDot app, Chaquopy).

## Panel link (Bluetooth LE)

| | Windows | macOS | Linux | Raspberry Pi | Android host |
| --- | --- | --- | --- | --- | --- |
| Backend | bleak → WinRT | bleak → CoreBluetooth | bleak → BlueZ (D-Bus) | bleak → BlueZ | `device/android.py` → `BleBridge.kt` |
| Find the panel | MAC or `IDM-` name | **name only** (CoreBluetooth hides MACs; a configured MAC is ignored) | MAC or name | MAC or name | MAC or name |
| Packet size | MTU from WinRT (514) | from CoreBluetooth | BlueZ ≥ 5.62 reports it; older BlueZ: DeskDot asks via `AcquireWrite` (else 20-byte packets, slow) | same as Linux | requested by the bridge |
| Permissions | — | Bluetooth permission for the terminal / Python | user in the `bluetooth` group (installer does it) | same | "Nearby devices" |

Only one central can hold the panel: stop DeskDot on the laptop when the Pi or phone runs it.

## Host features (providers) × OS

| Feature (provider) | Windows | macOS | Linux | Raspberry Pi | Android host | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| Now playing (`media`) | ✅ GSMTC (winrt) | 🟡 Spotify / Music via AppleScript; browsers need `brew install nowplaying-cli` (limited on macOS 15.4+) | 🟡 MPRIS via `playerctl` | 🟡 desktop session only (no session D-Bus in a system service) | ❌ | Album art: player thumbnail → art URL → iTunes. Automation permission on macOS |
| Synced lyrics (`lyrics`) | ✅ | ✅ | ✅ | ✅ | 🟡 needs `syncedlyrics` in the APK (not bundled) | network (LRCLIB etc.) |
| Active window (`window`) | ✅ name, title, real icon | 🟡 icon + name; titles need Screen Recording permission | 🟡 X11 + `xdotool`, no icons (monogram); ❌ Wayland | 🟡 desktop only | ❌ | |
| Screen capture (`screen`) | ✅ all modes | 🟡 Screen Recording permission | 🟡 X11 (or GNOME `gnome-screenshot` on Wayland); "Active window"/"Around cursor" fall back to whole screen | ❌ headless | ❌ | |
| System audio / mic (`audio`) | ✅ WASAPI loopback + mic | 🟡 mic; system sound needs a loopback device (BlackHole) | ✅ PulseAudio / PipeWire-pulse (monitor + mic) | 🟡 only with PulseAudio/PipeWire and a sound device | ❌ | `soundcard`; error says why |
| Webcam (`camera`) | ✅ DirectShow | 🟡 AVFoundation, Camera permission | ✅ V4L2 | 🟡 USB webcam (V4L2); opencv wheel needs 64-bit OS | ❌ OpenCV not in the APK | hardware controls best on DirectShow |
| On Air (`onair`) | ✅ capability-access registry | ❌ | ❌ | ❌ | ❌ | the Integrations tab says so; "Preview" still works |
| Idle / eye break (`idle`) | ✅ idle + full-screen detection | ✅ idle (`ioreg`), no full-screen detection | ❌ | ❌ | ❌ | without idle data the eye-break timer never starts |
| OS notifications (`notifications`) | ✅ toast DB | 🟡 Full Disk Access; macOS 15 path + 10.13–14 path | ❌ | ❌ | ❌ | |
| Sleep hand-off | ✅ WM_POWERBROADCAST | ❌ | ❌ | ❌ | — (service) | exit hand-off works everywhere |
| System stats (`system`) | ✅ | ✅ | ✅ | ✅ | 🟡 RAM / disk / battery; **CPU, network and uptime hidden** by Android (shown as `--`) | psutil; each metric degrades on its own |
| LAN services (`lan`: OBS WebSocket, OctoPrint / Moonraker, AnkiConnect) | ✅ | ✅ | ✅ | ✅ | ✅ | plain http / sockets on your network; ❌ in the browser app |
| Network data (weather, sports, markets, stocks, flights, space/ISS, sky, quakes, rain radar, air quality, holidays, daily, trivia, headlines, currency, photos, pokédex, avatars, chess, game deals, tides, planets, wear, calendar ICS, GitHub, ntfy, Home Assistant, CI, uptime, OBS, printer, media server, Anki, custom apps) | ✅ | ✅ | ✅ | ✅ | ✅ | only need internet / the LAN service; `localhost` services (OBS, AnkiConnect, printer) must be reachable from the host — on a Pi or phone set their LAN address |
| Font Lab TTFs | ✅ | ✅ | ✅ (any `.ttf/.TTF/.otf` case) | ✅ | 🟡 bitmap fonts; TTFs from `data/fonts` if present | `assets/fonts`, `data/fonts` |

Anki: AnkiConnect's default port 8765 is DeskDot's — DeskDot uses 8766 (see the app). On Android, "AnkiConnect
Android" also defaults to 8765.

## Apps

Every app not listed here draws only from network data or its own state and works on every host.

| App | Needs | Windows | macOS | Linux | Raspberry Pi | Android host |
| --- | --- | --- | --- | --- | --- | --- |
| Now Playing | `media` (+ `audio` for Spectrum / beat sync) | ✅ | 🟡 | 🟡 playerctl | 🟡 desktop | ❌ |
| Active App | `window` | ✅ | 🟡 | 🟡 X11 | 🟡 desktop | ❌ |
| Screen Mirror | `screen` | ✅ | 🟡 | 🟡 (Source: Active window / Around cursor = Windows/macOS only) | ❌ headless | ❌ |
| Camera Mirror | `camera` | ✅ | 🟡 | ✅ | 🟡 | ❌ |
| Visualizer | `audio` | ✅ | 🟡 mic / BlackHole | ✅ | 🟡 | ❌ |
| Pet / Pet World — "Dance to music" | `audio` | ✅ | 🟡 | ✅ | 🟡 | ❌ (setting disabled; pets still play) |
| System Monitor, Composer (CPU/RAM layers) | `system` | ✅ | ✅ | ✅ | ✅ | 🟡 CPU shows `--` |
| On Air (takeover), Eye Break | `onair`, `idle` | ✅ | 🟡 eye break only | ❌ | ❌ | ❌ |
| Games, clocks, timers, canvas, text, loops, pets, ambient, creative apps | — | ✅ | ✅ | ✅ | ✅ | ✅ |

Global settings with host limits: **Audio source "System sound"** (Windows, Linux; macOS needs BlackHole),
**Hand off on sleep** (Windows), **OS notifications** (Windows, macOS), **On Air** (Windows), **Eye break**
(Windows, macOS). `GET /api/meta` → `features` has one flag for each.

## Browser host (the web app at idotmatrix.com/app/)

The engine can also run inside a browser tab (Pyodide + Web Bluetooth; `platform: "web"`, label "Browser"). There
the tab can't see the computer, so most host features above are ❌, while network data, games, creative apps and
all settings work. System Monitor is badged "Not on Browser" (psutil). Through the browser's permission prompts
(`providers/webmedia.py` + `web/webapp/host-media.js`):

| Feature | Browser host |
| --- | --- |
| Webcam (`camera`) | ✅ `getUserMedia`, computers and phones; no face tracking / hardware controls (no OpenCV) |
| Screen capture (`screen`) | 🟡 `getDisplayMedia` on desktop Chrome / Edge / Firefox / Safari, from a click; ❌ phones; "Active window" / "Around cursor" = whatever was shared |
| Mic (`audio`) | ✅ `getUserMedia({audio})` |
| System sound (`audio_loopback`) | 🟡 a shared tab's sound (Chrome / Edge on a computer; whole system on Windows / ChromeOS); falls back to the mic elsewhere |
| Idle, media session, window, notifications, On Air, system stats | ❌ |
| LAN services on plain http / sockets (`lan`: OBS, 3D printer, Anki) | ❌ an https page may not call them (mixed content) and has no sockets |
| Network data | ✅ direct where the API allows CORS, else through the site's allowlisted `/app/proxy`; Home Assistant / media servers need an https URL that allows CORS; ntfy is polled every 10 s; uptime: no TCP checks |
 Panel link: Chrome / Edge / Opera on Windows,
macOS, ChromeOS and Android (Linux behind a flag), Bluefy on iOS; no Firefox or Safari. Packet size is guessed per
OS and stepped down when refused. Full matrix, CORS notes and test steps: [WEB_APP.md](WEB_APP.md); app by app: [App support in the browser](WEB_APP.md#app-support-in-the-browser).

## Studio browsers

Built with React 19, Tailwind 4 and Vite 8, so the studio needs a browser from 2023 on:

| Browser | Minimum | Notes |
| --- | --- | --- |
| Chrome / Edge (desktop, Android) | 111 | full support; WebGL for the 3D fly view |
| Firefox | 128 | no gamepad rumble (no `vibrationActuator`) |
| Safari macOS / iOS / iPadOS | 16.4 | Tailwind 4 needs `color-mix`, `@property`, cascade layers. iPhone: no element fullscreen (Now Playing uses a full-window overlay instead); iPad < 16.4 uses the prefixed API |
| Android WebView (the DeskDot app) | 111+ (updated via Play) | the app's own studio |

Secure-context limits when the studio is opened over the LAN as plain `http://<host>:8765` (Pi, phone host):
clipboard (falls back to `execCommand`, then "select the address"), gamepads and wake lock may be unavailable.
`localStorage` failures (private mode, storage disabled) are caught everywhere: preferences just don't persist.
3D views need WebGL and show a message when it's off.

## Phone controller (`/p/<code>`)

| | iOS Safari 15+ | Android Chrome | Notes |
| --- | --- | --- | --- |
| Touch d-pad / stick / swipe / tap | ✅ | ✅ | pointer events, `touch-action: none`, pinch-zoom blocked |
| Safe areas (notch, home bar) | ✅ `viewport-fit=cover` + `env(safe-area-inset-*)` | ✅ | |
| Vibration | ❌ (iOS has no `navigator.vibrate`; the toggle says so) | ✅ | |
| Keep screen on | 🟡 only on https pages (the LAN page is http) | 🟡 same | otherwise set the phone's auto-lock |
| Tilt steering | 🟡 https only; asks permission once | 🟡 https only | the option explains when unavailable |
| Gamepad on the phone | 🟡 https only | 🟡 https only | |
| Rotation | ✅ re-layout on resize / orientation change | ✅ | |
| Back/forward cache | ✅ reconnects on `pageshow` | ✅ | |

## Known limits

- macOS, Linux, Raspberry Pi and Android are not yet verified on hardware (Windows is).
- Raspberry Pi Zero 2 W: use the 64-bit OS; 32-bit armv7 lacks wheels for OpenCV / numpy on Python 3.13.
- Wayland hides the focused window from other apps (Active App); screen capture there needs GNOME's tool.
- macOS 15.4+ restricted the private MediaRemote API that `nowplaying-cli` uses: browsers may not show up; Spotify
  and Music always work.
