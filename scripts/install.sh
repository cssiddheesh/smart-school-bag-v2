#!/usr/bin/env bash
# Install Smart School Bag as a service on Raspberry Pi OS (run as your normal user, NOT with sudo).
#   ./scripts/install.sh
set -euo pipefail

if [ "$(id -u)" -eq 0 ]; then
  echo "Please run this as your normal user (it uses sudo only where needed)." >&2
  exit 1
fi

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_USER="$(id -un)"
UNIT=/etc/systemd/system/smart-school-bag.service

echo "==> Creating virtual environment in $APP_DIR/.venv"
python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install --upgrade pip >/dev/null
"$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/requirements.txt"

mkdir -p "$APP_DIR/data"

echo "==> Giving $RUN_USER access to USB input/serial devices (if those groups exist)"
for group in input dialout; do
  if getent group "$group" >/dev/null; then sudo usermod -aG "$group" "$RUN_USER"; fi
done

echo "==> Installing systemd service"
sed -e "s|__USER__|$RUN_USER|g" -e "s|__APP_DIR__|$APP_DIR|g" \
    "$APP_DIR/deploy/smart-school-bag.service" | sudo tee "$UNIT" >/dev/null
sudo systemctl daemon-reload
sudo systemctl enable --now smart-school-bag.service

sleep 2
systemctl --no-pager --lines=5 status smart-school-bag.service || true
IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
echo
echo "Smart School Bag is running.  Open:  http://${IP:-<pi-address>}:8000"
echo "Logs:   journalctl -u smart-school-bag -f"
