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
import sys
from pathlib import Path

from main import (
    MANUAL_DEFAULT_FORMAT,
    download_manually,
    load_config,
    log,
    record_manual_download,
)


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
        fmt = MANUAL_DEFAULT_FORMAT

    config = load_config()
    settings = config.get("settings", {})
    out_dir = Path(settings.get("download_dir", "/srv/files")) / "manually"

    downloaded_ids = []
    for url in args.urls:
        result = download_manually(url, out_dir, fmt=fmt, sort=sort)
        if result is None:
            continue
        video_id, _ = result
        record_manual_download(video_id, settings)
        downloaded_ids.append(video_id)
        log.info("done: %s (%s)", url, video_id)

    if not downloaded_ids:
        return 1
    log.info("downloaded %d/%d video(s) into %s",
             len(downloaded_ids), len(args.urls), out_dir)
    return 0 if len(downloaded_ids) == len(args.urls) else 1


if __name__ == "__main__":
    sys.exit(main() or 0)
