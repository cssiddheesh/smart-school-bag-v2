#!/usr/bin/env bash
# SmartBag - Cloudflare Tunnel installer for Raspberry Pi
# Usage: sudo bash smartbag-tunnel-install.sh
set -euo pipefail

TUNNEL_NAME="smartbag"
HOSTNAME_DEFAULT="api2.cssiddheesh.in"
PORT_DEFAULT="8000"
CF_DIR="/etc/cloudflared"

c_ok="\033[1;32m"; c_info="\033[1;36m"; c_err="\033[1;31m"; c_off="\033[0m"
info() { echo -e "${c_info}==>${c_off} $*"; }
ok()   { echo -e "${c_ok}OK${c_off}  $*"; }
die()  { echo -e "${c_err}ERROR:${c_off} $*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "Run as root:  sudo bash $0"
export HOME=/root

# ---------- uninstall ----------
if [ "${1:-}" = "--uninstall" ]; then
  info "Removing service..."
  cloudflared service uninstall 2>/dev/null || true
  cloudflared tunnel delete -f "$TUNNEL_NAME" 2>/dev/null || true
  rm -rf "$CF_DIR" /root/.cloudflared /usr/local/bin/cloudflared
  ok "Removed. (Delete the CNAME in the Cloudflare dashboard if it remains.)"
  exit 0
fi

ask() { # ask "prompt" default -> echoes answer
  local reply
  read -r -p "$1 [$2]: " reply < /dev/tty
  echo "${reply:-$2}"
}

# ---------- 1. install cloudflared ----------
if ! command -v cloudflared >/dev/null 2>&1; then
  info "Installing cloudflared..."
  case "$(uname -m)" in
    aarch64|arm64)  BIN="cloudflared-linux-arm64" ;;
    armv7l|armv6l)  BIN="cloudflared-linux-arm"   ;;
    x86_64)         BIN="cloudflared-linux-amd64" ;;
    *) die "Unsupported architecture: $(uname -m)" ;;
  esac
  curl -fL --retry 3 -o /usr/local/bin/cloudflared \
    "https://github.com/cloudflare/cloudflared/releases/latest/download/${BIN}"
  chmod +x /usr/local/bin/cloudflared
fi
ok "cloudflared $(cloudflared --version | awk '{print $3}')"

# ---------- 2. questions ----------
HOSTNAME=$(ask "Public hostname for your backend" "$HOSTNAME_DEFAULT")
PORT=$(ask "Local backend port on this Pi" "$PORT_DEFAULT")

# ---------- 3. browser login ----------
if [ ! -f /root/.cloudflared/cert.pem ]; then
  echo
  info "Cloudflare login (browser)."
  echo "    A link will appear below. Open it on ANY device (phone/laptop),"
  echo "    sign in to Cloudflare, and pick the zone: cssiddheesh.in"
  echo
  cloudflared tunnel login
fi
[ -f /root/.cloudflared/cert.pem ] || die "Login failed - cert.pem not found."
ok "Logged in"

# ---------- 4. create tunnel ----------
if cloudflared tunnel list -o json 2>/dev/null | python3 -c \
  "import sys,json; sys.exit(0 if any(t['name']=='$TUNNEL_NAME' for t in (json.load(sys.stdin) or [])) else 1)"; then
  info "Tunnel '$TUNNEL_NAME' already exists, reusing it."
else
  info "Creating tunnel '$TUNNEL_NAME'..."
  cloudflared tunnel create "$TUNNEL_NAME"
fi

TUNNEL_ID=$(cloudflared tunnel list -o json | python3 -c \
  "import sys,json; print(next(t['id'] for t in json.load(sys.stdin) if t['name']=='$TUNNEL_NAME'))")
CRED_SRC="/root/.cloudflared/${TUNNEL_ID}.json"
[ -f "$CRED_SRC" ] || die "Credentials file missing ($CRED_SRC). Run with --uninstall and retry."
ok "Tunnel ID: $TUNNEL_ID"

# ---------- 5. DNS (CNAME -> tunnel) ----------
info "Pointing $HOSTNAME to the tunnel..."
cloudflared tunnel route dns --overwrite-dns "$TUNNEL_NAME" "$HOSTNAME"
ok "CNAME $HOSTNAME -> ${TUNNEL_ID}.cfargotunnel.com"

# ---------- 6. config ----------
mkdir -p "$CF_DIR"
cp "$CRED_SRC" "$CF_DIR/${TUNNEL_ID}.json"
chmod 600 "$CF_DIR/${TUNNEL_ID}.json"

cat > "$CF_DIR/config.yml" <<EOF
tunnel: ${TUNNEL_ID}
credentials-file: ${CF_DIR}/${TUNNEL_ID}.json

ingress:
  - hostname: ${HOSTNAME}
    service: http://localhost:${PORT}
  - service: http_status:404
EOF
cloudflared tunnel ingress validate --config "$CF_DIR/config.yml"
ok "Config written to $CF_DIR/config.yml"

# ---------- 7. systemd service (auto-start on boot) ----------
cloudflared service uninstall >/dev/null 2>&1 || true
cloudflared service install
systemctl enable --now cloudflared
sleep 3
systemctl is-active --quiet cloudflared && ok "cloudflared service running" \
  || die "Service failed. Check: journalctl -u cloudflared -n 50"

cat <<EOF

=====================================================
 DONE
-----------------------------------------------------
 Backend URL : https://${HOSTNAME}
 Forwarding  : -> http://localhost:${PORT} on this Pi

 Next steps:
 1. Start your backend on port ${PORT} (bind 0.0.0.0 or 127.0.0.1).
 2. In your frontend, set the API base to https://${HOSTNAME}
 3. Allow CORS in your backend for:
      https://smartbag.pages.dev
      https://smartbag.cssiddheesh.in

 Useful commands:
   systemctl status cloudflared
   journalctl -u cloudflared -f
   sudo bash $0 --uninstall
=====================================================
EOF
