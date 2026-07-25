#!/usr/bin/env python3
"""Manually download a video with yt-dlp into download_dir/manually/.

Defaults to the best quality up to 720p; override with -f/--format or
-S/--format-sort exactly as in yt-dlp. Downloaded video IDs are added to
state.json so the watcher doesn't re-download them, and index.html is
rebuilt so the file shows up immediately. Because the filename carries
the YouTube [id], marking it watched on the index page deletes it at the
next scan round like any other watcher download.
"""

import argparse
import subprocess
import sys
from pathlib import Path

from main import (
    DEFAULT_API_PORT,
    DEFAULT_SITE_TITLE,
    VIDEO_ID_RE,
    YT_DLP,
    fetch_upload_timestamp,
    is_video_file,
    load_config,
    load_state,
    log,
    save_state,
    set_mtime,
    update_index_html,
)

DEFAULT_FORMAT = "bestvideo[height<=720]+bestaudio/best[height<=720]"


def download(url, out_dir, fmt, sort):
    """Download url into out_dir.

    Returns (video_id, file path) on success, else None. The finished
    file's path is taken from yt-dlp's after_move printout — a plain
    "--print id" can't be used here because it implies --skip-download.
    """
    cmd = [
        YT_DLP,
        "--no-playlist",
        "--print", "after_move:filepath",
        "-o", str(out_dir / "%(title)s [%(id)s].%(ext)s"),
    ]
    if fmt:
        cmd += ["-f", fmt]
    if sort:
        cmd += ["-S", sort]
    cmd.append(url)
    log.info("running: %s", " ".join(cmd))
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
    except subprocess.TimeoutExpired:
        log.error("download timed out for %s", url)
        return None
    if result.returncode != 0:
        log.error("download failed for %s:\n%s", url, result.stderr.strip()[:500])
        return None
    downloaded = None
    for line in result.stdout.splitlines():
        path = Path(line.strip())
        if path.is_file() and path.parent == out_dir and is_video_file(path):
            downloaded = path
    if downloaded is None:
        log.error("yt-dlp exited 0 for %s but the file was not found", url)
        return None
    match = VIDEO_ID_RE.search(downloaded.name)
    if not match:
        log.warning("downloaded %s but the filename has no video ID", url)
        return None
    return match.group(1), downloaded


def main():
    parser = argparse.ArgumentParser(
        description="Manually download a video into download_dir/manually/ "
                    "(default: best quality up to 720p)",
    )
    parser.add_argument(
        "-f", "--format", default=None,
        help="yt-dlp format string, passed through as -f (if neither -f "
             "nor -S is given, defaults to best quality up to 720p)",
    )
    parser.add_argument(
        "-S", "--format-sort", default=None,
        help="yt-dlp format sort string, passed through as -S",
    )
    parser.add_argument("urls", nargs="+", help="video URL(s) to download")
    args = parser.parse_args()

    # An explicit -f or -S replaces the built-in default: passing both
    # would make the -f win and silently defeat the user's -S.
    fmt = args.format
    sort = args.format_sort
    if fmt is None and sort is None:
        fmt = DEFAULT_FORMAT

    config = load_config()
    settings = config.get("settings", {})
    download_dir = settings.get("download_dir", "/srv/files")
    out_dir = Path(download_dir) / "manually"
    out_dir.mkdir(parents=True, exist_ok=True)

    seen = load_state()
    downloaded_ids = []
    for url in args.urls:
        result = download(url, out_dir, fmt, sort)
        if result is None:
            continue
        video_id, downloaded = result
        downloaded_ids.append(video_id)
        # Record the ID so the watcher never re-downloads this video,
        # even after the file is deleted via a watched mark.
        seen.add(video_id)
        # Like watcher downloads, the file's date should reflect the
        # YouTube upload time, not the download time.
        timestamp = fetch_upload_timestamp(video_id)
        if timestamp:
            set_mtime(downloaded, timestamp)
        log.info("done: %s (%s)", url, video_id)

    if not downloaded_ids:
        return 1
    save_state(seen)
    update_index_html(
        download_dir,
        api_port=settings.get("api_port", DEFAULT_API_PORT),
        site_title=settings.get("site_title", DEFAULT_SITE_TITLE),
    )
    log.info("downloaded %d/%d video(s) into %s",
             len(downloaded_ids), len(args.urls), out_dir)
    return 0 if len(downloaded_ids) == len(args.urls) else 1


if __name__ == "__main__":
    sys.exit(main() or 0)
