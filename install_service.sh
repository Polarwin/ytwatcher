#!/usr/bin/env bash
# Install ytwatcher as a systemd service. Idempotent: safe to re-run.
set -euo pipefail

SERVICE_NAME="ytwatcher"
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_PYTHON="$PROJECT_DIR/.venv/bin/python"
UNIT_FILE="/etc/systemd/system/$SERVICE_NAME.service"

# Download dir from subscriptions.yaml (settings.download_dir), same
# extraction as setup_nginx.sh; needed for the sandbox ReadWritePaths.
DOWNLOAD_DIR=$(grep -E '^[[:space:]]*download_dir:' "$PROJECT_DIR/subscriptions.yaml" \
    | head -1 | sed -E 's/.*download_dir:[[:space:]]*//; s/[[:space:]]*$//; s|/$||')
DOWNLOAD_DIR="${DOWNLOAD_DIR:-/srv/files/ytwatcher}"

if [ ! -x "$VENV_PYTHON" ]; then
    echo "ERROR: $VENV_PYTHON not found. Create the venv first:" >&2
    echo "  python -m venv .venv && .venv/bin/pip install yt-dlp PyYAML" >&2
    exit 1
fi

echo "Installing $SERVICE_NAME service..."
echo "  project: $PROJECT_DIR"
echo "  user:    $USER"

sudo tee "$UNIT_FILE" > /dev/null <<EOF
[Unit]
Description=YouTube subscription watcher
Wants=network-online.target
After=network-online.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$PROJECT_DIR
Environment=PYTHONUNBUFFERED=1
Environment=PATH=$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin
# yt-dlp writes its cache under XDG_CACHE_HOME; with ProtectHome=read-only
# $HOME/.cache would be read-only, so redirect it into the project dir.
Environment=XDG_CACHE_HOME=$PROJECT_DIR/.cache
ExecStart=$VENV_PYTHON main.py
Restart=always
RestartSec=10
# Sandboxing: the service needs write access only to the project dir and
# the download dir; everything else stays read-only.
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ProtectHome=read-only
ReadWritePaths=-$PROJECT_DIR -$DOWNLOAD_DIR

[Install]
WantedBy=multi-user.target
EOF

# Daily yt-dlp upgrade timer (render placeholders in the shipped unit files)
for unit in yt-dlp-update.service yt-dlp-update.timer; do
    sed -e "s|@PROJECT_DIR@|$PROJECT_DIR|g" -e "s|@USER@|$USER|g" \
        "$PROJECT_DIR/$unit" | sudo tee "/etc/systemd/system/$unit" > /dev/null
done

sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE_NAME"
sudo systemctl restart "$SERVICE_NAME"
sudo systemctl enable --now yt-dlp-update.timer

echo
sudo systemctl status "$SERVICE_NAME" --no-pager || true
echo
systemctl list-timers yt-dlp-update.timer --no-pager || true

cat <<EOF

=== $SERVICE_NAME cheat sheet ===
  sudo systemctl status $SERVICE_NAME     # service status
  sudo systemctl restart $SERVICE_NAME    # restart (needed after code updates)
  sudo systemctl stop $SERVICE_NAME       # stop
  sudo systemctl start $SERVICE_NAME      # start
  journalctl -u $SERVICE_NAME -f          # follow logs
  systemctl list-timers yt-dlp-update.timer      # next scheduled yt-dlp upgrade
  sudo systemctl start yt-dlp-update.service     # run an upgrade now
  ./uninstall_service.sh                  # remove the service and timer
EOF
