#!/usr/bin/env bash
# Install the mini YouTube download page (yt_dl_temp.py) as a systemd
# service. Idempotent: safe to re-run.
set -euo pipefail

SERVICE_NAME="yt-dl-temp"
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_PYTHON="$PROJECT_DIR/.venv/bin/python"
UNIT_FILE="/etc/systemd/system/$SERVICE_NAME.service"
# Under sudo, $HOME is root's: resolve the invoking user's home so the
# unit's PATH really contains ~/.local/bin (deno lives there).
USER_HOME="$(getent passwd "${SUDO_USER:-$USER}" | cut -d: -f6)"

if [ ! -x "$VENV_PYTHON" ]; then
    echo "ERROR: $VENV_PYTHON not found. Create the venv first." >&2
    exit 1
fi

echo "Installing $SERVICE_NAME..."
sudo tee "$UNIT_FILE" > /dev/null <<EOF
[Unit]
Description=Mini YouTube download page (static/temp, 10-min TTL)
Wants=network-online.target
After=network-online.target

[Service]
Type=simple
# $USER is root under sudo: always run as the invoking user.
User=${SUDO_USER:-$USER}
WorkingDirectory=$PROJECT_DIR
Environment=PYTHONUNBUFFERED=1
Environment=PATH=$USER_HOME/.local/bin:/usr/local/bin:/usr/bin:/bin
# yt-dlp writes its cache under XDG_CACHE_HOME.
Environment=XDG_CACHE_HOME=$PROJECT_DIR/.cache
Environment=YT_TEMP_DIR=/srv/files/static/temp
Environment=YT_TEMP_TTL=600
Environment=YT_TEMP_PORT=8792
ExecStart=$VENV_PYTHON yt_dl_temp.py
Restart=always
RestartSec=10
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ProtectHome=read-only
# No ReadWritePaths hole for /srv/files: systemd's bind mount over the
# NFS automount makes writes fail with EACCES (same reason the main
# ytwatcher unit leaves /srv out — see install_service.sh).
ReadWritePaths=-$PROJECT_DIR

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE_NAME"
sudo systemctl restart "$SERVICE_NAME"

echo
sudo systemctl status "$SERVICE_NAME" --no-pager || true
echo
echo "=== $SERVICE_NAME cheat sheet ==="
echo "  sudo systemctl status $SERVICE_NAME     # status"
echo "  sudo systemctl restart $SERVICE_NAME    # restart (after code edits)"
echo "  journalctl -u $SERVICE_NAME -f          # follow logs"
