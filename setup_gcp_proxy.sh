#!/usr/bin/env bash
# Set up GCP_us as the public proxy for the mini download page running on
# alicebob (yt_dl_temp.py, tailscale 100.103.88.9:8792). TLS + basic auth
# at the edge; downloads happen at home.
#
# Prerequisites:
#   1. GCP firewall allows tcp 80,443 to this VM
#   2. tailscale installed AND logged in: sudo tailscale up
# Run as root:  sudo bash setup_gcp_proxy.sh
set -euo pipefail

DOMAIN="ytwatcher.duckdns.org"
UPSTREAM="100.103.88.9:8792"
CONF_DIR="/home/justin/yt-dl-proxy"

if [ "$EUID" -ne 0 ]; then
    echo "Run as root: sudo bash $0" >&2
    exit 1
fi

echo "==> upstream check (tailscale must be up)"
if ! curl -q -sf --noproxy '*' --max-time 10 "http://$UPSTREAM/" > /dev/null; then
    echo "http://$UPSTREAM/ unreachable." >&2
    echo "Install + log in tailscale first: curl -fsSL https://tailscale.com/install.sh | sudo sh && sudo tailscale up" >&2
    exit 1
fi

echo "==> install caddy binary"
if [ ! -x /usr/local/bin/caddy ]; then
    URL=$(curl -fsSL https://api.github.com/repos/caddyserver/caddy/releases/latest \
          | grep -o 'https://[^"]*linux_amd64.tar.gz' | head -1)
    [ -n "$URL" ] || { echo "could not resolve caddy release URL" >&2; exit 1; }
    curl -fsSL -o /tmp/caddy.tar.gz "$URL"
    rm -rf /tmp/caddy-extract && mkdir -p /tmp/caddy-extract
    tar -xzf /tmp/caddy.tar.gz -C /tmp/caddy-extract caddy
    install -m 0755 /tmp/caddy-extract/caddy /usr/local/bin/caddy
    rm -rf /tmp/caddy.tar.gz /tmp/caddy-extract /tmp/caddy.zip /tmp/caddy-bin
fi
/usr/local/bin/caddy version

echo "==> Caddyfile"
{
    echo "$DOMAIN {"
    echo -e "\tbasic_auth {"
    while read -r user hash; do
        [ -n "$user" ] && echo -e "\t\t$user $hash"
    done < "$CONF_DIR/.web-users"
    echo -e "\t}"
    echo -e "\tredir /ytwatcher / 308"
    echo -e "\tredir /ytwatcher/ / 308"
    echo -e "\treverse_proxy http://$UPSTREAM"
    echo "}"
} > "$CONF_DIR/Caddyfile"
chown justin:justin "$CONF_DIR/Caddyfile"

echo "==> systemd unit"
cat > /etc/systemd/system/caddy.service <<EOF
[Unit]
Description=Caddy web server (yt-dl proxy)
After=network-online.target tailscaled.service
Wants=network-online.target

[Service]
User=justin
Group=justin
ExecStart=/usr/local/bin/caddy run --config $CONF_DIR/Caddyfile
AmbientCapabilities=CAP_NET_BIND_SERVICE
NoNewPrivileges=true
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable --now caddy

echo
echo "==> verify"
sleep 3
systemctl is-active caddy
curl -sk -o /dev/null -w "local https status: %{http_code}\n" "https://127.0.0.1/" || true
echo
echo "Remaining (manual):"
echo "  1. GCP firewall: allow tcp 80,443 to this VM"
echo "  2. duckdns: point $DOMAIN to this VM's external IP"
