# ytwatcher

A small YouTube subscription watcher. It polls subscribed channels for new
videos and downloads the ones that match each subscription's filter using
[yt-dlp](https://github.com/yt-dlp/yt-dlp).

## Requirements

- Python 3.10+
- `yt-dlp`, `PyYAML`, `requests`, and `python-dotenv` (all installed in the project `.venv`)
- `ffmpeg` on PATH (for merging video+audio formats)
- `deno` on PATH (JavaScript runtime; recent yt-dlp needs it to extract
  some videos). Install to `~/.local/bin` — the service unit adds it to
  PATH:

  ```bash
  mkdir -p ~/.local/bin
  curl -fsSL https://github.com/denoland/deno/releases/latest/download/deno-x86_64-unknown-linux-gnu.zip -o /tmp/deno.zip
  unzip -o /tmp/deno.zip -d ~/.local/bin && rm /tmp/deno.zip
  ```

## Setup

```bash
python -m venv .venv
.venv/bin/pip install yt-dlp PyYAML requests python-dotenv
```

## Configuration

Edit `subscriptions.yaml` (copy `subscriptions.sample.yaml` to get started;
the real file is gitignored):

- `settings.download_dir` — root directory for downloads; each channel gets
  its own subdirectory (`download_dir/<channel name>/`).
- `settings.check_interval_minutes` — how often to scan in loop mode.
- `settings.recent_videos_to_scan` — how many recent videos per channel to
  inspect each round.
- `settings.api_host` / `settings.api_port` — where the watched-mark
  endpoint listens (defaults `0.0.0.0` / `8791`).
- `settings.site_title` — title of the generated `index.html` page, used for
  both `<title>` and `<h1>` (default `Downloads`).
- Each subscription has:
  - `name` — used for logging and the download subdirectory.
  - `url` — channel URL (the `/videos` and `/streams` tabs are appended
    automatically), or a list of channel URLs to combine under one `name`.
  - `match` — `all` to download everything, or a list of keywords; a video
    matches if any keyword appears in its title (case-insensitive).
  - `exclude` — optional list of keywords; a video is skipped if any
    keyword appears in its title (case-insensitive). Takes precedence
    over `match`.
  - `quality` — yt-dlp format string passed via `-f`.
  - `keep_watched` — optional (default `false`); when `true`, files you
    mark as watched are moved into a `watched` subdirectory of the
    channel folder instead of being deleted.

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

Validate `subscriptions.yaml` (exits non-zero and lists the problems if
invalid):

```bash
.venv/bin/python main.py --check
```

## Manual downloads

`manual_download.py` downloads a single video by URL into
`download_dir/manually/`, using the best quality up to 720p by default
(`bestvideo[height<=720]+bestaudio/best[height<=720]`). Override the
quality with `-f` or `-S`, passed through to yt-dlp exactly as-is:

```bash
.venv/bin/python manual_download.py "https://www.youtube.com/watch?v=..."
.venv/bin/python manual_download.py -f "bestvideo+bestaudio/best" URL
.venv/bin/python manual_download.py -S "res:1080" URL
```

The filename carries the YouTube `[id]`, so the entry on the index page
can be marked watched and the file is deleted at the next scan round like
any other download. The video ID is also added to `state.json` so the
watcher never re-downloads it afterwards, and `index.html` is rebuilt
right away.

## Download index

After any round that completes a download, `main.py` rebuilds
`download_dir/index.html` from the files already on disk. The page groups
videos by channel subfolder, newest first within each group, and links to each
file with a relative path so it works behind nginx. It only rewrites the file
when the listing actually changes, so `index.html` is not touched on rounds
with no new downloads.

Each entry has a **Mark watched** button. Watched videos are dimmed,
struck through, and moved to the bottom of their list. The watched state
is kept in the browser's `localStorage` (keyed by the YouTube video ID in
the filename), so it survives index rebuilds.

Manually downloaded videos work too: drop the file anywhere under
`download_dir` and it appears in the index after the next rebuild. Since
its filename has no YouTube `[id]`, it gets a stable pseudo-ID derived
from its path, so it can be marked watched like any other entry. The
pseudo-ID changes if you rename or move the file. Unlike watcher
downloads, manual files are **never auto-deleted** when marked watched —
deletion only applies to files whose filename carries a real YouTube ID.

Every mark is also reported to a small HTTP endpoint embedded in the
watcher (`POST /watched` on `settings.api_port`, default `8791`), which
records the video ID in `watched.json`. At the start of each scan round,
the watcher deletes every downloaded file whose video ID is in
`watched.json`, and the index loses those entries on the next rebuild.
For subscriptions with `keep_watched: true`, the file is moved into a
`watched` subdirectory of the channel folder instead of being deleted;
archived files no longer appear in the index. Because removal only
happens when a round runs, a mark can be undone (un-watch the video)
any time before the next round. If the watcher is down when a mark is
made, the mark stays browser-local only and no removal happens.

The endpoint binds to `settings.api_host` (default `0.0.0.0`) so the
browser can reach it; it has no authentication, so anyone who can reach
the port can mark IDs for deletion. Keep it on a trusted network or set
`api_host: 127.0.0.1` and proxy it through nginx.

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
`yt-dlp --flat-playlist` on the channel's `/videos` and `/streams` tabs
(the latter covers channels that publish as live streams) and merges the
listings. Video IDs already in `state.json` are skipped. Live streams and
upcoming premieres are not marked as seen — they are retried each round
and downloaded only once the stream has ended. Other new videos are
marked as seen immediately (even if they don't match or the download
fails) so they are never re-evaluated. Matching videos are downloaded with
the subscription's quality format string. A failure in one channel is
logged and does not abort the round.

`state.json` is created automatically and tracks every video ID ever
scanned. Delete it to re-scan (and re-download) everything.
