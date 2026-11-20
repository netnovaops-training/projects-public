#!/usr/bin/env bash
# =============================================================================
#  Career Portal — Raspberry Pi installer
#
#  Run this from the directory that contains it:
#      sudo bash install.sh
#
#  It is safe to run more than once. Re-running upgrades the code and leaves
#  your database, uploads, and drafts alone.
# =============================================================================
set -Eeuo pipefail

APP_USER="zeeportal"
APP_DIR="/opt/zeeportal"
DATA_DIR="/var/lib/zeeportal"
ENV_FILE="/etc/zeeportal.env"
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

c_ok()   { printf '\033[32m  ✓ %s\033[0m\n' "$*"; }
c_info() { printf '\033[36m==> %s\033[0m\n' "$*"; }
c_warn() { printf '\033[33m  ! %s\033[0m\n' "$*"; }
c_err()  { printf '\033[31m  ✗ %s\033[0m\n' "$*" >&2; }
die()    { c_err "$*"; exit 1; }

trap 'c_err "Failed on line $LINENO. Nothing further was changed."' ERR

[[ $EUID -eq 0 ]] || die "Run this with sudo:  sudo bash install.sh"
[[ -f "$SRC_DIR/requirements.txt" ]] || die "Run this from inside the pi/ directory."

# --- 1. gather settings -------------------------------------------------------
ask() {  # ask VAR "Prompt" "default"
  local var="$1" prompt="$2" default="${3:-}" current="${!1:-}" answer
  [[ -n "$current" ]] && { printf -v "$var" '%s' "$current"; return; }
  if [[ -n "$default" ]]; then read -r -p "  $prompt [$default]: " answer || true
  else read -r -p "  $prompt: " answer || true; fi
  printf -v "$var" '%s' "${answer:-$default}"
}

echo
c_info "Settings — press Enter to accept the value in brackets"

ask PUBLIC_HOST     "Public hostname"                 "example.org"
ask DESKTOP_IP      "Desktop LAN IP (the 4070 box)"   ""
ask DESKTOP_MAC     "Desktop wired NIC MAC address"   ""
ask DESKTOP_SSH_USER "Windows username on the desktop" ""
ask OLLAMA_MODEL    "Ollama model tag"                "qwen3.5:9b"
ask IDLE_MIN        "Hibernate desktop after N idle minutes" "20"
ask ADMIN_USER      "Your portal username (admin)"    "jason"
ask SISTER_USER     "Her portal username"             "zanetta"
ask TIMEZONE        "Timezone"                        "America/New_York"

[[ -n "$DESKTOP_IP"  ]] || c_warn "No desktop IP set — you can add it to $ENV_FILE later."
[[ -n "$DESKTOP_MAC" ]] || c_warn "No desktop MAC set — Wake-on-LAN will not work until you add it."

# Derive the broadcast address of the Pi's primary interface.
PI_IFACE="$(ip -4 route show default | awk '{print $5; exit}')"
BROADCAST="$(ip -4 -o addr show dev "$PI_IFACE" 2>/dev/null \
  | awk '{print $6}' | head -1 | awk -F/ '{print $1}' \
  | awk -F. '{print $1"."$2"."$3".255"}')"
BROADCAST="${BROADCAST:-255.255.255.255}"
c_ok "Pi interface $PI_IFACE, broadcast $BROADCAST"

# --- 2. packages --------------------------------------------------------------
c_info "Installing system packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq \
  python3 python3-venv python3-dev build-essential \
  git curl wget ca-certificates \
  etherwake wakeonlan openssh-client \
  debian-keyring debian-archive-keyring apt-transport-https gnupg >/dev/null
c_ok "Base packages installed"

if ! command -v caddy >/dev/null 2>&1; then
  c_info "Installing Caddy"
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
    | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
    | tee /etc/apt/sources.list.d/caddy-stable.list >/dev/null
  apt-get update -qq
  apt-get install -y -qq caddy >/dev/null
fi
c_ok "Caddy $(caddy version | head -1)"

# --- 3. user and directories --------------------------------------------------
if ! id -u "$APP_USER" >/dev/null 2>&1; then
  useradd --system --home-dir "$DATA_DIR" --create-home --shell /usr/sbin/nologin "$APP_USER"
fi
install -d -o "$APP_USER" -g "$APP_USER" -m 750 "$DATA_DIR" "$DATA_DIR/uploads" \
  "$DATA_DIR/outputs" "$DATA_DIR/.ssh"
chmod 700 "$DATA_DIR/.ssh"
c_ok "Service account and data directories ready"

