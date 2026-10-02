# Launchers: search and drive DeskDot from anywhere

Three ways to reach the panel without opening the studio. They all search the same things (apps by name,
description, category and setting titles; presets; games; quick actions; studio settings sections) and they all
talk only to the engine's HTTP API. The engine is the one process that owns the Bluetooth link (CLAUDE.md rule 4).

| | Windows | macOS | Linux | Global hotkey | Needs |
| --- | :-: | :-: | :-: | --- | --- |
| [DeskDot Launcher](#deskdot-launcher) | ✅ | ✅ (basic) | ✅ (no hotkey of its own) | Ctrl+Alt+Space | `uv sync --extra launcher` |
| [DeskDot Bar](#deskdot-bar-macos) | — | ✅ native | — | ⌥ Space | build with Swift (or CI artifact) |
| [Raycast extension](#raycast) | ✅ | ✅ | — | whatever you assign in Raycast | Raycast |

What you can find and do:

- **Apps & games**: Enter shows it on the panel, Ctrl/⌘+Enter opens it in the studio (`/#app/<id>`). The preview
  pane plays the app's animated `preview.gif`.
- **Now showing**: the live panel (`/api/frame.png`), refreshed about twice a second while the bar is open.
- **Display menu**: press **Tab** for a grid of every app grouped by category, with animated thumbnails.
- **Presets**: one-tap playlists (every game, chill, dashboard, your own…).
- **Controls**: brightness (←/→ in the bar, or type `b 40`), panel power, next / previous, playlist play / stop,
  dismiss notification, reconnect.
- **The fly**: "Let the fly play" hands the game on the panel to the fruit-fly brain (or starts Fly Brain);
  "Play Snake with the fly" starts a specific game with the fly at the controls. "Give … back to the AI" undoes it.
- **Send to panel**: type `> hello` (or anything that matches nothing) to send it as a notification banner or as
  scrolling text for 30 s.
- **Settings**: "Calibration settings", "Integrations settings"… open the studio's settings sheet at that section.
- **Recent** items come first when the query is empty, and get a boost while you type.

## Studio deep links

The launchers open the studio at a specific place with a hash:

| Link | Opens |
| --- | --- |
| `http://127.0.0.1:8765/#app/clock` | selects the app and shows its settings in the inspector |
| `http://127.0.0.1:8765/#settings/display` | the settings sheet at a section or block: `display`, `panel`, `calibrate`, `transfer`, `alerts`, `notifications`, `integrations`, `playlist`, `autopilot`, `device`, `handoff`, `audio`, `weather` |

(`web/src/lib/deeplink.ts`; the hash is cleared once handled.)

## DeskDot Launcher

A frameless, always-on-top, Spotlight-style window (pywebview) that loads the page the engine serves at
**`GET /launcher`** (the second Vite entry, `web/launcher.html` + `web/src/launcher/`). Works in any browser too:
open <http://127.0.0.1:8765/launcher>.

```powershell
uv sync --extra launcher          # pywebview + pystray (Pillow is already a dependency)
uv run deskdot launcher           # starts it and shows the bar; afterwards Ctrl+Alt+Space toggles it
```

- **Hotkey**: Ctrl+Alt+Space by default. Change it in `deskdot.toml` (or `DESKDOT_LAUNCHER_HOTKEY`):

  ```toml
  launcher_hotkey = "Ctrl+Shift+D"     # modifiers: Ctrl, Alt/Option, Shift, Win/Cmd · keys: A–Z, 0–9, F1–F24, Space, Enter, Tab, `
  ```

  If another app already owns the combination the launcher says so in its log; pick another.
- **Esc** clears the query, a second Esc hides the bar. Clicking anywhere else hides it too.
- **Tray icon** (Windows/Linux): Show · Open studio · Start DeskDot engine (when it's down) · Start with login · Quit.
- **Engine not running?** The bar shows a "Start DeskDot" page: Enter starts `deskdot serve` detached (its output
  goes to `data/engine-launcher.log`), and the bar switches to the search as soon as the engine answers.
- **One instance**: a second `deskdot launcher` just shows the running one. `deskdot launcher --show | --hide |
  --quit` talk to it over 127.0.0.1:8797, so you can bind `deskdot launcher --show` to a desktop shortcut (the
  way to get a hotkey on Linux).
- **Start with login** is **off** until you turn it on, and nothing is written before that:

  ```powershell
  uv run deskdot launcher --autostart on    # Windows: HKCU\Software\Microsoft\Windows\CurrentVersion\Run
                                            # macOS: ~/Library/LaunchAgents/com.deskdot.launcher.plist
                                            # Linux: ~/.config/autostart/deskdot-launcher.desktop
  uv run deskdot launcher --autostart off   # removes it
  ```

  or tick "Start with login" in the tray menu, type "login" in the bar, or set `launcher_autostart = true` in
  `deskdot.toml`. The login item runs `pythonw -m deskdot launcher --background --config <your deskdot.toml>`.
- Other keys: `launcher_url` (default `http://127.0.0.1:<port>`; `DESKDOT_URL` also works).

On **macOS** the same command works (pywebview uses WebKit) with a global hotkey from an AppKit key monitor, which
needs *System Settings → Privacy & Security → Accessibility* for your terminal/Python, and there is no tray icon.
DeskDot Bar is the better Mac experience.

<!-- screenshot: docs/media/launcher-list.png (the bar with "fly snake" typed) -->
<!-- screenshot: docs/media/launcher-grid.png (Tab: the display menu) -->

## DeskDot Bar (macOS)

A native Swift app in [`integrations/macos/DeskDotBar`](../integrations/macos/DeskDotBar) (SwiftUI + AppKit,
macOS 13+). No Dock icon; in the menu bar it shows a **mini live view of the panel** and the current app's name.

- **Click** the item: a bigger live view, brightness slider, previous / play-stop / next / power, **let the fly
  play**, a presets menu, "Search DeskDot…", Open Studio, Settings (engine URL and hotkey) and Quit.
- **⌥ Space** (or ⌃⌥ Space, ⌘⇧ Space, ⌥ D, ⌃⌥ D) opens the **command bar**: a floating, non-activating panel like
  Spotlight's, so the app you were in stays in front. Same search, preview pane, Tab grid, ↵ / ⌘↵, ←/→ brightness
  and Esc as the launcher above. The hotkey uses Carbon's `RegisterEventHotKey`: no Accessibility permission.
- Engine URL defaults to `http://127.0.0.1:8765`; set another one (e.g. a Raspberry Pi running the engine with
  `lan_studio = true`) in Settings.

Build it (Xcode 15+ or the Swift 5.9+ command-line tools):

```bash
cd integrations/macos/DeskDotBar
bash scripts/bundle.sh       # swift build -c release + wraps it in build/DeskDotBar.app (LSUIElement, ad-hoc signed)
open build/DeskDotBar.app    # first launch: right-click → Open (it isn't notarized)
```

or download `DeskDotBar-app` from the **DeskDot Bar (macOS)** GitHub Actions run
(`.github/workflows/macos-bar.yml` builds it on `macos-latest` whenever `integrations/macos/**` changes). To start
it with login: System Settings → General → Login Items → add DeskDot Bar.

Design notes: the command bar follows the pattern of menu-bar utilities such as Vorssaint's Command Bar
(non-activating floating panel, keyboard-first list with a detail pane). That project is GPL-3.0; DeskDot (MIT)
borrows only the idea, no code.

<!-- screenshot: docs/media/deskdot-bar-menu.png -->
<!-- screenshot: docs/media/deskdot-bar-command.png -->

## Raycast

[`integrations/raycast`](../integrations/raycast) is a Raycast extension (TypeScript, `@raycast/api`) for Raycast
on macOS and Windows:

| Command | What it does |
| --- | --- |
| **Search DeskDot Apps** | every app with its animated preview in the detail pane; filter by category. ↵ show on panel · ⌘↵ / Ctrl+↵ open its settings in the studio · ⌘F / Ctrl+F play the game with the fly |
| **DeskDot Controls** | live panel image, next / previous, playlist play / stop, let the fly play, power, brightness (+/−, or pick a level) |
| **DeskDot Presets** | your presets and the built-in ones with their app lists; play or play shuffled |
| **Send to Panel** | a form: message, title, style (banner / full / celebrate / scrolling text), icon, colour, seconds |

```bash
cd integrations/raycast
npm install
npm run dev        # = ray develop: imports it into Raycast and live-reloads
```

Preference: **Engine URL** (default `http://127.0.0.1:8765`). Assign a hotkey to any command in Raycast's
settings (e.g. ⌥ Space for Search DeskDot Apps). To publish to the store, set `author` in `package.json` to your
Raycast username (`ray lint` checks it).

## Troubleshooting

- **"Can't reach the DeskDot engine"**: start it (`uv run deskdot serve`) or check the URL. The launchers never
  talk to the panel directly.
- **The launcher page says it isn't built**: `cd web && npm run build` (the engine serves `web/dist/launcher.html`).
- **Hotkey does nothing**: another app owns it (Windows: the launcher logs "already taken"; DeskDot Bar shows it in
  the menu). Pick another one.
- **From another computer**: the engine only answers the local machine unless `lan_studio = true`.
