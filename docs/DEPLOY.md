# Where to run DotDeck

The engine must run on a machine that is **within Bluetooth range of the panel** (~5–10 m) and has
**Bluetooth LE**. Everything else (studio, MCP, scripts) talks to it over HTTP, from any device on your network.

| Host | Works? | Notes |
| --- | --- | --- |
| **Raspberry Pi Zero 2 W / 3 / 4 / 5** | ✅ Recommended | Built-in BLE, ~1–3 W, runs the same code on Linux/BlueZ. One-command install below. |
| Old laptop / mini PC (Windows or Linux) | ✅ | Same as your laptop; set it to never sleep. |
| Your laptop | ✅ | With **hand-off** (below) the panel keeps showing a clock or animation while it sleeps. |
| Spare Android phone (8.0+, 64-bit) | 🧪 New | The **DotDeck Android app** runs the whole engine on the phone as an always-on service — see [android/README.md](../android/README.md). Keep it plugged in. (Termux alone can't use Bluetooth LE.) |
| iPhone | ❌ | iOS suspends background apps; it can't keep the panel's link open. |
| Wi-Fi router | ❌ | No Bluetooth and far too little RAM/CPU on typical routers. |
| Alexa / Google Home | ❌ as a host | Closed platforms. They *can* control DotDeck via Home Assistant (see ROADMAP). |
| ESP32 | ⚠️ Future | Could act as a Wi-Fi→BLE bridge that pulls baked GIFs from a DotDeck server (Tronbyt-style). |

Only **one** device can hold the panel's Bluetooth link. Stop DotDeck on the laptop when the Pi or phone runs it.

## Hand-off: the panel keeps going without a computer

The panel's firmware can run by itself: its **clock keeps time** and it **loops the last GIF** it was given.
DotDeck uses that (Settings → Panel → *When the computer is off*):

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
   scp -r C:\Users\<you>\Downloads\idotmatrix pi@raspberrypi.local:~/dotdeck
   ```
4. On the Pi:
   ```bash
   cd ~/dotdeck && bash scripts/install-pi.sh
   ```
5. Stop DotDeck on the laptop, then open `http://raspberrypi.local:8765` from any device.

The installer adds BlueZ, installs `uv` (which brings its own Python 3.13), installs dependencies, sets
`host = "0.0.0.0"` and `lan_studio = true` so the studio is reachable on the LAN, and registers a `dotdeck` systemd service that starts
at boot, restarts on failure and hands off gracefully on stop. Logs: `journalctl -u dotdeck -f`.

Things that are Windows/macOS-only simply switch off on the Pi: "now playing" media keys, the active-app icon,
OS notifications and screen mirroring (they describe *that* computer). Everything network-based — weather,
sports, stocks, flights, space, radar, the games, pets, clocks — works the same.

## Playing with friends (local Wi-Fi)

Open a multiplayer game in the studio's Play mode and choose **Play with friends**: the panel shows a QR code,
friends on the same Wi-Fi scan it and get a controller on their phone. The first time, Windows asks whether Python
may use the network — choose **private networks**. Only the controller page is reachable from other devices.

## Laptop checklist (if the laptop stays the host)

- Run with `.venv\Scripts\python -m dotdeck serve` and leave the terminal open.
- By default the studio only opens on this laptop (other devices can only reach game controllers). To use the
  studio from your phone too, set `lan_studio = true` in `dotdeck.toml`, allow Python through the Windows firewall,
  and open `http://<laptop-ip>:8765` on the phone. There's no login, so only do this on a network you trust.
