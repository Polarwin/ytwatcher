# ytwatcher — Session Log

Date: 2026-07-20

This log covers the work done in this session: adding a downloadable index page, adding Telegram notifications, and refining the index layout.

---

## 1. Feature: `index.html` generation

### What was asked

Generate a single `index.html` in `download_dir` (read from `subscriptions.yaml`, not hardcoded) after every round where any download completed. Requirements:

- Scan `download_dir` recursively (each subscription has its own subfolder).
- Group videos by channel/subfolder, newest-first within each group (by file mtime).
- Each entry links to the video file with a **relative** path, shows filename and file size.
- Header with a "last updated" timestamp.
- Clean inline CSS, dark theme, mobile-friendly.
- Only rewrite `index.html` if something changed.
- Log it: `index.html updated (N videos across M channels)`.
- Run it once now to generate the initial page from existing files.
- Commit and push.

### What was done

- Added `scan_downloads()`, `fingerprint()`, `generate_index_html()`, and `update_index_html()` to `main.py`.
- Integrated index generation:
  - Once at watcher startup, so existing libraries are browseable immediately.
  - After every round that completes one or more downloads.
- Added `--generate-index` CLI flag for on-demand regeneration without scanning YouTube.
- Updated `README.md`.
- Ran `.venv/bin/python main.py --generate-index`, which created `/srv/files/index.html` with 55 videos across 7 channels.
- Committed and pushed.

### Key design decisions

- **Full recursive scan**: `scan_downloads()` uses `Path.rglob("*")` and filters by video extensions, skipping temp/partial files (`*.part`, `*.ytdl`, etc.).
- **Rewrite-on-change only**: A SHA-1 fingerprint of the canonical file listing (path, size, mtime, channel group) is embedded in `index.html`. The file is only rewritten when the fingerprint changes, preserving mtime when nothing changes.
- **Relative links**: HREFs are URL-encoded relative paths from `index.html` to each video, so the page works behind nginx.
- **Top-level grouping**: Each file is grouped by its immediate parent directory under `download_dir` (the subscription subfolder).
- **State handling**: New videos are added to `state.json` immediately when seen, even if they don't match or fail to download, so they are never re-evaluated.

---

## 2. Feature: Telegram notifications

### What was asked

Add Telegram notifications for completed downloads:

- Load `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` from `.env` via `python-dotenv`.
- If missing, print one startup warning and run silently — never crash.
- After each successful download, send one message with channel name, video title, and file size.
- If several videos complete in one round, send **one summary message** instead of spamming.
- Never notify for skipped/matched-but-not-downloaded videos.
- Failed Telegram sends must not kill the round.
- Test with `--test-notify` or by temporarily removing a video ID from `state.json`, verify arrival, restore state.
- Commit and push.

### What was done

- Installed `python-dotenv` in the project `.venv` (`requests` was already present).
- Added `load_telegram_config()`, `send_telegram_message()`, `format_download_notification()`, and `notify_completed_downloads()` to `main.py`.
- Modified `download_video()` to return the downloaded file path, so file size can be read for notifications.
- Modified `process_subscription()` to collect a list of completed download details (channel, title, size) instead of just a count.
- `run_round()` now sends one summary notification after saving state and updating `index.html`.
- Added `--test-notify` flag that sends a sample message and exits without touching YouTube or `state.json`.
- Added `.env` to `.gitignore`.
- Updated `README.md` with Telegram setup instructions.
- Ran `.venv/bin/python main.py --test-notify`; log showed `test notification sent`.
- Committed and pushed.

### Key design decisions

- **One summary per round**: `notify_completed_downloads()` builds a single message for all videos completed in the round, avoiding chat spam.
- **Only completed downloads**: Skipped, members-only, matched-but-not-downloaded, and failed videos are never added to the notification list.
- **Locate file by video ID**: After `yt-dlp` finishes, the downloaded file is found by scanning the output directory for a file whose name contains the video ID and passes the video-file filter.
- **Graceful degradation**: Missing `.env` values trigger exactly one `log.warning` at startup; notification calls return early, and Telegram HTTP errors are caught and logged without affecting the round.
- **Member-only handling**: Videos with availability `subscriber_only`, `premium_only`, or `needs_auth`, or whose stderr contains "member"/"subscriber"/"join this channel", are marked seen and skipped so the round isn't blocked by paywalled content.

---

## 3. Refinement: full-scan confirmation + 🆕 Latest section

### What was asked

1. Confirm `index.html` is rebuilt from a **full recursive scan** every time (not incrementally), so deleted videos disappear automatically. Run a quick test: create a dummy `.mp4`, regenerate, confirm it appears; delete it, regenerate, confirm it's gone.
2. Add a "🆕 Latest" section at the very top with the 10 newest videos across all channels (by mtime), each showing its channel name. Per-channel groups stay below, newest-first.

