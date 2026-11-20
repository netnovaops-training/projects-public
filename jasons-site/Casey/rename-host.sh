#!/usr/bin/env bash
# =============================================================================
#  Rename a hostname everywhere on this machine
#
#  Finds every reference to an old hostname in config files, shows you exactly
#  what would change, and only then changes it.
#
#      sudo bash rename-host.sh garden.example.org example.org
#          -> DRY RUN. Shows every file and every line. Changes nothing.
#
#      sudo bash rename-host.sh garden.example.org example.org --apply
#          -> Backs up each file, makes the change, restarts what's affected.
#
#  Every modified file is backed up next to itself as <file>.bak-<timestamp>,
#  and a single rollback script is written that undoes the whole run.
# =============================================================================
set -Eeuo pipefail

OLD="${1:-}"
NEW="${2:-}"
APPLY=false
[[ "${3:-}" == "--apply" || "${3:-}" == "-a" ]] && APPLY=true

BOLD=$'\033[1m'; DIM=$'\033[2m'; GRN=$'\033[32m'; YEL=$'\033[33m'
RED=$'\033[31m'; CYN=$'\033[36m'; OFF=$'\033[0m'

info(){ printf '%s==> %s%s\n' "$CYN" "$*" "$OFF"; }
ok(){   printf '%s  ✓ %s%s\n' "$GRN" "$*" "$OFF"; }
warn(){ printf '%s  ! %s%s\n' "$YEL" "$*" "$OFF"; }
die(){  printf '%s  ✗ %s%s\n' "$RED" "$*" "$OFF" >&2; exit 1; }

[[ -n "$OLD" && -n "$NEW" ]] || die "Usage: sudo bash rename-host.sh OLD.HOST NEW.HOST [--apply]"
[[ $EUID -eq 0 ]] || die "Run with sudo."
[[ "$OLD" != "$NEW" ]] || die "Old and new hostnames are the same."

STAMP="$(date +%Y%m%d-%H%M%S)"
ROLLBACK="/root/rollback-hostname-$STAMP.sh"

echo
printf '%s  %s  ->  %s%s\n' "$BOLD" "$OLD" "$NEW" "$OFF"
$APPLY && printf '%s  APPLYING CHANGES%s\n' "$RED" "$OFF" \
       || printf '%s  DRY RUN — nothing will be changed%s\n' "$YEL" "$OFF"
echo

# --- 1. discover -------------------------------------------------------------
# Overridable so the script can be exercised against a sandbox before it is
# pointed at a live machine.
if [[ -n "${RENAME_SEARCH_DIRS:-}" ]]; then
  read -r -a SEARCH_DIRS <<<"$RENAME_SEARCH_DIRS"
else
  SEARCH_DIRS=(/etc /opt /srv /var/www /usr/local /home /root)
