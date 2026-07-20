#!/usr/bin/env bash
# Remove the ytwatcher systemd service.
set -euo pipefail

SERVICE_NAME="ytwatcher"
UNIT_FILE="/etc/systemd/system/$SERVICE_NAME.service"

echo "Uninstalling $SERVICE_NAME service..."
sudo systemctl stop yt-dlp-update.timer 2>/dev/null || true
sudo systemctl disable yt-dlp-update.timer 2>/dev/null || true
sudo systemctl stop "$SERVICE_NAME" 2>/dev/null || true
sudo systemctl disable "$SERVICE_NAME" 2>/dev/null || true
sudo rm -f "$UNIT_FILE" \
    /etc/systemd/system/yt-dlp-update.service \
    /etc/systemd/system/yt-dlp-update.timer
sudo systemctl daemon-reload

echo "$SERVICE_NAME service and yt-dlp-update timer removed."