# --- 4. code ------------------------------------------------------------------
c_info "Installing application to $APP_DIR"
install -d -m 755 "$APP_DIR"
rm -rf "$APP_DIR/app"
cp -r "$SRC_DIR/app" "$APP_DIR/"
cp -f "$SRC_DIR/manage.py" "$SRC_DIR/requirements.txt" \
      "$SRC_DIR/test_portal.py" "$SRC_DIR/test_pipeline.py" "$APP_DIR/"
find "$APP_DIR/app" -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null || true

# Knowledge files live in git so you can reset them with a single command.
install -d -m 755 "$APP_DIR/knowledge"
if [[ -d "$SRC_DIR/../knowledge" ]]; then
  cp -f "$SRC_DIR/../knowledge/"*.md "$APP_DIR/knowledge/" 2>/dev/null || true
fi
chown -R root:root "$APP_DIR"
chmod -R a+rX "$APP_DIR"

if [[ ! -d "$APP_DIR/.git" ]]; then
  git -C "$APP_DIR" init -q
  git -C "$APP_DIR" config user.email "portal@localhost"
  git -C "$APP_DIR" config user.name "Career Portal"
fi
printf 'venv/\n__pycache__/\n*.pyc\n' > "$APP_DIR/.gitignore"
git -C "$APP_DIR" add -A >/dev/null 2>&1 || true
git -C "$APP_DIR" commit -qm "Install/update $(date -Iseconds)" >/dev/null 2>&1 || true
c_ok "Code installed and snapshotted in git"

# --- 5. python environment ----------------------------------------------------
c_info "Building the Python environment (this takes a few minutes on a Pi)"
[[ -d "$APP_DIR/venv" ]] || python3 -m venv "$APP_DIR/venv"
"$APP_DIR/venv/bin/pip" install --quiet --upgrade pip wheel
"$APP_DIR/venv/bin/pip" install --quiet -r "$APP_DIR/requirements.txt"
c_ok "Python dependencies installed"

# --- 6. environment file ------------------------------------------------------
if [[ -f "$ENV_FILE" ]]; then
  SECRET="$(grep -E '^ZEE_SECRET_KEY=' "$ENV_FILE" | cut -d= -f2- || true)"
fi
SECRET="${SECRET:-$(python3 -c 'import secrets;print(secrets.token_hex(32))')}"

# Values are quoted so this file is valid both as a systemd EnvironmentFile and
# as something a shell can `source` (ZEE_SITE_NAME contains a space).
cat > "$ENV_FILE" <<EOF
# Career Portal configuration. Edit, then: sudo systemctl restart zeeportal
ZEE_SECRET_KEY="$SECRET"
ZEE_SITE_NAME="Career Portal"
ZEE_PUBLIC_HOST="$PUBLIC_HOST"
ZEE_BASE_DIR="$APP_DIR"
ZEE_DATA_DIR="$DATA_DIR"
ZEE_KNOWLEDGE_DIR="$APP_DIR/knowledge"
ZEE_TIMEZONE="$TIMEZONE"
ZEE_MAX_UPLOAD_MB="512"

# --- the desktop with the GPU ---
ZEE_DESKTOP_IP="$DESKTOP_IP"
ZEE_DESKTOP_MAC="$DESKTOP_MAC"
ZEE_DESKTOP_BROADCAST="$BROADCAST"
ZEE_DESKTOP_SSH_USER="$DESKTOP_SSH_USER"
ZEE_DESKTOP_SSH_KEY="$DATA_DIR/.ssh/id_ed25519"
ZEE_WOL_PORTS="7,9"
ZEE_OLLAMA_PORT="11434"
ZEE_WHISPER_PORT="9000"
ZEE_OLLAMA_MODEL="$OLLAMA_MODEL"
ZEE_OLLAMA_NUM_CTX="32768"

# --- power ---
ZEE_AUTO_WAKE="1"
ZEE_AUTO_SLEEP="1"
ZEE_IDLE_SLEEP_MINUTES="$IDLE_MIN"
ZEE_BOOT_WAIT_SECONDS="300"
EOF
chmod 640 "$ENV_FILE"
chown root:"$APP_USER" "$ENV_FILE"
c_ok "Wrote $ENV_FILE"

# --- 7. ssh key for hibernating the desktop -----------------------------------
if [[ ! -f "$DATA_DIR/.ssh/id_ed25519" ]]; then
  sudo -u "$APP_USER" ssh-keygen -t ed25519 -N "" -q \
    -f "$DATA_DIR/.ssh/id_ed25519" -C "zeeportal@$(hostname)"
  c_ok "Generated an SSH key for the portal"
fi

