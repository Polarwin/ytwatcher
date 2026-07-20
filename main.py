#!/usr/bin/env python3
"""YouTube subscription watcher.

Polls subscribed channels for new videos and downloads the ones that
match each subscription's filter. Configuration lives in
subscriptions.yaml; processed video IDs are tracked in state.json.
"""

import argparse
import json
import logging
import subprocess
import sys
import time
from pathlib import Path

import yaml

CONFIG_FILE = Path(__file__).parent / "subscriptions.yaml"
STATE_FILE = Path(__file__).parent / "state.json"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("ytwatcher")


def load_config():
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_state():
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return set(json.load(f))
        except (json.JSONDecodeError, OSError) as e:
            log.warning("Could not read state.json (%s); starting fresh", e)
    return set()


def save_state(seen):
    tmp = STATE_FILE.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(sorted(seen), f, indent=1)
    tmp.replace(STATE_FILE)


def fetch_recent_videos(channel_url, limit):
    """Return a list of {id, title} for the channel's N most recent videos."""
    videos_url = channel_url.rstrip("/") + "/videos"
    cmd = [
        "yt-dlp",
        "--flat-playlist",
        "--playlist-end", str(limit),
        "--print", "%(id)s\t%(title)s",
        videos_url,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        raise RuntimeError(
            f"yt-dlp exited {result.returncode}: {result.stderr.strip()[:300]}"
        )
    videos = []
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        vid, _, title = line.partition("\t")
        if vid:
            videos.append({"id": vid.strip(), "title": title.strip()})
    return videos


def matches(sub, title):
    match = sub.get("match", "all")
    if match == "all":
        return True
    title_lower = title.lower()
    return any(kw.lower() in title_lower for kw in match)


def download_video(sub, video, download_dir):
    out_dir = Path(download_dir) / sub["name"]
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        "yt-dlp",
        "-f", sub["quality"],
        "-o", str(out_dir / "%(title)s [%(id)s].%(ext)s"),
        "--no-playlist",
        f"https://www.youtube.com/watch?v={video['id']}",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
    if result.returncode != 0:
        log.error(
            "[%s] download FAILED for %s: %s",
            sub["name"], video["id"], result.stderr.strip()[:300],
        )
        return False
    return True


def process_subscription(sub, settings, seen, scan_only=False):
    name = sub["name"]
    limit = settings.get("recent_videos_to_scan", 10)
    try:
        videos = fetch_recent_videos(sub["url"], limit)
    except Exception as e:
        log.error("[%s] failed to list videos: %s", name, e)
        return

    log.info("[%s] scanned %d recent videos", name, len(videos))
    for video in videos:
        if video["id"] in seen:
            log.info("[%s] skipped (already seen): %s", name, video["title"])
            continue
        if not matches(sub, video["title"]):
            log.info("[%s] new, no match: %s", name, video["title"])
            if not scan_only:
                seen.add(video["id"])
            continue
        if scan_only:
            log.info("[%s] new, MATCHED (would download): %s", name, video["title"])
            continue
        # Mark as seen regardless of download outcome so we never
        # re-evaluate this video.
        seen.add(video["id"])
        log.info("[%s] matched: %s", name, video["title"])
        log.info("[%s] downloading: %s", name, video["title"])
        try:
            if download_video(sub, video, settings["download_dir"]):
                log.info("[%s] done: %s", name, video["title"])
        except Exception as e:
            log.error("[%s] download error for %s: %s", name, video["id"], e)


def run_round(config, seen, scan_only=False):
    settings = config.get("settings", {})
    subs = config.get("subscriptions", [])
    mode = "scan-only" if scan_only else "scan"
    log.info("=== %s round started: %d subscriptions ===", mode, len(subs))
    for sub in subs:
        try:
            process_subscription(sub, settings, seen, scan_only=scan_only)
        except Exception as e:
            log.error("[%s] unexpected error: %s", sub.get("name", "?"), e)
    if not scan_only:
        save_state(seen)
    log.info("=== %s round finished ===", mode)


def main():
    parser = argparse.ArgumentParser(description="YouTube subscription watcher")
    parser.add_argument(
        "--once", action="store_true",
        help="run a single scan round and exit",
    )
    parser.add_argument(
        "--scan", action="store_true",
        help="dry run: list new videos and match decisions without "
             "downloading or updating state.json",
    )
    args = parser.parse_args()

    config = load_config()
    interval = config.get("settings", {}).get("check_interval_minutes", 30)

    if args.scan:
        run_round(config, load_state(), scan_only=True)
        return 0

    if args.once:
        run_round(config, load_state())
        return 0

    log.info("starting watcher loop (every %d minutes)", interval)
    while True:
        try:
            run_round(config, load_state())
        except Exception as e:
            log.error("scan round failed: %s", e)
        time.sleep(interval * 60)


if __name__ == "__main__":
    sys.exit(main() or 0)
