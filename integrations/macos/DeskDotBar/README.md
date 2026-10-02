# DeskDot Bar (macOS)

A native menu-bar companion for DeskDot: a mini live view of the panel in the menu bar, quick controls
(brightness, power, next/previous, playlist, presets, "let the fly play") and a Spotlight-style command bar on a
global hotkey (default **⌥ Space**). It only talks to the DeskDot engine's HTTP API (default
`http://127.0.0.1:8765`, configurable in the menu).

```bash
cd integrations/macos/DeskDotBar
bash scripts/bundle.sh       # → build/DeskDotBar.app (needs Xcode 15+ / Swift 5.9+, macOS 13+)
open build/DeskDotBar.app
```

Or `swift run` for development. CI builds it on every change (`.github/workflows/macos-bar.yml`) and uploads
`DeskDotBar.app.zip` as an artifact. The app is ad-hoc signed: the first time, right-click → Open.

See [docs/LAUNCHERS.md](../../../docs/LAUNCHERS.md#deskdot-bar-macos) for the full guide.
