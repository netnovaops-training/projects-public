#!/usr/bin/env bash
# =============================================================================
#  No-IP Dynamic DNS client (DUC v3) for Raspberry Pi OS
#
#      sudo bash setup-ddns.sh
#
#  Before running: create the free hostname at noip.com (example.org),
#  then go to My Services -> DDNS Keys and create a key. Use the DDNS Key
#  username/password below, NOT your No-IP account login. If your No-IP account
#  uses "Sign in with Google", a DDNS Key is the only option that works.
#
#  IMPORTANT ONGOING TASK: free No-IP hostnames expire every 30 days unless you
#  click the confirmation link they email you. Whitelist noip.com in your mail
#  client. If the site suddenly stops resolving, this is almost always why.
# =============================================================================
set -Eeuo pipefail

c_ok()   { printf '\033[32m  ✓ %s\033[0m\n' "$*"; }
c_info() { printf '\033[36m==> %s\033[0m\n' "$*"; }
c_warn() { printf '\033[33m  ! %s\033[0m\n' "$*"; }
die()    { printf '\033[31m  ✗ %s\033[0m\n' "$*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "Run with sudo:  sudo bash setup-ddns.sh"

ARCH="$(dpkg --print-architecture)"
c_info "Detected architecture: $ARCH"

read -r -p "  Hostname (e.g. example.org): " NOIP_HOST
read -r -p "  DDNS Key username: " NOIP_USER
read -r -s -p "  DDNS Key password: " NOIP_PASS; echo

[[ -n "$NOIP_HOST" && -n "$NOIP_USER" && -n "$NOIP_PASS" ]] || die "All three values are required."

if ! command -v noip-duc >/dev/null 2>&1; then
  c_info "Downloading the No-IP Dynamic Update Client"
  TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
  cd "$TMP"
  # Always fetch "latest" rather than pinning a version -- No-IP's own docs
  # disagree with each other about the current version number.
  wget -q --content-disposition https://www.noip.com/download/linux/latest \
    || die "Download failed. Check internet access on the Pi."
  tar xf ./*.tar.gz
  DEB="$(find . -name "noip-duc_*_${ARCH}.deb" | head -1)"
  [[ -n "$DEB" ]] || die "No .deb found for architecture '$ARCH'. Available: $(find . -name '*.deb' -printf '%f ')"
  apt-get install -y "./${DEB#./}" >/dev/null
  c_ok "Installed $(basename "$DEB")"
else
  c_ok "noip-duc already installed"
fi

cat > /etc/default/noip-duc <<EOF
NOIP_USERNAME=$NOIP_USER
NOIP_PASSWORD=$NOIP_PASS
NOIP_HOSTNAMES=$NOIP_HOST
EOF
chmod 600 /etc/default/noip-duc
c_ok "Wrote /etc/default/noip-duc (permissions 600)"

systemctl daemon-reload
systemctl enable --now noip-duc
sleep 4

if systemctl is-active --quiet noip-duc; then
  c_ok "noip-duc service is running"
else
  c_warn "Service is not active. Recent log:"
  journalctl -u noip-duc -n 25 --no-pager
fi

echo
c_info "Verification"
PUBLIC_IP="$(curl -fsS --max-time 10 https://api.ipify.org || echo '?')"
RESOLVED="$(getent hosts "$NOIP_HOST" | awk '{print $1}' | head -1 || echo '')"
echo "  Your public IP:        ${PUBLIC_IP}"
echo "  $NOIP_HOST resolves to: ${RESOLVED:-(not yet)}"
if [[ -n "$RESOLVED" && "$RESOLVED" == "$PUBLIC_IP" ]]; then
  c_ok "DNS matches your public IP."
else
  c_warn "They don't match yet. DNS can take a few minutes to propagate — re-check with:"
  echo "      getent hosts $NOIP_HOST"
fi

cat <<'EOF'

  STILL TO DO ON THE ROUTER
  -------------------------
  Forward these to this Pi's LAN IP:
      TCP 80   -> Pi   (needed for the Let's Encrypt HTTP challenge)
      TCP 443  -> Pi   (the actual site)

  Give the Pi a static LAN IP or a DHCP reservation first, or the forward will
  break the next time it reboots.

  Do NOT forward 11434 (Ollama), 8080 (Open WebUI), 9000 (Whisper), or 22.
  Ollama in particular has no authentication whatsoever.

  Watch the certificate get issued:
      sudo journalctl -u caddy -f

EOF
