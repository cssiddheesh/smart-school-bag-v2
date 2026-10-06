#!/usr/bin/env bash
# Set up (on first run) and launch the Smart School Bag backend and Cloudflare Tunnel.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_SERVICE="smart-school-bag.service"
TUNNEL_SERVICE="cloudflared.service"
ENV_FILE="/etc/default/smart-school-bag"
TUNNEL_CONFIG="/etc/cloudflared/config.yml"
LOCAL_PORT_DEFAULT="8000"

info() { printf '==> %s\n' "$*"; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

usage() {
  cat <<'USAGE'
Usage: ./smartbag-launch.sh [start|stop|restart|status]

With no argument (or "start"), prepares and starts the backend and Cloudflare
Tunnel services. The first run may prompt for sudo and Cloudflare authorization.
USAGE
}

require_sudo() {
  command -v sudo >/dev/null 2>&1 || die "sudo is required to manage system services."
  sudo -v || die "Could not obtain sudo permission."
}

sync_backend_port() {
  local port="$1"
  local tmp_file
  tmp_file="$(mktemp)"

  if sudo test -f "$ENV_FILE"; then
    sudo awk '! /^[[:space:]]*PORT[[:space:]]*=/' "$ENV_FILE" > "$tmp_file"
  fi
  printf 'PORT=%s\n' "$port" >> "$tmp_file"
  sudo install -m 0600 "$tmp_file" "$ENV_FILE"
  rm -f "$tmp_file"
}

case "${1:-start}" in
  start)
    if [ "$(id -u)" -eq 0 ]; then
      die "Run this as your normal Pi user, not with sudo."
    fi
    require_sudo

    if [ ! -x "$SCRIPT_DIR/.venv/bin/python" ] || [ ! -f /etc/systemd/system/$APP_SERVICE ]; then
      info "Installing the backend service and Python dependencies..."
      "$SCRIPT_DIR/scripts/install.sh"
    fi

    if ! sudo test -f "$TUNNEL_CONFIG"; then
      if [ ! -t 0 ]; then
        die "Tunnel setup needs an interactive terminal. Run this command directly on the Pi."
      fi
      info "Setting up Cloudflare Tunnel (Cloudflare login may be required)..."
      sudo bash "$SCRIPT_DIR/smartbag-tunnel-install-current.sh"
    fi

    APP_PORT="$(sudo sed -nE 's/^[[:space:]]*service:[[:space:]]*http:\/\/127\.0\.0\.1:([0-9]+)[[:space:]]*$/\1/p' "$TUNNEL_CONFIG" | head -n 1)"
    if ! [[ "$APP_PORT" =~ ^[0-9]+$ ]] || [ "$APP_PORT" -lt 1 ] || [ "$APP_PORT" -gt 65535 ]; then
      die "Could not read a valid backend port from $TUNNEL_CONFIG."
    fi
    sync_backend_port "$APP_PORT"

    info "Starting backend and Cloudflare Tunnel on port $APP_PORT..."
    sudo systemctl enable --now "$APP_SERVICE" "$TUNNEL_SERVICE"
    sudo systemctl restart "$APP_SERVICE"

    for _ in $(seq 1 30); do
      if curl -fsS --max-time 2 "http://127.0.0.1:${APP_PORT}/health" >/dev/null; then
        break
      fi
      sleep 1
    done
    curl -fsS --max-time 5 "http://127.0.0.1:${APP_PORT}/health" >/dev/null \
      || die "The backend did not become healthy. Check: sudo journalctl -u $APP_SERVICE -n 100 --no-pager"

    printf '\nSmart School Bag is running.\n'
    printf 'Local:   http://localhost:%s\n' "$APP_PORT"
    printf 'Website: https://smartbag.cssiddheesh.in\n'
    printf 'API:     https://api2.cssiddheesh.in\n'
    printf 'Logs:    sudo journalctl -u %s -f\n' "$APP_SERVICE"
    printf 'Stop:    %s stop\n' "$0"
    ;;
  stop)
    require_sudo
    sudo systemctl stop "$TUNNEL_SERVICE" "$APP_SERVICE"
    info "Backend and Cloudflare Tunnel stopped."
    ;;
  restart)
    require_sudo
    sudo systemctl restart "$APP_SERVICE" "$TUNNEL_SERVICE"
    info "Backend and Cloudflare Tunnel restarted."
    ;;
  status)
    require_sudo
    sudo systemctl --no-pager --full status "$APP_SERVICE" "$TUNNEL_SERVICE"
    ;;
  -h|--help|help)
    usage
    ;;
  *)
    usage >&2
    exit 2
    ;;
esac