### What was done

- Confirmed `update_index_html()` always builds from a fresh `scan_downloads()` call.
- Added a `latest` list computed by flattening all entries and sorting by mtime descending, then passed it to `generate_index_html()`.
- Added a `🆕 Latest` section before the per-channel groups; each entry shows `Channel · mtime · size`.
- Ran the dummy-file test:
  ```bash
  touch /srv/files/Tube/dummy_test.mp4
  .venv/bin/python main.py --generate-index   # 56 videos
  grep -c 'dummy_test' /srv/files/index.html  # 2

  rm /srv/files/Tube/dummy_test.mp4
  .venv/bin/python main.py --generate-index   # 55 videos
  grep -c 'dummy_test' /srv/files/index.html  # 0
  ```
- Committed and pushed.

---

## Final architecture

```text
┌─────────────────────────────────────────────────────────────┐
│  User-facing files                                          │
│  - subscriptions.yaml   : channel URLs, filters, quality    │
│  - .env                 : Telegram token/chat ID (optional) │
│  - state.json           : already-seen YouTube video IDs    │
│  - SESSION_LOG.md       : this log                          │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  main.py (YouTube subscription watcher)                     │
│  - loads config + state                                     │
│  - for each subscription, lists recent videos with yt-dlp   │
│  - downloads matches, skips members-only/failures           │
│  - updates state.json                                       │
│  - rebuilds download_dir/index.html from full scan          │
│  - sends one Telegram summary per round (if configured)     │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  download_dir (e.g. /srv/files/)                            │
│  - <channel>/.../<video files>                              │
│  - index.html (auto-generated, relative links)              │
└─────────────────────────────────────────────────────────────┘

Systemd (installed by install_service.sh):
  - ytwatcher.service       : runs `main.py` continuously
  - yt-dlp-update.service   : upgrades yt-dlp in the venv
  - yt-dlp-update.timer     : triggers the upgrade daily at 00:05

After a yt-dlp upgrade, `yt-dlp-update.service` restarts `ytwatcher.service` so the watcher picks up the new binary.
```

### Files and their roles

| File | Role |
|------|------|
| `main.py` | Core watcher: scanning, downloading, index generation, Telegram notifications |
| `subscriptions.yaml` | Channel list, filters, quality settings, `download_dir` |
| `state.json` | Persistent set of already-processed video IDs |
| `.env` | Optional Telegram credentials (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`) |
| `install_service.sh` | Installs `ytwatcher.service` and `yt-dlp-update.timer` |
| `uninstall_service.sh` | Removes the service and timer |
| `yt-dlp-update.service` | One-shot service that upgrades `yt-dlp` and restarts the watcher |
| `yt-dlp-update.timer` | Daily timer at 00:05 for the upgrade service |
| `README.md` | Setup and usage documentation |
| `SESSION_LOG.md` | This session log |

---

## How to operate this

### Edit subscriptions

Edit `subscriptions.yaml`:

```yaml
settings:
  download_dir: /srv/files/
  check_interval_minutes: 30
  recent_videos_to_scan: 10

subscriptions:
  - name: MyChannel
    url: https://www.youtube.com/@MyChannel
    match: all
    quality: "bestvideo[height<=720]+bestaudio/best[height<=720]"
```

Restart the service after changing subscriptions:

```bash
sudo systemctl restart ytwatcher
```

### Add Telegram notifications

Create `.env` next to `main.py`:

```bash
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id
```

Test without touching YouTube or state:

```bash
.venv/bin/python main.py --test-notify
```

Restart the service to pick up `.env` changes:

```bash
sudo systemctl restart ytwatcher
```

### Regenerate the download index on demand

```bash
.venv/bin/python main.py --generate-index
```

This rebuilds `download_dir/index.html` from a full scan.

### View logs

```bash
journalctl -u ytwatcher -f
```

### Dry-run a scan

```bash
.venv/bin/python main.py --scan
```

This lists match decisions without downloading or updating `state.json`.

### Run one round manually

```bash
.venv/bin/python main.py --once
```

### Force re-download of everything

Delete `state.json` and restart the service. **Warning:** this will re-evaluate and likely re-download all matching videos.

### yt-dlp upgrade schedule

The timer runs daily at 00:05:

```bash
systemctl list-timers yt-dlp-update.timer
```

Run an upgrade immediately:

```bash
sudo systemctl start yt-dlp-update.service
```

---

## Commits from this session

- `359188d` — Generate `download_dir/index.html` after downloads
- `7d6e861` — Add Telegram notifications for completed downloads
- `afb0788` — Add 🆕 Latest section and ensure full-scan index rebuilds
- `<this commit>` — Add `SESSION_LOG.md`

---

## 4. Feature: watched marks in `index.html` (2026-07-21)

### What was asked

Mark which videos have been watched and move watched entries to the
bottom of the list.

### What was done

- Added `VIDEO_ID_RE` to extract the YouTube video ID from download
  filenames (`<title> [<id>].<ext>`).
- `entry_lines()` now emits `data-id="<video id>"` on each `<li>` plus a
  "Mark watched" button (entries without an ID in the filename get
  neither).
- Added CSS: watched entries are dimmed and struck through; the button
  turns green and reads "✓ Watched".
- Added an inline `<script>` to the generated page: watched IDs are kept
  in `localStorage` (`ytwatcher:watched`), toggling updates storage and
  re-renders; on load, watched entries in each `<ul>` are moved to the
  bottom while unwatched entries keep their original (newest-first)
  order. Applies independently to the Latest section and each channel.
- Regenerated `/srv/files/index.html` (had to delete it first — the
  fingerprint only covers the file listing, so template changes alone
  don't trigger a rewrite).
- Updated `README.md`.

### Key design decisions

- **Client-side, no backend**: the page is served as a static file by
  nginx, so watched state lives in `localStorage`. It survives index
  rebuilds (keyed by video ID, not filename) but is per-browser and does
  not sync across devices.

---

## 5. Feature: delete watched videos on scan rounds (2026-07-21)

### What was asked

When checking for new videos, delete watched videos both from the index
page and from the hard drive.

### What was done

- Added `watched.json` (gitignored, next to `state.json`) plus
  `load_watched()` / `save_watched()` helpers mirroring the state ones.
- Added a tiny HTTP endpoint (`WatchedHandler` on `ThreadingHTTPServer`,
  daemon thread) started by the watcher loop: `POST /watched` with
  `{"id": ..., "watched": true|false}` updates `watched.json`. Video IDs
  are validated (`[A-Za-z0-9_-]{11}`) and bad requests get a 400.
- The index page's toggle now also POSTs the mark to
  `http://<page-host>:<api_port>/watched` (failures are ignored, so
  `localStorage` still works standalone).
