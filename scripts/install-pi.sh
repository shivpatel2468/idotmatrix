#!/usr/bin/env bash
# Install DotDeck as an always-on service on a Raspberry Pi (or any Debian/Ubuntu box with Bluetooth).
#
#   1. Copy this whole folder to the Pi (web/dist included — the Pi doesn't need Node):
#        scp -r idotmatrix pi@raspberrypi.local:~/dotdeck
#   2. On the Pi:   cd ~/dotdeck && bash scripts/install-pi.sh
#   3. Open http://raspberrypi.local:8765 from any device on your Wi-Fi.
#
# Re-run it after copying a newer version; it's idempotent.
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
USER_NAME="$(id -un)"

echo "==> DotDeck in $APP_DIR (service user: $USER_NAME)"

if [ ! -f "$APP_DIR/web/dist/index.html" ]; then
  echo "!! web/dist is missing. Build the studio on your laptop first (cd web; npm run build) and copy it over."
  exit 1
fi

echo "==> System packages (Bluetooth stack)"
sudo apt-get update -qq
sudo apt-get install -y -qq bluetooth bluez curl ca-certificates >/dev/null
sudo systemctl enable --now bluetooth
# let the service user talk to BlueZ without root
sudo usermod -aG bluetooth "$USER_NAME" || true

echo "==> uv (Python manager) — installs its own Python 3.13, the system Python is untouched"
if ! command -v uv >/dev/null 2>&1 && [ ! -x "$HOME/.local/bin/uv" ]; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
fi
UV="$(command -v uv || echo "$HOME/.local/bin/uv")"

echo "==> Python dependencies"
cd "$APP_DIR"
"$UV" sync --extra mcp --no-dev

echo "==> Config"
if [ ! -f "$APP_DIR/dotdeck.toml" ]; then
  cp "$APP_DIR/dotdeck.example.toml" "$APP_DIR/dotdeck.toml"
fi
# the studio must be reachable from other devices on the LAN
sed -i 's/^host = "127.0.0.1".*/host = "0.0.0.0"      # reachable on the LAN (phone, laptop)/' "$APP_DIR/dotdeck.toml"
# a Pi has no screen of its own: let other devices on the LAN use the studio too (not just game controllers)
if grep -q "^lan_studio" "$APP_DIR/dotdeck.toml"; then
  sed -i 's/^lan_studio = .*/lan_studio = true      # the studio\/API are reachable from other devices on the LAN/' "$APP_DIR/dotdeck.toml"
else
  echo 'lan_studio = true      # the studio/API are reachable from other devices on the LAN' >> "$APP_DIR/dotdeck.toml"
fi

echo "==> systemd service"
sudo tee /etc/systemd/system/dotdeck.service >/dev/null <<UNIT
[Unit]
Description=DotDeck — iDotMatrix panel engine and studio
After=bluetooth.target network-online.target
Wants=bluetooth.target network-online.target

[Service]
Type=simple
User=$USER_NAME
WorkingDirectory=$APP_DIR
ExecStart=$APP_DIR/.venv/bin/python -m dotdeck serve --config $APP_DIR/dotdeck.toml
Restart=always
RestartSec=5
# graceful stop so the engine can hand the panel its clock before disconnecting
KillSignal=SIGINT
TimeoutStopSec=45
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
UNIT
sudo systemctl daemon-reload
sudo systemctl enable dotdeck
sudo systemctl restart dotdeck

IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
echo
echo "DotDeck is running. Open http://$(hostname).local:8765  (or http://$IP:8765)"
echo "Logs:     journalctl -u dotdeck -f"
echo "Restart:  sudo systemctl restart dotdeck"
echo "IMPORTANT: stop DotDeck on your laptop — only one computer may hold the panel's Bluetooth link."
