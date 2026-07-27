#!/usr/bin/env python3
"""One-off: re-download three videos that only had stale .part fragments
left on disk, each into the directory where its fragments were found.
Reuses main.py helpers (cookie retry, state.json, index rebuild)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from main import (
    YT_DLP,
    fetch_upload_timestamp,
    is_video_file,
    load_config,
    log,
    parse_duration_print,
    record_duration,
    record_manual_download,
    run_yt_dlp,
    set_mtime,
)

JOBS = [
    # (video_id, out_dir, format)
    # HTHeGCyNSZc already downloaded OK in the first run (only the index
    # rebuild crashed on a tmp-file race, now fixed in main.py).
    ("DLhRPyGqZwo", "/srv/files/ytwatcher/FoxNews",
     "bestvideo[height<=720]+bestaudio/best[height<=720]"),
    ("PHEAIUbGrrQ", "/srv/files/others/TVShows/Drops.of.God.2023",
     "bestvideo+bestaudio/best"),
]


def main():
    config = load_config()
    settings = config.get("settings", {})
    download_root = Path(settings.get("download_dir", "/srv/files"))
    failed = []
    for vid, out_dir_str, fmt in JOBS:
        out_dir = Path(out_dir_str)
        cmd = [
            YT_DLP,
            "-f", fmt,
            "-o", str(out_dir / "%(title)s [%(id)s].%(ext)s"),
            "--no-playlist",
            "--print", "after_move:%(filepath)s\t%(duration)s",
            f"https://www.youtube.com/watch?v={vid}",
        ]
        log.info("running: %s", " ".join(cmd))
        result = run_yt_dlp(cmd)
        if result.returncode != 0:
            log.error("FAILED %s: %s", vid, result.stderr.strip()[:500])
            failed.append(vid)
            continue
        downloaded = None
        for line in result.stdout.splitlines():
            path = Path(line.rpartition("\t")[0].strip())
            if path.is_file() and path.parent == out_dir and is_video_file(path):
                downloaded = path
        if downloaded is None:
            log.error("yt-dlp exited 0 for %s but the file was not found", vid)
            failed.append(vid)
            continue
        timestamp = fetch_upload_timestamp(vid)
        if timestamp:
            set_mtime(downloaded, timestamp)
        record_duration(download_root, downloaded,
                        parse_duration_print(result.stdout))
        try:
            record_manual_download(vid, settings)
        except Exception:
            # The file is on disk; don't let an index/state hiccup abort
            # the remaining jobs.
            log.exception("post-download recording failed for %s", vid)
        log.info("OK %s -> %s", vid, downloaded)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