# --- 8. systemd ---------------------------------------------------------------
install -m 644 "$SRC_DIR/systemd/zeeportal.service" /etc/systemd/system/zeeportal.service
systemctl daemon-reload
systemctl enable --now zeeportal >/dev/null
sleep 3
systemctl is-active --quiet zeeportal \
  && c_ok "Portal service is running" \
  || { c_err "Portal failed to start. Logs:"; journalctl -u zeeportal -n 40 --no-pager; exit 1; }

# --- 9. caddy -----------------------------------------------------------------
c_info "Configuring Caddy for $PUBLIC_HOST"
install -d -m 755 /var/log/caddy && chown caddy:caddy /var/log/caddy
[[ -f /etc/caddy/Caddyfile && ! -f /etc/caddy/Caddyfile.orig ]] \
  && cp /etc/caddy/Caddyfile /etc/caddy/Caddyfile.orig
sed "s/example\.zapto\.org/$PUBLIC_HOST/g" "$SRC_DIR/Caddyfile" > /etc/caddy/Caddyfile
if caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile >/dev/null 2>&1; then
  systemctl reload-or-restart caddy
  c_ok "Caddy configured"
else
  c_warn "Caddyfile did not validate — leaving Caddy alone. Check /etc/caddy/Caddyfile."
fi

# --- 10. management wrapper ---------------------------------------------------
# A wrapper so you never have to remember the venv path or export the config.
# Sourcing the env file needs the quoted values written above.
cat > /usr/local/bin/zeeportal <<WRAP
#!/usr/bin/env bash
set -euo pipefail
set -a; . $ENV_FILE; set +a
cd $APP_DIR
exec $APP_DIR/venv/bin/python $APP_DIR/manage.py "\$@"
WRAP
chmod 755 /usr/local/bin/zeeportal
c_ok "Installed the 'zeeportal' command"

# --- 11. accounts -------------------------------------------------------------
c_info "Creating portal accounts"
run_manage() { sudo -u "$APP_USER" /usr/local/bin/zeeportal "$@"; }

EXISTING="$(run_manage users 2>/dev/null || true)"
if ! grep -q "^$ADMIN_USER " <<<"$EXISTING"; then
  run_manage adduser "$ADMIN_USER" --admin --generate --name "$ADMIN_USER" || \
    c_warn "Could not create $ADMIN_USER — create it later with: sudo -u $APP_USER zeeportal adduser $ADMIN_USER --admin --generate"
fi
if [[ -n "$SISTER_USER" ]] && ! grep -q "^$SISTER_USER " <<<"$EXISTING"; then
  run_manage adduser "$SISTER_USER" --generate --name "$SISTER_USER" || \
    c_warn "Could not create $SISTER_USER — create it later with: sudo -u $APP_USER zeeportal adduser $SISTER_USER --generate"
fi

# --- done ---------------------------------------------------------------------
cat <<EOF

$(c_ok "Install complete")

  Portal (local test):   http://$(hostname -I | awk '{print $1}'):8000  -- via Caddy only
  Portal (public):       https://$PUBLIC_HOST

  Write down the generated passwords printed above. They must be changed at
  first sign-in.

  NEXT STEPS
  ----------
  1. Point $PUBLIC_HOST at your home IP (No-IP) and forward router ports
     80 and 443 to this Pi. Until that is done, HTTPS will not issue.
       sudo bash $SRC_DIR/setup-ddns.sh

  2. Set up the desktop (Wake-on-LAN, Ollama, Whisper) by running
     desktop/setup-desktop.ps1 in an Administrator PowerShell on the 4070 box.

  3. Authorise this Pi to hibernate the desktop. Copy this public key into
     C:\\ProgramData\\ssh\\administrators_authorized_keys on the desktop:

$(cat "$DATA_DIR/.ssh/id_ed25519.pub" 2>/dev/null | sed 's/^/     /')

  USEFUL COMMANDS
  ---------------
    sudo systemctl status zeeportal             service health
    sudo journalctl -u zeeportal -f             live logs
    sudo systemctl restart zeeportal            apply changes to $ENV_FILE

    sudo -u $APP_USER zeeportal status       is the desktop up?
    sudo -u $APP_USER zeeportal wake         wake it now
    sudo -u $APP_USER zeeportal sleep        hibernate it now
    sudo -u $APP_USER zeeportal users        list accounts
    sudo -u $APP_USER zeeportal passwd NAME --generate
    sudo -u $APP_USER zeeportal kb           knowledge base version

    sudo git -C $APP_DIR checkout knowledge/    reset the AI rules

  SELF-TEST
  ---------
    sudo -u $APP_USER $APP_DIR/venv/bin/python $APP_DIR/test_portal.py

EOF
