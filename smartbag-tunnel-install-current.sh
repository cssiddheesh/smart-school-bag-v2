#!/usr/bin/env bash
# Smart School Bag - Cloudflare Tunnel installer for Raspberry Pi
# Usage: sudo bash smartbag-tunnel-install-current.sh
set -euo pipefail

TUNNEL_NAME="smartbag"
HOSTNAME_DEFAULT="api2.cssiddheesh.in"
PORT_DEFAULT="8000"
CF_DIR="/etc/cloudflared"

c_ok="\033[1;32m"; c_info="\033[1;36m"; c_warn="\033[1;33m"; c_err="\033[1;31m"; c_off="\033[0m"
info() { echo -e "${c_info}==>${c_off} $*"; }
ok()   { echo -e "${c_ok}OK${c_off}  $*"; }
warn() { echo -e "${c_warn}WARN${c_off} $*"; }
die()  { echo -e "${c_err}ERROR:${c_off} $*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "Run as root: sudo bash $0"
export HOME=/root

if [ "${1:-}" = "--uninstall" ]; then
  info "Removing Smart School Bag Cloudflare Tunnel..."
  cloudflared service uninstall 2>/dev/null || true
  cloudflared tunnel delete -f "$TUNNEL_NAME" 2>/dev/null || true
  systemctl disable --now cloudflared 2>/dev/null || true
  rm -rf "$CF_DIR" /root/.cloudflared /usr/local/bin/cloudflared
  ok "Tunnel installation removed."
  warn "Delete any remaining DNS record in Cloudflare if required."
  exit 0
fi

command -v curl >/dev/null 2>&1 || die "curl is required."
command -v python3 >/dev/null 2>&1 || die "python3 is required."

if ! command -v cloudflared >/dev/null 2>&1; then
  info "Installing cloudflared..."
  case "$(uname -m)" in
    aarch64|arm64) BIN="cloudflared-linux-arm64" ;;
    armv7l|armv6l|armhf) BIN="cloudflared-linux-arm" ;;
    x86_64|amd64) BIN="cloudflared-linux-amd64" ;;
    *) die "Unsupported architecture: $(uname -m)" ;;
  esac
  curl -fL --retry 3 -o /usr/local/bin/cloudflared "https://github.com/cloudflare/cloudflared/releases/latest/download/${BIN}"
  chmod +x /usr/local/bin/cloudflared
fi
ok "cloudflared installed: $(cloudflared --version | head -n1)"

ask() { local reply; read -r -p "$1 [$2]: " reply < /dev/tty; echo "${reply:-$2}"; }
HOSTNAME=$(ask "Public hostname for your backend" "$HOSTNAME_DEFAULT")
PORT=$(ask "Local backend port on this Pi" "$PORT_DEFAULT")
[[ "$PORT" =~ ^[0-9]+$ ]] || die "Port must be a number."
[ "$PORT" -ge 1 ] && [ "$PORT" -le 65535 ] || die "Port must be between 1 and 65535."

mkdir -p /root/.cloudflared
chmod 700 /root/.cloudflared
if [ ! -f /root/.cloudflared/cert.pem ]; then
  info "Cloudflare login required. Open the browser link and authorize cssiddheesh.in."
  cloudflared tunnel login
fi
[ -f /root/.cloudflared/cert.pem ] || die "Cloudflare login failed."
ok "Cloudflare login confirmed."

if cloudflared tunnel list -o json 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin) or []; sys.exit(0 if any(t.get('name')=='$TUNNEL_NAME' for t in d) else 1)"; then
  info "Tunnel '$TUNNEL_NAME' already exists; reusing it."
else
  info "Creating tunnel '$TUNNEL_NAME'..."
  cloudflared tunnel create "$TUNNEL_NAME"
fi

TUNNEL_ID="$(cloudflared tunnel list -o json | python3 -c "import sys,json; d=json.load(sys.stdin) or []; print(next(t['id'] for t in d if t.get('name')=='$TUNNEL_NAME'))")"
CRED_SRC="/root/.cloudflared/${TUNNEL_ID}.json"
[ -f "$CRED_SRC" ] || die "Credentials file missing: $CRED_SRC"
ok "Tunnel ID: $TUNNEL_ID"

info "Routing DNS hostname '$HOSTNAME' to the tunnel..."
cloudflared tunnel route dns --overwrite-dns "$TUNNEL_NAME" "$HOSTNAME"
ok "DNS route configured."

mkdir -p "$CF_DIR"
cp "$CRED_SRC" "$CF_DIR/${TUNNEL_ID}.json"
chmod 600 "$CF_DIR/${TUNNEL_ID}.json"

cat > "$CF_DIR/config.yml" <<CFG
 tunnel: ${TUNNEL_ID}
 credentials-file: ${CF_DIR}/${TUNNEL_ID}.json

ingress:
  - hostname: ${HOSTNAME}
    service: http://127.0.0.1:${PORT}
  - service: http_status:404
CFG
sed -i 's/^ //' "$CF_DIR/config.yml"
cloudflared tunnel ingress validate --config "$CF_DIR/config.yml"
ok "Tunnel configuration validated: $CF_DIR/config.yml"

cloudflared service uninstall >/dev/null 2>&1 || true
cloudflared service install
systemctl daemon-reload
systemctl enable --now cloudflared
sleep 3
systemctl is-active --quiet cloudflared || die "Service failed. Check: journalctl -u cloudflared -n 100 --no-pager"
ok "cloudflared service running and enabled at boot."

if curl -fsS --max-time 3 "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1; then
  ok "Backend health check passed locally."
else
  warn "Backend is not responding on http://127.0.0.1:${PORT}/health yet. Start the Smart School Bag backend first."
fi

cat <<SUMMARY

=====================================================
 SMART SCHOOL BAG CLOUDFLARE TUNNEL - DONE
=====================================================

Public API: https://${HOSTNAME}
Tunnel:     ${TUNNEL_NAME}
Tunnel ID:  ${TUNNEL_ID}
Forwarding: https://${HOSTNAME} -> http://127.0.0.1:${PORT}
Config:     ${CF_DIR}/config.yml

Frontend:
  https://smartschoolbag.pages.dev
  https://smartbag.cssiddheesh.in

IMPORTANT:
  This script configures the Cloudflare Tunnel.
  It does NOT start the Smart School Bag backend.

Test after starting the backend:
  curl http://127.0.0.1:${PORT}/health
  curl https://${HOSTNAME}/health

Useful commands:
  systemctl status cloudflared
  journalctl -u cloudflared -f
  cloudflared tunnel list
  cloudflared tunnel info ${TUNNEL_NAME}
  sudo bash $0 --uninstall
=====================================================
SUMMARY
