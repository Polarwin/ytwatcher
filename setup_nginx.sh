#!/usr/bin/env bash
# Set up the nginx "homeserver" site:
#   /            -> landing page listing the enabled applications
#   /ytwatcher/  -> downloaded videos (/srv/files, index.html built by main.py)
#   /stockticker/ -> proxy to the stockticker app on 127.0.0.1:8010
# Idempotent: safe to re-run. Re-run after adding a new app to the APPS list.
set -euo pipefail

SITE_NAME="homeserver"
SITE_AVAILABLE="/etc/nginx/sites-available/$SITE_NAME"
SITE_ENABLED="/etc/nginx/sites-enabled/$SITE_NAME"
LANDING_ROOT="/srv/www"
DOWNLOAD_DIR="/srv/files"
STOCKTICKER_PORT=8010

# Apps shown on the landing page: "Name|/path/|description"
APPS=(
    "ytwatcher|/ytwatcher/|Downloaded YouTube subscription videos"
    "stockticker|/stockticker/|Stock ticker dashboard"
)

echo "Setting up nginx site: $SITE_NAME"

# --- Landing page -----------------------------------------------------------
echo "  landing page: $LANDING_ROOT/index.html"
sudo mkdir -p "$LANDING_ROOT"

tmp_index="$(mktemp)"
{
cat <<'HEADER'
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Home Server</title>
  <style>
    :root { color-scheme: dark; }
    body {
      margin: 0;
      font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      background: #121212;
      color: #e0e0e0;
      line-height: 1.5;
    }
    .container { max-width: 700px; margin: 0 auto; padding: 2rem 1rem; }
    h1 { margin: 0 0 1.5rem; font-size: 1.5rem; color: #fff; }
    ul { list-style: none; padding: 0; margin: 0; }
    li { margin-bottom: .75rem; }
    a.app {
      display: block;
      padding: 1rem 1.25rem;
      background: #1e1e1e;
      border: 1px solid #2a2a2a;
      border-radius: 8px;
      color: #8ab4f8;
      text-decoration: none;
      font-size: 1.1rem;
    }
    a.app:hover { background: #262626; border-color: #444; }
    a.app small { display: block; color: #999; font-size: .85rem; margin-top: .15rem; }
  </style>
</head>
<body>
  <div class="container">
    <h1>Home Server</h1>
    <ul>
HEADER
for app in "${APPS[@]}"; do
    IFS='|' read -r name path desc <<< "$app"
    printf '      <li><a class="app" href="%s">%s<small>%s</small></a></li>\n' \
        "$path" "$name" "$desc"
done
cat <<'FOOTER'
    </ul>
  </div>
</body>
</html>
FOOTER
} > "$tmp_index"
sudo mv "$tmp_index" "$LANDING_ROOT/index.html"
sudo chmod 644 "$LANDING_ROOT/index.html"  # mktemp files are 0600; nginx can't read them

# --- nginx site -------------------------------------------------------------
echo "  site config:  $SITE_AVAILABLE"
sudo tee "$SITE_AVAILABLE" > /dev/null <<EOF
server {
    listen 80 default_server;
    listen [::]:80 default_server;
    server_name _;
    charset utf-8;

    root $LANDING_ROOT;
    index index.html;

    location = /ytwatcher {
        return 301 /ytwatcher/;
    }

    location /ytwatcher/ {
        alias $DOWNLOAD_DIR/;
        index index.html;
        autoindex on;
        autoindex_exact_size off;
        autoindex_localtime on;
    }

    location = /stockticker {
        return 301 /stockticker/;
    }

    location /stockticker/ {
        proxy_pass http://127.0.0.1:$STOCKTICKER_PORT/;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Prefix /stockticker;
    }
}
EOF

# Enable this site; disable the old standalone sites it replaces
# (two default_server blocks on port 80 would conflict).
sudo ln -sf "$SITE_AVAILABLE" "$SITE_ENABLED"
for old in fileserver stockticker; do
    if [ -L "/etc/nginx/sites-enabled/$old" ]; then
        echo "  disabling old site: $old (kept in sites-available)"
        sudo rm "/etc/nginx/sites-enabled/$old"
    fi
done

sudo nginx -t
sudo systemctl reload nginx

cat <<EOF

=== done ===
  http://<server-ip>/            landing page
  http://<server-ip>/ytwatcher/  videos ($DOWNLOAD_DIR)
  http://<server-ip>/stockticker/  stockticker app (127.0.0.1:$STOCKTICKER_PORT)

To add another app: edit the APPS list and the site config heredoc in
$(basename "$0"), then re-run it.
EOF
