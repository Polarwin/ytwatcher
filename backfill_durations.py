#!/usr/bin/env python3
"""Backfill durations.json for already-downloaded media files.

The cache (durations.json) normally records duration and has_video at
download time. Files from before the cache existed (or after a storage
migration) have no entry, so the index cannot show their length and
every scan round re-probes has_video with ffprobe.

For every media file under the download folder whose cache entry is
missing or stale, run ONE ffprobe call (-show_entries
format=duration:stream=codec_type) and store duration, has_video,
size, and birth time, exactly as record_duration would. The index page
picks the new cache entries up automatically: the page fingerprint
covers durations, so index.html is rebuilt at the next round.

Usage:
    .venv/bin/python backfill_durations.py [--dry-run] [--workers 8] [DIR]

DIR defaults to the configured settings.download_dir.
"""
import argparse
import json
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import main  # noqa: E402

log = main.log

_probe_lock = threading.Lock()
_save_counter = 0


def probe(path):
    """One ffprobe call -> (duration_seconds, has_video) or (None, None)."""
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration:stream=codec_type",
        "-of", "json", str(path),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True,
                                timeout=120)
        if result.returncode != 0:
            return None, None
        data = json.loads(result.stdout or "{}")
        duration = data.get("format", {}).get("duration")
        has_video = any(s.get("codec_type") == "video"
                        for s in data.get("streams", []))
        return (int(float(duration)) if duration is not None else None,
                has_video)
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None, None


def backfill_file(path, root, durations, dry_run):
    """Probe one file and update the shared cache dict (caller saves)."""
    global _save_counter
    rel = path.relative_to(root).as_posix()
    try:
        stat = path.stat()
    except OSError:
        return "gone"
    ctime = main._file_creation_time(path)
    cached = durations.get(rel)
    if (cached and cached.get("size") == stat.st_size
            and cached.get("mtime") == ctime and cached.get("duration")):
        return "fresh"
    duration, has_video = (None, None) if dry_run else probe(path)
    if not dry_run and duration is None and has_video is None:
        log.warning("ffprobe failed for %s", rel)
        return "failed"
    entry = {"size": stat.st_size, "mtime": ctime}
    if duration is not None:
        entry["duration"] = duration
    if has_video is not None:
        entry["has_video"] = has_video
    elif cached and cached.get("has_video") is not None:
        entry["has_video"] = cached["has_video"]
    with _probe_lock:
        durations[rel] = entry
        _save_counter += 1
        if _save_counter % 25 == 0:
            main.save_durations(durations)
    return "probed" if not dry_run else "would-probe"


def main_cli():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="list files that would be probed")
    parser.add_argument("--workers", type=int, default=8,
                        help="parallel ffprobe jobs (default: 8)")
    parser.add_argument("dir", nargs="?", default=None,
                        help="folder to scan (default: configured download_dir)")
    args = parser.parse_args()

    if args.dir:
        root = Path(args.dir)
    else:
        cfg = main.load_config()
        root = Path(cfg.get("settings", {}).get("download_dir", "/srv/files"))
    if not root.is_dir():
        sys.exit(f"not a directory: {root}")

    durations = main.load_durations()
    files = [p for p in main.walk_video_files(root)
             if "watched" not in p.relative_to(root).parts[:-1]]
    print(f"{len(files)} media files under {root}", flush=True)

    counts = {}
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for i, status in enumerate(pool.map(
                lambda p: backfill_file(p, root, durations, args.dry_run),
                files), 1):
            counts[status] = counts.get(status, 0) + 1
            if i % 50 == 0 or status in ("failed", "would-probe"):
                print(f"[{i}/{len(files)}] {status}", flush=True)

    if not args.dry_run:
        main.save_durations(durations)
    print("done:", counts)


if __name__ == "__main__":
    main_cli()
