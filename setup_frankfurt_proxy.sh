#!/usr/bin/env bash
# Turn frankfurt into a pure proxy for the mini download page running on
# alicebob. YouTube blocks this VPS's IP, so downloads happen at home;
# duckdns + basic auth + TLS stay here.
#
# Prerequisites on frankfurt:
#   1. box responsive again (reboot via Aliyun console if sshd is hung)
#   2. `sudo tailscale up` completed (browser auth)
# Run as root:  sudo bash setup_frankfurt_proxy.sh
set -euo pipefail

DOMAIN="ytwatcher.duckdns.org"
# Default: the mini app on alicebob via tailscale. For an app running
# locally on this box: UPSTREAM=127.0.0.1:8792 sudo bash $0
UPSTREAM="${UPSTREAM:-100.103.88.9:8792}"
PROJECT_DIR="/home/justin/ytwatcher"
AUTH_USERS_FILE="$PROJECT_DIR/.web-users"

if [ "$EUID" -ne 0 ]; then
    echo "Run as root: sudo bash $0" >&2
    exit 1
fi

echo "==> stop the local ytwatcher (downloads live at home now)"
systemctl disable --now ytwatcher 2>/dev/null || true
systemctl disable --now yt-dlp-update.timer 2>/dev/null || true

echo "==> upstream check"
if curl -s -o /dev/null --max-time 10 "http://$UPSTREAM/"; then
    echo "upstream reachable"
else
    echo "http://$UPSTREAM/ unreachable." >&2
    echo "Start the app first, or fix the UPSTREAM variable." >&2
    exit 1
fi

[ -s "$AUTH_USERS_FILE" ] || { echo "missing $AUTH_USERS_FILE" >&2; exit 1; }

echo "==> Caddy: replace the site block with a pure proxy (keep basic auth)"
TMP_CADDY="$(mktemp)"
awk -v dom="$DOMAIN" '$0 == dom" {" {skip=1; next}
    skip && /^}/ {skip=0; next}
    !skip' /etc/caddy/Caddyfile > "$TMP_CADDY"
{
    echo
    echo "$DOMAIN {"
    echo -e "\tbasic_auth {"
    while read -r user hash; do
        [ -n "$user" ] && echo -e "\t\t$user $hash"
    done < "$AUTH_USERS_FILE"
    echo -e "\t}"
    echo -e "\tredir /ytwatcher / 308"
    echo -e "\tredir /ytwatcher/ / 308"
    echo -e "\treverse_proxy http://$UPSTREAM"
    echo "}"
} >> "$TMP_CADDY"
cp "$TMP_CADDY" /etc/caddy/Caddyfile
rm -f "$TMP_CADDY"
caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
systemctl reload caddy

echo
echo "==> done. Verify from anywhere:"
echo "  curl -u justin:<pw> https://$DOMAIN/"
