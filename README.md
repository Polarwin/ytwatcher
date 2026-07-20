# ytwatcher

A small YouTube subscription watcher. It polls subscribed channels for new
videos and downloads the ones that match each subscription's filter using
[yt-dlp](https://github.com/yt-dlp/yt-dlp).

## Requirements

- Python 3.10+
- `yt-dlp`, `PyYAML`, `requests`, and `python-dotenv` (all installed in the project `.venv`)
- `ffmpeg` on PATH (for merging video+audio formats)

## Setup

```bash
python -m venv .venv
.venv/bin/pip install yt-dlp PyYAML requests python-dotenv
```

## Configuration

Edit `subscriptions.yaml`:

- `settings.download_dir` — root directory for downloads; each channel gets
  its own subdirectory (`download_dir/<channel name>/`).
- `settings.check_interval_minutes` — how often to scan in loop mode.
- `settings.recent_videos_to_scan` — how many recent videos per channel to
  inspect each round.
- Each subscription has:
  - `name` — used for logging and the download subdirectory.
  - `url` — channel URL (the `/videos` tab is appended automatically).
  - `match` — `all` to download everything, or a list of keywords; a video
    matches if any keyword appears in its title (case-insensitive).
  - `quality` — yt-dlp format string passed via `-f`.

## Usage

Single test round:

```bash
.venv/bin/python main.py --once
```

Dry run (list new videos and match decisions without downloading or
touching `state.json`):

```bash
.venv/bin/python main.py --scan
```

Continuous watching (scans every `check_interval_minutes`):

```bash
.venv/bin/python main.py
```

Regenerate the download index from existing files without scanning YouTube:

```bash
.venv/bin/python main.py --generate-index
```

## Download index

After any round that completes a download, `main.py` rebuilds
`download_dir/index.html` from the files already on disk. The page groups
videos by channel subfolder, newest first within each group, and links to each
file with a relative path so it works behind nginx. It only rewrites the file
when the listing actually changes, so `index.html` is not touched on rounds
with no new downloads.

## Telegram notifications

Create a `.env` file next to `main.py` with your Telegram credentials:

```bash
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id
```

After each round that completes one or more downloads, a single summary
message is sent to the chat. No messages are sent for skipped or
matched-but-not-downloaded videos. If the credentials are missing, the
watcher prints one warning at startup and continues silently.

Test the notification setup without touching YouTube or `state.json`:

```bash
.venv/bin/python main.py --test-notify
```

## How it works

Each round, for every subscription, the watcher runs
`yt-dlp --flat-playlist` on the channel's `/videos` tab to list the most
recent videos. Video IDs already in `state.json` are skipped. New videos
are marked as seen immediately (even if they don't match or the download
fails) so they are never re-evaluated. Matching videos are downloaded with
the subscription's quality format string. A failure in one channel is
logged and does not abort the round.

`state.json` is created automatically and tracks every video ID ever
scanned. Delete it to re-scan (and re-download) everything.
