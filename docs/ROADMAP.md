# Roadmap

Ordered by value ÷ effort. Each item names where it lands in the architecture.

## Headline goal: a fruit-fly brain that plays the apps

Wire DotDeck to the **FlyWire whole-brain connectome** of the adult fruit fly. FlyWire is a Princeton-led
consortium; its AI reconstruction and 3D viewer were built with Google Research. It was published in *Nature* on
2 Oct 2024: 139,255 neurons and about 54.5 million synapses.

The plan, in three parts:

- **Simulation:** run a simplified spiking simulation of the visual → descending-motor pathways.
- **Input:** feed it the panel's 32×32 frame as compound-eye input.
- **Output:** let its motor neurons steer the games (Snake, Flappy, Racer), or interact with any app.

The panel can also show the brain's own activity as it plays. Play against a fly. Sources:
[flywire.ai](https://flywire.ai/), [Nature 634 (8032)](https://www.nature.com/nature/volumes/634/issues/8032).

## Next (v3.2)

- **Lower packet gap** — try 15–20 ms on hardware; would lift photo-frame streaming above 7 fps.
- **Screen Mirror legibility** — region presets (e.g. "watch this rectangle"), edge-enhance mode for text.
- **Pixel-delta path** — for frames that differ by ≤ N pixels, send `pixel` packets instead of a PNG
  (`Device.set_pixels` exists). Enable behind a config flag after verifying on hardware.
- **Lower-case 5×7 glyphs** for more readable lyrics and messages.
- **Night mode** — schedule dimming / screen off (`protocol.eco` or engine-side schedule) in Settings.
- **Studio: playlist item overrides editor** (the API supports per-item settings; the UI shows "+N" only).

## Soon

- **Calendar** app (ICS URL provider): next meeting countdown, take-over 2 min before.
- **Home Assistant / MQTT bridge**: provider + "Entities" app; MQTT topic → notification.
- **GitHub / CI** provider: PR checks, deploy status (token in config).
- **Screensaver set**: upload a native GIF when the PC sleeps/locks so the panel stays alive offline.
- **Pixel editor upgrades**: layers, onion-skin frames → save as GIF to the gallery.

## Later

- Plugin index: install community apps from a URL into `plugins/` with a manifest and version checks.
- Multi-panel walls: several `Device`s composed into 64×32 / 64×64 canvases.
- Linux/macOS media providers (MPRIS / MediaRemote).
- Packaged installer (PyInstaller + tray icon with start/stop and "open studio").

## Done in v3.1

Hardware-verified link layer, Active App, Text Studio, Visualizer, Screen/Camera Mirror with image controls,
Snake, GitHub Graph, Countdown, Scores upgrades + alerts, Autopilot, guarded power switch — see VISION.md.

## Done in v3.0 (the rebuild)

Everything in [VISION.md › What exists](VISION.md#what-exists-v30).