- Added `delete_watched_videos()` and wired it into the start of every
  non-scan round: files whose embedded video ID is in `watched.json` are
  unlinked, then the index is rebuilt so they disappear from the page.
- New settings: `api_host` (default `0.0.0.0`) and `api_port` (default
  `8791`); the port is embedded in the generated page's `fetch()` URL.
- Updated `README.md`, `.gitignore`, `subscriptions.yaml`.

### Key design decisions

- **Client-side marks, server-side file**: the page keeps `localStorage`
  as before, but every toggle also POSTs the video ID to a tiny HTTP
  endpoint (`BaseHTTPRequestHandler` + `ThreadingHTTPServer`, daemon
  thread) embedded in the watcher loop. Marks land in `watched.json`
  (gitignored, next to `state.json`).
- **Deletion at round start**: `run_round()` (non-scan) calls
  `delete_watched_videos()`, which unlinks every video file whose
  embedded `[video id]` appears in `watched.json`, then rebuilds the
  index. Deletion is deferred to the round, so un-marking before the next
  round saves the file.
- **CORS without preflight**: the page POSTs with
  `Content-Type: text/plain` (a CORS-safelisted value); the handler also
  answers `OPTIONS` and sends `Access-Control-Allow-Origin: *`. Endpoint
  is unauthenticated by design — see README for the trust warning.
- **Config**: `settings.api_host` (default `0.0.0.0`) and
  `settings.api_port` (default `8791`) control binding; the port is
  embedded in the generated page's `fetch()` URL.
- Tested: unit-tested deletion (deletes only watched IDs, idempotent)
  and a live API roundtrip on port 18791 (mark/unmark/bad-ID rejection).
- Regenerated `/srv/files/index.html` (delete-then-regenerate again,
  since the fingerprint doesn't cover template changes).
- **Note**: the running `ytwatcher.service` still uses the old code until
  restarted (`sudo systemctl restart ytwatcher`); the API endpoint only
  runs in loop mode, not for `--once` / `--generate-index`.

### Fix: sync toggles across sections

A video appearing in both 🆕 Latest and its channel section only updated
in the list that was clicked, because `apply()` ran per-`<ul>`. The
script now collects each list's `apply()` into `applyFns` and every
toggle calls `applyAll()`, so both copies of a video update together
(style, button text, position). Verified with a node DOM-stub test:
marking in Latest moves/dims the channel copy too, and un-marking from
either section restores both.