fi
EXISTING_DIRS=()
for d in "${SEARCH_DIRS[@]}"; do [[ -d "$d" ]] && EXISTING_DIRS+=("$d"); done
SEARCH_DIRS=("${EXISTING_DIRS[@]}")
[[ ${#SEARCH_DIRS[@]} -gt 0 ]] || die "None of the search directories exist."
info "Searching for '$OLD'"

mapfile -t FILES < <(
  grep -rIl --binary-files=without-match \
    --exclude="*.bak-*" --exclude="*.log" --exclude="*.log.*" \
    --exclude-dir=.git --exclude-dir=node_modules --exclude-dir=venv \
    --exclude-dir=__pycache__ --exclude-dir=.cache \
    -- "$OLD" "${SEARCH_DIRS[@]}" 2>/dev/null | sort -u || true
)

if [[ ${#FILES[@]} -eq 0 ]]; then
  warn "No files reference '$OLD'."
else
  ok "${#FILES[@]} file(s) reference it:"
  echo
  for f in "${FILES[@]}"; do
    printf '  %s%s%s\n' "$BOLD" "$f" "$OFF"
    grep -n --color=never -- "$OLD" "$f" 2>/dev/null | head -8 | \
      sed "s|^|      |; s|$OLD|${RED}$OLD${OFF}|g"
    local_count=$(grep -c -- "$OLD" "$f" 2>/dev/null || echo 0)
    [[ "$local_count" -gt 8 ]] && printf '      %s… and %s more line(s)%s\n' \
      "$DIM" "$((local_count - 8))" "$OFF"
    echo
  done
fi

# --- 2. things a text search will not find -----------------------------------
info "Checking places that need more than a find-and-replace"

if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  RUNNING="$(docker ps --format '{{.Names}}' 2>/dev/null | tr '\n' ' ' || true)"
  [[ -n "$RUNNING" ]] && warn "Docker containers running: $RUNNING"
  HITS="$(docker ps -aq 2>/dev/null | while read -r id; do
            docker inspect "$id" 2>/dev/null | grep -ql -- "$OLD" && docker inspect \
              --format '{{.Name}}' "$id" 2>/dev/null; done | tr -d '/' | tr '\n' ' ' || true)"
  if [[ -n "${HITS// }" ]]; then
    warn "These containers have '$OLD' baked into their config: $HITS"
    warn "Editing the compose file is not enough — they must be recreated:"
    warn "    docker compose down && docker compose up -d"
  else
    ok "No container configs reference it"
  fi
fi

if [[ -d /var/lib/caddy/.local/share/caddy/certificates ]]; then
  CERTS="$(find /var/lib/caddy/.local/share/caddy/certificates -type d -name "*$OLD*" 2>/dev/null | head -5 || true)"
  [[ -n "$CERTS" ]] && warn "Caddy holds a certificate for $OLD (harmless; it just stops renewing)"
fi

for f in /etc/default/noip-duc /etc/noip2.conf /usr/local/etc/no-ip2.conf; do
  [[ -f "$f" ]] && grep -q -- "$OLD" "$f" 2>/dev/null && \
    warn "Dynamic DNS client points at $OLD ($f) — the new name must exist at No-IP first"
done

grep -q -- "$OLD" /etc/hosts 2>/dev/null && warn "/etc/hosts references it"
echo

# --- 3. apply ----------------------------------------------------------------
if ! $APPLY; then
  cat <<EOF
${YEL}  Nothing was changed.${OFF}

  Read the list above. If it looks right, run it again with --apply:

      sudo bash $0 $OLD $NEW --apply

  ${BOLD}Before you do:${OFF} create ${NEW} in your No-IP account, or the
  certificate will fail to issue and the site will be unreachable.

EOF
  exit 0
fi

[[ ${#FILES[@]} -eq 0 ]] || {
  info "Backing up and replacing"
  printf '#!/usr/bin/env bash\n# Undo the %s -> %s rename\nset -e\n' "$OLD" "$NEW" > "$ROLLBACK"
  for f in "${FILES[@]}"; do
    cp -a -- "$f" "$f.bak-$STAMP"
    printf 'cp -a -- %q %q\n' "$f.bak-$STAMP" "$f" >> "$ROLLBACK"
    sed -i "s|$OLD|$NEW|g" -- "$f"
    ok "$f  ${DIM}(backup: $f.bak-$STAMP)${OFF}"
  done
  printf 'echo "Restored. Now restart: caddy, apache2, momhelp, zeeportal, noip-duc"\n' >> "$ROLLBACK"
  chmod +x "$ROLLBACK"
  echo
  ok "Rollback script: $ROLLBACK"
}

# --- 4. validate before restarting -------------------------------------------
echo
info "Validating configuration"
FAILED=false
if command -v caddy >/dev/null 2>&1 && [[ -f /etc/caddy/Caddyfile ]]; then
  if caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile >/dev/null 2>&1; then
    ok "Caddyfile is valid"
  else
    printf '%s' "$RED"; caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile 2>&1 | head -12
    printf '%s' "$OFF"; FAILED=true
  fi
fi
if command -v apachectl >/dev/null 2>&1; then
  apachectl configtest >/dev/null 2>&1 && ok "Apache config is valid" \
    || { warn "Apache config test failed:"; apachectl configtest 2>&1 | head -8; FAILED=true; }
fi
$FAILED && die "Fix the errors above, or roll back with: sudo bash $ROLLBACK"

# --- 5. restart --------------------------------------------------------------
echo
info "Restarting affected services"
for svc in noip-duc caddy apache2 zeeportal momhelp; do
  systemctl list-unit-files 2>/dev/null | grep -q "^$svc.service" || continue
  systemctl is-enabled --quiet "$svc" 2>/dev/null || systemctl is-active --quiet "$svc" 2>/dev/null || continue
  if systemctl restart "$svc" 2>/dev/null; then
    sleep 1
    systemctl is-active --quiet "$svc" && ok "$svc restarted" || warn "$svc did not come back — journalctl -u $svc -n 30"
  else
    warn "could not restart $svc"
  fi
done

# --- 6. verify ---------------------------------------------------------------
echo
info "Checking the result"
PUB="$(curl -fsS --max-time 10 https://api.ipify.org 2>/dev/null || echo '?')"
RES="$(getent hosts "$NEW" 2>/dev/null | awk '{print $1}' | head -1 || true)"
printf '  public IP           %s\n' "$PUB"
printf '  %s resolves to  %s\n' "$NEW" "${RES:-(not yet)}"
if [[ -n "$RES" && "$RES" == "$PUB" ]]; then
  ok "DNS matches your public IP"
elif [[ -z "$RES" ]]; then
  warn "$NEW does not resolve yet. Create it at noip.com and let the update client run."
else
  warn "DNS points somewhere else. Give it a few minutes, or check the No-IP client."
fi

# Same exclusions as the discovery pass, so backups and logs do not show up as
# "still referencing it" and send you hunting for nothing.
mapfile -t REMAIN < <(
  grep -rIl --binary-files=without-match \
    --exclude="*.bak-*" --exclude="*.log" --exclude="*.log.*" \
    --exclude-dir=.git --exclude-dir=node_modules --exclude-dir=venv \
    --exclude-dir=__pycache__ --exclude-dir=.cache \
    -- "$OLD" "${SEARCH_DIRS[@]}" 2>/dev/null | sort -u || true)
if [[ ${#REMAIN[@]} -eq 0 ]]; then
  ok "No remaining references to $OLD"
else
  warn "${#REMAIN[@]} file(s) still mention $OLD:"
  printf '      %s\n' "${REMAIN[@]}"
fi

cat <<EOF

${BOLD}  Still to do by hand${OFF}

  1. No-IP dashboard: create ${NEW} if you have not, and delete ${OLD}
     if you are finished with it.
  2. If the DDNS client config changed, confirm it is updating the new name:
         sudo journalctl -u noip-duc -n 20
  3. Watch the new certificate get issued (can take a minute):
         sudo journalctl -u caddy -f
  4. Any Docker containers flagged above must be recreated, not just restarted.
  5. Test from a phone on mobile data, not home wi-fi:
         https://${NEW}/

  Rollback if anything is wrong:  sudo bash $ROLLBACK

EOF
