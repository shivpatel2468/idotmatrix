# Idea backlog (research 2026-09-27)

Mined from the Tidbyt app catalogue and install ranking, AWTRIX 3, LaMetric, the Home Assistant blueprint
community, Tronbyt, and calm-technology literature. ✅ = built, 🚧 = in progress, ☐ = open.

## Demand signals

- Tidbyt top installs: Weather, Clock, Stocks, Sunrise/Sunset, Baseball, Photo, Moon Phase, Spotify, Crypto,
  Arcade, **Day Night Map**, News, **Google Calendar**, Nyan Cat, Football, Messages, Weather Map, Digital Rain,
  **Fuzzy Clock** (https://discuss.tidbyt.com/t/app-ranking/3333).
- AWTRIX custom apps and indicators (https://github.com/Blueforcer/awtrix3/blob/main/docs/apps.md).
- Home Assistant users mostly push: energy prices, next train, CO₂, calendar, shopping list, countdowns.

## Backlog

| Idea | Status |
| --- | --- |
| On-Air light (webcam/mic in use, any app) | ✅ |
| Status indicators (corner pixels over every app) | ✅ |
| AWTRIX-compatible custom push apps (`POST /api/custom/{name}`) | ✅ |
| ntfy.sh subscription (keyless phone → panel) | ✅ |
| Home Assistant bridge (entity display + inbound REST) | ✅ |
| Eye-break 20-20-20 nudge | ✅ |
| Day/Night world map · Progress bars · Five o'clock somewhere · Visible planets · What to wear · Tides & surf · QR code · Habit tracker · Calendar (ICS) · Novelty loops | ✅ |
| CI radiator · Uptime monitor · OBS status · 3D printer · Plex/Jellyfin · Anki | ✅ |
| Falling Sand CA Sandbox (Hourglass, Volcano, Oasis, Acid, Elemental) | ✅ (`sand.py`) |
| 3D Wolfenstein Raycaster (Textured walls, depth fog, minimap radar) | ✅ (`raycaster.py`) |
| Neuromorphic 1,024-Neuron Living Cortex (Action potentials, spiral waves) | ✅ (`brain.py`) |
| Focus Companion / Productivity Tamagotchi (Pomodoro cycles, lofi desk) | ✅ (`focuspet.py`) |
| Craig Reynolds Boids Swarm (Bioluminescent trails, predator evasion) | ✅ (`boids.py`) |
| 80s Cyberpunk Synthwave Horizon (Perspective road, slotted sun, sports car) | ✅ (`synthwave.py`) |
| Retro 80s 3D/4D Vector Wireframe Engine (4D Tesseract, Icosahedron, Torus) | ✅ (`wireframe.py`) |
| Raspberry Pi service installer | ✅ (`scripts/install-pi.sh`, docs/DEPLOY.md) |
| MQTT (AWTRIX topic schema) | ☐ needs a dependency (paho-mqtt) |
| Discord mute/presence (local RPC) | ☐ needs a free client id |
| Transit departures (transport.rest, TfL, Swiss) | ☐ region-specific |
| Energy / grid carbon ("run the dishwasher now?") | ☐ region-specific (UK/DE keyless) |
| ESP32 Wi-Fi→BLE bridge pulling baked GIFs (Tronbyt model) | ☐ hardware project |
| Android host app (Kotlin; Termux can't do BLE GATT) | ☐ large |
| Alexa / Google voice via Home Assistant | ☐ HA bridge is in — voice via HA routines is now possible |

## Design lessons worth keeping

- Black background, high contrast, few colours; silhouettes carry meaning.
- **Icon + one number** per screen; persistent state in corner indicators, not full-screen interruptions.
- Apps have a lifetime; stale data leaves the rotation instead of showing old numbers.
- Glance beats precision (fuzzy clocks, day maps). Animate on change; stay still when all is normal.
- Novelty loops are hugely popular — ship them as baked clips (smooth, native playback).
