#!/usr/bin/env bash
# Mount //192.168.0.103/Lexar at /srv/files, migrating existing local
# files onto the share first. Persistent via /etc/fstab. Idempotent.
set -euo pipefail

SHARE="//192.168.0.103/Lexar"
MOUNT_POINT="/srv/files"
CREDS_FILE="/etc/samba/lexar.creds"
STAGING="/mnt/lexar-migrate"
MOUNT_OPTS="vers=3.0,iocharset=utf8,uid=$USER,gid=$USER,file_mode=0664,dir_mode=0775,nofail,_netdev"

# --- 1. cifs-utils -------------------------------------------------------
if ! command -v mount.cifs > /dev/null; then
    echo "Installing cifs-utils..."
    sudo apt-get update -qq
    sudo apt-get install -y cifs-utils rsync
fi

# --- 2. credentials ------------------------------------------------------
# AUTH_OPT is either a credentials file or plain guest access.
if [ -f "$CREDS_FILE" ]; then
    AUTH_OPT="credentials=$CREDS_FILE"
else
    read -rp "Samba username (empty = guest): " SMB_USER
    if [ -n "$SMB_USER" ]; then
        sudo mkdir -p "$(dirname "$CREDS_FILE")"
        read -rsp "Samba password: " SMB_PASS; echo
        printf 'username=%s\npassword=%s\n' "$SMB_USER" "$SMB_PASS" | sudo tee "$CREDS_FILE" > /dev/null
        sudo chmod 600 "$CREDS_FILE"
        AUTH_OPT="credentials=$CREDS_FILE"
    else
        AUTH_OPT="guest"
    fi
fi

# --- 3. stop ytwatcher while we shuffle files around ---------------------
YT_WATCHER_WAS_ACTIVE=0
if systemctl is-active --quiet ytwatcher 2>/dev/null; then
    YT_WATCHER_WAS_ACTIVE=1
    echo "Stopping ytwatcher service during migration..."
    sudo systemctl stop ytwatcher
fi

# --- 4. migrate existing local files onto the share ----------------------
if findmnt -rn "$MOUNT_POINT" | grep -q cifs; then
    echo "$MOUNT_POINT is already a cifs mount, skipping migration."
else
    sudo mkdir -p "$MOUNT_POINT" "$STAGING"
    if ! findmnt -rn "$STAGING" > /dev/null; then
        sudo mount -t cifs "$SHARE" "$STAGING" \
            -o "$AUTH_OPT,$MOUNT_OPTS"
    fi

    if [ -n "$(ls -A "$MOUNT_POINT")" ]; then
        echo "Moving existing files from $MOUNT_POINT onto the share..."
        sudo rsync -a --info=progress2 "$MOUNT_POINT"/ "$STAGING"/
        # rsync succeeded (set -e); now remove the local copies
        sudo find "$MOUNT_POINT" -mindepth 1 -delete
    else
        echo "$MOUNT_POINT is empty, nothing to migrate."
    fi

    sudo umount "$STAGING"
    sudo rmdir "$STAGING"
fi

# --- 5. persistent mount via fstab ---------------------------------------
FSTAB_LINE="$SHARE $MOUNT_POINT cifs $AUTH_OPT,$MOUNT_OPTS 0 0"
if ! grep -qF "$SHARE $MOUNT_POINT" /etc/fstab; then
    echo "Adding fstab entry..."
    echo "$FSTAB_LINE" | sudo tee -a /etc/fstab > /dev/null
    sudo systemctl daemon-reload
fi

if ! findmnt -rn "$MOUNT_POINT" > /dev/null; then
    echo "Mounting $MOUNT_POINT..."
    sudo mount "$MOUNT_POINT"
fi

# --- 6. restart ytwatcher -------------------------------------------------
if [ "$YT_WATCHER_WAS_ACTIVE" -eq 1 ]; then
    echo "Restarting ytwatcher service..."
    sudo systemctl start ytwatcher
fi

echo
findmnt "$MOUNT_POINT"
df -h "$MOUNT_POINT" | tail -1
echo "Done. $SHARE is now mounted at $MOUNT_POINT (survives reboot via fstab)."
