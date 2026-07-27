#!/usr/bin/env python3
"""One-off: re-download two interrupted Slow-Spanish videos at <=480p
into /srv/files/Espanol/Spain/Slow and record them in state.json so the
watcher doesn't fetch them again at 720p. Reuses main.py helpers so the
cookie retry and index rebuild behave exactly like manual_download.py."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from main import (
    YT_DLP,
    VIDEO_ID_RE,
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

OUT_DIR = Path("/srv/files/ytwatcher/Espanol/Spain/Slow")
FORMAT = "bestvideo[height<=480]+bestaudio/best[height<=480]"
VIDEO_IDS = ["4wrt0-tlpiE", "h3YNbFPh0Js"]


def main():
    config = load_config()
    settings = config.get("settings", {})
    download_root = Path(settings.get("download_dir", "/srv/files"))
    failed = []
    for vid in VIDEO_IDS:
        cmd = [
            YT_DLP,
            "-f", FORMAT,
            "-o", str(OUT_DIR / "%(title)s [%(id)s].%(ext)s"),
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
            if path.is_file() and path.parent == OUT_DIR and is_video_file(path):
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
        record_manual_download(vid, settings)
        log.info("OK %s -> %s", vid, downloaded)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
