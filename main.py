#!/usr/bin/env python3
"""YouTube subscription watcher.

Polls subscribed channels for new videos and downloads the ones that
match each subscription's filter. Configuration lives in
subscriptions.yaml; processed video IDs are tracked in state.json and
failed-download attempt counts in failed.json.
"""

import argparse
import hashlib
import html
import json
import logging
import os
import re
import subprocess
import sys
import threading
import time
import urllib.parse
import uuid
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import requests
import yaml
from dotenv import load_dotenv

CONFIG_FILE = Path(__file__).parent / "subscriptions.yaml"
STATE_FILE = Path(__file__).parent / "state.json"
WATCHED_FILE = Path(__file__).parent / "watched.json"
FAILED_FILE = Path(__file__).parent / "failed.json"
# Netscape-format cookie export used as a retry when a yt-dlp download
# fails without cookies. Managed via the API (never committed to git).
COOKIES_FILE = Path(__file__).parent / "cookies.txt"
# Duration cache for the index page, keyed by file's relative path and
# validated by size+mtime. Populated at download time from yt-dlp's
# after_move printout; deleting it just loses the durations.
DURATIONS_FILE = Path(__file__).parent / "durations.json"

# Download attempts before a failing video is marked as seen for good.
MAX_DOWNLOAD_ATTEMPTS = 5

# Port for the embedded HTTP API used by the index page (watched marks,
# config editing, manual downloads). Overridable via settings.api_port in
# subscriptions.yaml.
DEFAULT_API_PORT = 8791

# Title shown on the generated index.html page (<title> and <h1>).
# Overridable via settings.site_title in subscriptions.yaml.
DEFAULT_SITE_TITLE = "Downloads"

# Prefer the yt-dlp next to the running interpreter (the project venv);
# systemd units have a minimal PATH where a bare "yt-dlp" won't resolve.
YT_DLP = str(Path(sys.executable).parent / "yt-dlp")
if not Path(YT_DLP).exists():
    YT_DLP = "yt-dlp"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("ytwatcher")

VIDEO_EXTENSIONS = {
    ".mp4", ".webm", ".mkv", ".mov", ".avi", ".flv", ".wmv",
    ".m4v", ".mpg", ".mpeg", ".3gp",
    # Audio-only downloads (subscriptions with an audio format string).
    ".m4a", ".mp3", ".opus", ".ogg", ".aac", ".wav", ".flac",
}
SKIP_SUFFIXES = {
    ".part", ".ytdl", ".tmp", ".temp", ".download", ".crdownload", ".aria2",
}

INDEX_FINGERPRINT_RE = re.compile(r"<!--\s*index-fingerprint:\s*([a-f0-9]{40})\s*-->")

# YouTube video ID embedded in download filenames: "<title> [<id>].<ext>"
VIDEO_ID_RE = re.compile(r"\[([A-Za-z0-9_-]{11})\]")


def entry_id(entry):
    """Stable watch-mark ID for an index entry.

    Files downloaded by the watcher carry their YouTube ID in the name.
    Manually added files get a pseudo-ID derived from their path
    ("m" + 10 hex chars, matching the 11-char ID shape the API accepts),
    so they can be marked watched too. The pseudo-ID changes if the file
    is renamed or moved.
    """
    match = VIDEO_ID_RE.search(entry["name"])
    if match:
        return match.group(1)
    digest = hashlib.sha1(entry["rel"].encode("utf-8")).hexdigest()
    return "m" + digest[:10]


def validate_config(config):
    """Check the structure of subscriptions.yaml.

    Returns a list of problems found; empty means the config is valid.
    """
    problems = []
    if not isinstance(config, dict):
        return ["top level must be a mapping with 'settings' and 'subscriptions'"]

    settings = config.get("settings", {})
    if not isinstance(settings, dict):
        problems.append("settings: must be a mapping")
    else:
        for key in ("check_interval_minutes", "recent_videos_to_scan",
                    "api_port", "max_video_age_days", "watchlist_max_age_days"):
            if key in settings and not isinstance(settings[key], (int, float)):
                problems.append(f"settings.{key}: must be a number")

    subs = config.get("subscriptions", [])
    if not isinstance(subs, list):
        problems.append("subscriptions: must be a list")
        return problems
    for i, sub in enumerate(subs):
        label = f"subscriptions[{i}]"
        if not isinstance(sub, dict):
            problems.append(f"{label}: must be a mapping")
            continue
        name = sub.get("name")
        if isinstance(name, str) and name.strip():
            label = f"subscription '{name}'"
        else:
            problems.append(f"{label}: missing or empty 'name'")
        url = sub.get("url")
        if isinstance(url, str):
            if not url.strip():
                problems.append(f"{label}: missing or empty 'url'")
        elif not (
            isinstance(url, list) and url
            and all(isinstance(u, str) and u.strip() for u in url)
        ):
            problems.append(
                f"{label}: 'url' must be a non-empty string or a list of URLs"
            )
        if not isinstance(sub.get("quality"), str) or not sub.get("quality", "").strip():
            problems.append(f"{label}: missing or empty 'quality'")
        match = sub.get("match", "all")
        if match != "all" and not (
            isinstance(match, list) and all(isinstance(kw, str) for kw in match)
        ):
            problems.append(f"{label}: 'match' must be 'all' or a list of keywords")
        watchlist = sub.get("match_watchlist")
        if watchlist is not None and not (
            isinstance(watchlist, str)
            or (isinstance(watchlist, list)
                and all(isinstance(p, str) for p in watchlist))
        ):
            problems.append(
                f"{label}: 'match_watchlist' must be a file path or a list of paths"
            )
        exclude = sub.get("exclude", [])
        if not (isinstance(exclude, list)
                and all(isinstance(kw, str) for kw in exclude)):
            problems.append(f"{label}: 'exclude' must be a list of keywords")
        if "shorts_max_duration" in sub and not isinstance(
            sub["shorts_max_duration"], (int, float)
        ):
            problems.append(f"{label}: 'shorts_max_duration' must be a number")
        if "keep_watched" in sub and not isinstance(sub["keep_watched"], bool):
            problems.append(f"{label}: 'keep_watched' must be true or false")
    return problems


def load_config():
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    for problem in validate_config(config):
        log.error("%s: %s", CONFIG_FILE.name, problem)
    return config


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


def load_failed():
    """Return {video_id: failed download attempts}."""
    if FAILED_FILE.exists():
        try:
            with open(FAILED_FILE, "r", encoding="utf-8") as f:
                return {k: int(v) for k, v in json.load(f).items()}
        except (json.JSONDecodeError, OSError, ValueError, TypeError) as e:
            log.warning("Could not read failed.json (%s); starting fresh", e)
    return {}


def save_failed(failed):
    tmp = FAILED_FILE.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(dict(sorted(failed.items())), f, indent=1)
    tmp.replace(FAILED_FILE)


def note_download_failure(name, video, failed, seen):
    """Record a failed download attempt for a video.

    Un-marks the video so the next round retries it. Once it has failed
    MAX_DOWNLOAD_ATTEMPTS times it stays marked as seen, so videos that
    will never download (region locks, takedowns, ...) stop being
    retried every round.
    """
    attempts = failed.get(video["id"], 0) + 1
    if attempts >= MAX_DOWNLOAD_ATTEMPTS:
        failed.pop(video["id"], None)
        log.warning("[%s] giving up on %s after %d failed attempts",
                    name, video["title"], attempts)
        return
    failed[video["id"]] = attempts
    seen.discard(video["id"])
    log.info("[%s] download failed (attempt %d/%d), will retry: %s",
             name, attempts, MAX_DOWNLOAD_ATTEMPTS, video["title"])


_watched_lock = threading.Lock()

# Guards load_state/save_state: besides the watcher loop, manual download
# jobs (CLI or API) also record their video IDs in state.json.
_state_lock = threading.Lock()

# Quality presets for the manual-download API endpoint. Raw format strings
# are not accepted over the network — the endpoint is unauthenticated, so
# keep the surface to these fixed choices.
MANUAL_QUALITY_PRESETS = {
    "720": "bestvideo[height<=720]+bestaudio/best[height<=720]",
    "best": "bestvideo+bestaudio/best",
    "audio": "bestaudio",
}

# Default format for manual_download.py when neither -f nor -S is given.
MANUAL_DEFAULT_FORMAT = MANUAL_QUALITY_PRESETS["720"]

# In-memory status of recent manual download jobs started via the API.
MAX_DOWNLOAD_JOBS = 20
_download_jobs = {}
_download_jobs_lock = threading.Lock()


def load_watched():
    """Return the set of video IDs the user marked as watched."""
    if WATCHED_FILE.exists():
        try:
            with open(WATCHED_FILE, "r", encoding="utf-8") as f:
                return set(json.load(f))
        except (json.JSONDecodeError, OSError) as e:
            log.warning("Could not read watched.json (%s); starting fresh", e)
    return set()


def save_watched(watched):
    tmp = WATCHED_FILE.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(sorted(watched), f, indent=1)
    tmp.replace(WATCHED_FILE)


def fetch_recent_videos(channel_url, limit):
    """Return a list of {id, title, availability, duration, live_status,
    timestamp} for the channel's N most recent videos. duration is seconds
    (int) or None; timestamp is the upload time as a unix timestamp (int)
    or None.

    Both the channel's Videos tab and its Live tab are scanned and merged:
    some channels publish their main content as live streams, which only
    appear under /streams, never under /videos.
    """
    base = channel_url.rstrip("/")
    videos = []
    seen_ids = set()
    errors = []
    for tab in ("videos", "streams"):
        cmd = [
            YT_DLP,
            "--flat-playlist",
            "--playlist-end", str(limit),
            "--print", "%(id)s\t%(title)s\t%(availability)s\t%(duration)s\t%(live_status)s\t%(timestamp)s\t%(upload_date)s",
            f"{base}/{tab}",
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        except subprocess.TimeoutExpired as e:
            errors.append(f"{tab}: {e}")
            continue
        if result.returncode != 0:
            errors.append(f"{tab}: yt-dlp exited {result.returncode}: "
                          f"{result.stderr.strip()[:300]}")
            continue
        for video in parse_flat_playlist(result.stdout):
            if video["id"] not in seen_ids:
                seen_ids.add(video["id"])
                videos.append(video)
    if not videos and errors:
        raise RuntimeError("; ".join(errors))
    if errors:
        log.warning("partial channel listing for %s: %s", channel_url, "; ".join(errors))
    return videos


def parse_flat_playlist(stdout):
    """Parse yt-dlp --flat-playlist output into video dicts."""
    videos = []
    for line in stdout.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        vid = parts[0].strip()
        if not vid:
            continue
        duration = None
        if len(parts) > 3:
            try:
                duration = int(float(parts[3]))
            except ValueError:
                duration = None
        timestamp = None
        if len(parts) > 5:
            try:
                timestamp = int(float(parts[5]))
            except ValueError:
                timestamp = None
        if timestamp is None and len(parts) > 6:
            # Fall back to upload_date (YYYYMMDD) when no exact timestamp.
            try:
                timestamp = int(
                    datetime.strptime(parts[6].strip(), "%Y%m%d").timestamp()
                )
            except ValueError:
                timestamp = None
        videos.append({
            "id": vid,
            "title": parts[1].strip() if len(parts) > 1 else "",
            "availability": parts[2].strip() if len(parts) > 2 else "",
            "duration": duration,
            "live_status": parts[4].strip() if len(parts) > 4 else "",
            "timestamp": timestamp,
        })
    return videos


# yt-dlp availability values that mean "not watchable without membership"
MEMBERS_ONLY_AVAILABILITY = {"subscriber_only", "premium_only", "needs_auth"}

# stderr fragments yt-dlp prints when a video requires channel membership
MEMBERS_ONLY_ERROR_HINTS = ("member", "subscriber", "join this channel")

# stderr fragments that mean a download failed for auth reasons — the
# sign that cookies.txt is missing, empty, or expired.
AUTH_ERROR_HINTS = ("sign in", "not a bot", "netscape format cookies")

# yt-dlp live_status values that mean "stream hasn't ended yet" — wait and
# retry in a later round instead of marking the video as seen.
LIVE_PENDING_STATUSES = {"is_live", "is_upcoming"}

# stderr fragments yt-dlp prints when a download fails because the stream
# is still live (safety net for when flat-playlist lacks live_status)
LIVE_ERROR_HINTS = ("live event", "is currently live", "this live stream", "premieres in")


def is_members_only_error(stderr):
    text = stderr.lower()
    return any(hint in text for hint in MEMBERS_ONLY_ERROR_HINTS)


def is_live_error(stderr):
    text = stderr.lower()
    return any(hint in text for hint in LIVE_ERROR_HINTS)


_watchlist_cache = {}  # path -> (mtime, [(ticker, compiled regex)])


def load_watchlist_tickers(path):
    """Load match keywords from a watchlist file (one per line, '#'
    comments), each matched as a whole word — meant for stock tickers,
    where substring matching would false-positive (TER in "Wetter",
    MU in "music", ...). Cached by file mtime: the dynamic watchlist
    is re-read only when it changes.
    """
    try:
        mtime = os.path.getmtime(path)
    except OSError as e:
        log.warning("match_watchlist file not readable: %s (%s)", path, e)
        return []
    cached = _watchlist_cache.get(path)
    if cached and cached[0] == mtime:
        return cached[1]
    tickers = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                ticker = line.strip()
                if not ticker or ticker.startswith("#"):
                    continue
                tickers.append(ticker.lstrip("^"))
    except OSError as e:
        log.warning("could not read match_watchlist %s: %s", path, e)
        return []
    compiled = [
        (t, re.compile(r"(?<![A-Za-z0-9])" + re.escape(t) + r"(?![A-Za-z0-9])",
                       re.IGNORECASE))
        for t in tickers
    ]
    _watchlist_cache[path] = (mtime, compiled)
    log.info("loaded %d watchlist keyword(s) from %s", len(compiled), path)
    return compiled


def matches_keywords(sub, text, include_watchlist=True):
    """Return True if text contains any of the subscription's match keywords.

    A subscription with match: all (or no match list) matches everything.
    Keywords from match_watchlist files match as whole words; they are
    skipped when include_watchlist is False (description matching —
    descriptions carry social-media boilerplate that would match company
    aliases like "Facebook").
    """
    match = sub.get("match", "all")
    if match == "all":
        return True
    text_lower = text.lower()
    if any(kw.lower() in text_lower for kw in match):
        return True
    if not include_watchlist:
        return False
    watchlist = sub.get("match_watchlist")
    if isinstance(watchlist, str):
        watchlist = [watchlist]
    if watchlist:
        return any(
            rx.search(text)
            for path in watchlist
            for _, rx in load_watchlist_tickers(path)
        )
    return False


def matches(sub, title):
    title_lower = title.lower()
    if any(kw.lower() in title_lower for kw in sub.get("exclude", [])):
        return False
    return matches_keywords(sub, title)


def is_short(video, sub):
    """Return True if the video looks like a YouTube Short.

    Based on duration only: anything at or below the subscription's
    shorts_max_duration (default 60s) counts as a Short. Unknown
    durations are not treated as Shorts, to avoid skipping normal
    videos on missing metadata.
    """
    if not sub.get("skip_shorts", False):
        return False
    duration = video.get("duration")
    if duration is None:
        return False
    return duration <= sub.get("shorts_max_duration", 60)


def is_video_file(path):
    """Return True for completed video/audio files under download_dir."""
    if not path.is_file():
        return False
    if path.name.startswith("."):
        return False
    if path.suffix.lower() not in VIDEO_EXTENSIONS:
        return False
    file_suffixes = {s.lower() for s in path.suffixes}
    if file_suffixes & SKIP_SUFFIXES:
        return False
    return True


def format_size(size):
    """Return a human-readable byte size."""
    if size < 1024:
        return f"{size} B"
    value = size / 1024
    for unit in ("KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.1f} {unit}"
        value /= 1024


def format_duration(seconds):
    """Return seconds as m:ss or h:mm:ss."""
    hours, rem = divmod(int(seconds), 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def load_durations():
    """Return the ffprobe duration cache: {rel path: {duration, size, mtime}}."""
    if DURATIONS_FILE.exists():
        try:
            with open(DURATIONS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
        except (json.JSONDecodeError, OSError) as e:
            log.warning("Could not read durations.json (%s); starting fresh", e)
    return {}


def save_durations(durations):
    tmp = DURATIONS_FILE.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(dict(sorted(durations.items())), f, indent=1)
    tmp.replace(DURATIONS_FILE)


def record_duration(download_dir, path, duration):
    """Cache a downloaded file's duration (known from yt-dlp) for the index."""
    if duration is None:
        return
    path = Path(path)
    try:
        rel = path.relative_to(download_dir).as_posix()
        stat = path.stat()
    except (ValueError, OSError):
        return
    durations = load_durations()
    durations[rel] = {
        "duration": duration, "size": stat.st_size, "mtime": stat.st_mtime,
    }
    save_durations(durations)


def parse_duration_print(stdout):
    """Extract the duration from yt-dlp's after_move "filepath<TAB>duration"
    printout (seconds, int), or None if not found."""
    duration = None
    for line in stdout.splitlines():
        _, _, value = line.rpartition("\t")
        try:
            duration = int(float(value.strip()))
        except ValueError:
            pass
    return duration


def scan_downloads(download_dir):
    """Scan download_dir recursively and group video files by top-level subfolder.

    Files under 'watched' subdirectories (archived by subscriptions with
    keep_watched: true) are not listed. Returns an ordered dict mapping
    channel/subfolder name to a list of entries sorted newest-first by
    file mtime. Each entry is a dict with keys: rel, name, size, mtime,
    channel, duration (seconds, or None if not in the cache).

    Durations come from durations.json (recorded at download time from
    yt-dlp's after_move printout), validated by size+mtime; files without
    a matching cache entry simply show no duration.
    """
    root = Path(download_dir)
    if not root.is_dir():
        return {}
    durations = load_durations()
    groups = {}
    for path in root.rglob("*"):
        if not is_video_file(path):
            continue
        rel = path.relative_to(root)
        if "watched" in rel.parts[:-1]:
            continue
        if len(rel.parts) > 1:
            channel = rel.parts[0]
        else:
            channel = "(root)"
        stat = path.stat()
        rel_posix = rel.as_posix()
        cached = durations.get(rel_posix)
        duration = None
        if (cached and cached.get("size") == stat.st_size
                and cached.get("mtime") == stat.st_mtime):
            duration = cached.get("duration")
        groups.setdefault(channel, []).append({
            "rel": rel_posix,
            "name": path.name,
            "size": stat.st_size,
            "mtime": stat.st_mtime,
            "channel": channel,
            "duration": duration,
        })
    # Drop cache entries for files that no longer exist.
    seen_rels = {e["rel"] for entries in groups.values() for e in entries}
    pruned = {k: v for k, v in durations.items() if k in seen_rels}
    if pruned != durations:
        save_durations(pruned)
    for entries in groups.values():
        entries.sort(key=lambda e: e["mtime"], reverse=True)
    return dict(sorted(groups.items(), key=lambda kv: kv[0].casefold()))


# Bump when the index.html template changes: the fingerprint below only
# covers the file listing, so without this an existing index.html would
# keep the old template until some video is added or removed.
INDEX_TEMPLATE_VERSION = 28


def fingerprint(groups, site_title=""):
    """Return a stable hash of the current download listing and page title."""
    data = []
    for channel, entries in groups.items():
        data.append({
            "channel": channel,
            "entries": [
                {"rel": e["rel"], "size": e["size"], "mtime": e["mtime"]}
                for e in entries
            ],
        })
    canonical = json.dumps(data, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha1(
        (f"{INDEX_TEMPLATE_VERSION}\n" + site_title + "\n" + canonical).encode("utf-8")
    ).hexdigest()


def read_existing_fingerprint(index_path):
    """Read the fingerprint embedded in an existing index.html, if any."""
    if not index_path.exists():
        return None
    try:
        text = index_path.read_text(encoding="utf-8")
    except OSError:
        return None
    match = INDEX_FINGERPRINT_RE.search(text)
    return match.group(1) if match else None


def generate_index_html(groups, total, channels, now_str, fp, latest=None, api_port=DEFAULT_API_PORT, site_title=DEFAULT_SITE_TITLE):
    """Build the index.html page."""
    latest = latest or []
    escaped_title = html.escape(site_title)
    lines = [
        "<!DOCTYPE html>",
        '<html lang="en">',
        "<head>",
        '  <meta charset="UTF-8">',
        '  <meta name="viewport" content="width=device-width, initial-scale=1.0">',
        f"  <title>{escaped_title}</title>",
        "  <style>",
        "    :root { color-scheme: dark; }",
        "    body {",
        "      margin: 0;",
        '      font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;',
        "      background: #121212;",
        "      color: #e0e0e0;",
        "      line-height: 1.5;",
        "    }",
        "    .container { max-width: 900px; margin: 0 auto; padding: 1rem; }",
        "    header { border-bottom: 1px solid #333; margin-bottom: 1.5rem; padding-bottom: 1rem; }",
        "    h1 { margin: 0; font-size: 1.5rem; color: #fff; }",
        "    header p { margin: .25rem 0 0; color: #aaa; font-size: .875rem; }",
        "    .channel { margin-bottom: 2rem; }",
        "    .latest h2 { color: #8ab4f8; }",
        "    h2 { margin: 0 0 .5rem; font-size: 1.15rem; color: #fff; }",
        "    ul { list-style: none; padding: 0; margin: 0; }",
        "    li {",
        "      display: flex;",
        "      justify-content: space-between;",
        "      align-items: center;",
        "      gap: 1rem;",
        "      padding: .75rem;",
        "      border-bottom: 1px solid #2a2a2a;",
        "    }",
        "    li:last-child { border-bottom: none; }",
        "    a { color: #8ab4f8; text-decoration: none; word-break: break-word; flex: 1; }",
        # Long titles are clamped to two lines on desktop; the full name
        # stays available as the link's hover tooltip (title attribute).
        "    li > a {",
        "      display: -webkit-box;",
        "      -webkit-box-orient: vertical;",
        "      -webkit-line-clamp: 2;",
        "      line-clamp: 2;",
        "      overflow: hidden;",
        "    }",
        "    a:hover { text-decoration: underline; }",
        "    .meta { white-space: nowrap; color: #999; font-size: .85rem; flex-shrink: 0; text-align: right; }",
        "    .watch-btn {",
        "      flex-shrink: 0;",
        "      padding: .15rem .55rem;",
        "      font-size: .8rem;",
        "      color: #bbb;",
        "      background: #2a2a2a;",
        "      border: 1px solid #444;",
        "      border-radius: 4px;",
        "      cursor: pointer;",
        "    }",
        "    .watch-btn:hover { background: #3a3a3a; color: #fff; }",
        "    .tools { margin-bottom: 2rem; }",
        "    .tools form { display: flex; gap: .5rem; flex-wrap: wrap; align-items: center; }",
        "    .tools input[type=url] {",
        "      flex: 1; min-width: 200px; padding: .4rem .6rem;",
        "      background: #1e1e1e; border: 1px solid #444; border-radius: 4px; color: #e0e0e0;",
        "    }",
        "    .tools select, .tools button {",
        "      padding: .4rem .8rem; background: #2a2a2a; border: 1px solid #444;",
        "      border-radius: 4px; color: #e0e0e0; cursor: pointer;",
        "    }",
        "    .tools button:hover { background: #3a3a3a; color: #fff; }",
        "    .tool-status { color: #999; font-size: .85rem; }",
        "    .tools details { margin-top: 1rem; }",
        "    .tools summary { cursor: pointer; color: #8ab4f8; }",
        "    #config-text, #cookies-text {",
        "      width: 100%; box-sizing: border-box; height: 20rem; margin: .5rem 0;",
        "      background: #1e1e1e; border: 1px solid #444; border-radius: 4px;",
        "      color: #e0e0e0; font-family: monospace; padding: .5rem;",
        "    }",
        "    #cookies-text { height: 8rem; }",
        "    #cookies-file { display: block; margin-top: .5rem; color: #999; }",
        "    .playlist { margin-bottom: 2rem; }",
        "    .playlist button {",
        "      padding: .4rem .8rem; background: #2a2a2a; border: 1px solid #444;",
        "      border-radius: 4px; color: #e0e0e0; cursor: pointer;",
        "    }",
        "    .playlist button:hover { background: #3a3a3a; color: #fff; }",
        "    .pl-controls { display: flex; gap: .75rem; align-items: center; margin-top: .5rem; }",
        "    .pl-controls label { color: #bbb; font-size: .9rem; }",
        "    #pl-empty { color: #999; font-size: .9rem; }",
        "    #pl-video { width: 100%; max-height: 70vh; margin-top: .75rem; background: #000; }",
        "    #pl-now { color: #8ab4f8; margin-top: .5rem; font-size: .95rem; }",
        "    li.pl-current a { color: #7bd88a; }",
        "    li.pl-current-video > a { color: #7bd88a; }",
        "    .pl-remove { flex-shrink: 0; }",
        "    #pl-items li { cursor: grab; }",
        "    #pl-items li.pl-drop-target { border-top: 2px solid #8ab4f8; }",
        # Queued-state cues: text/shape changes carry the meaning (color-
        # blind safe); the green tint is only a secondary hint.
        "    .watch-btn.pl-added { color: #7bd88a; border-color: #7bd88a; }",
        "    li.pl-queued > a { font-weight: bold; }",
        "    li.pl-queued > a::before { content: \"\\2261  \"; color: #7bd88a; }",
        "    li.watched { opacity: .45; }",
        "    li.watched a { text-decoration: line-through; }",
        "    li.watched .watch-btn { color: #7bd88a; border-color: #7bd88a; }",
        "    footer { margin-top: 2rem; padding-top: 1rem; border-top: 1px solid #333; color: #888; font-size: .85rem; text-align: center; }",
        "    @media (max-width: 600px) {",
        "      li { flex-direction: column; gap: .25rem; align-items: flex-start; }",
        "      li > a { display: block; overflow: visible; }",
        "      .meta { text-align: left; white-space: normal; }",
        "    }",
        "  </style>",
        "</head>",
        "<body>",
        '  <div class="container">',
        "    <header>",
        f"      <h1>{escaped_title}</h1>",
        f'      <p id="library-status">Last updated: {html.escape(now_str)} &mdash; {total} video(s) across {channels} channel(s)</p>',
        '      <p class="tool-status" id="watch-status"></p>',
        "    </header>",
    ]

    lines.extend([
        '    <section class="tools">',
        '      <form id="dl-form">',
        '        <input type="url" id="dl-url" '
        'placeholder="https://www.youtube.com/watch?v=&hellip;" required>',
        '        <select id="dl-quality">',
        '          <option value="720" selected>720p</option>',
        '          <option value="best">Best</option>',
        '          <option value="audio">Audio only</option>',
        '        </select>',
        '        <button type="submit">Download</button>',
        '        <span class="tool-status" id="dl-status"></span>',
        '      </form>',
        '      <details id="config-editor">',
        '        <summary>Edit subscriptions</summary>',
        '        <textarea id="config-text" spellcheck="false"></textarea>',
        '        <button type="button" id="config-save">Save</button>',
        '        <span class="tool-status" id="config-status"></span>',
        '      </details>',
        '      <details id="cookies-editor">',
        '        <summary>Cookies for yt-dlp</summary>',
        '        <p class="tool-status">Used automatically as a retry when a download '
        'fails without cookies. Paste a Netscape cookies.txt export (e.g. from a '
        'browser extension); saving replaces the current cookies, saving an empty '
        'box removes them. Saved cookies are never displayed here.</p>',
        '        <input type="file" id="cookies-file" accept=".txt,text/plain">',
        '        <textarea id="cookies-text" spellcheck="false" '
        'placeholder="# Netscape HTTP Cookie File"></textarea>',
        '        <button type="button" id="cookies-save">Save cookies</button>',
        '        <span class="tool-status" id="cookies-status"></span>',
        '      </details>',
        '    </section>',
    ])

    lines.extend([
        '    <section class="playlist">',
        '      <h2>Playlist</h2>',
        '      <p id="pl-empty">Empty &mdash; add videos with the + Playlist buttons below.</p>',
        '      <ul id="pl-items"></ul>',
        '      <div class="pl-controls">',
        '        <button type="button" id="pl-play">Play</button>',
        '        <button type="button" id="pl-add-all" '
        'title="Queue every listed video in random order">Add all shuffled</button>',
        '        <button type="button" id="pl-add-latest" '
        'title="Queue the Latest section in listed order">Add all latest</button>',
        '        <button type="button" id="pl-add-espanol" '
        'title="Queue every Spanish video in listed order">Add all Spanish</button>',
        '        <label><input type="checkbox" id="pl-repeat"> Repeat</label>',
        '        <button type="button" id="pl-clear">Clear</button>',
        '      </div>',
        '      <div id="pl-player" hidden>',
        '        <video id="pl-video" controls playsinline></video>',
        '        <div id="pl-now"></div>',
        '      </div>',
        '    </section>',
    ])

    def entry_lines(entry, show_channel=False):
        href = urllib.parse.quote(entry["rel"], safe="/")
        size = format_size(entry["size"])
        mtime_str = datetime.fromtimestamp(entry["mtime"]).strftime("%Y-%m-%d %H:%M")
        meta_parts = [mtime_str, size]
        if entry.get("duration"):
            meta_parts.insert(0, format_duration(entry["duration"]))
        if show_channel:
            meta_parts.insert(0, html.escape(entry.get("channel", "")))
        data_attr = f' data-id="{entry_id(entry)}"'
        # "watch-toggle" is the unambiguous hook for the watched-mark JS:
        # both buttons carry "watch-btn" for styling, so a plain
        # querySelector(".watch-btn") would grab whichever comes first.
        watch_btn = (
            '          <button class="watch-btn watch-toggle" type="button">Mark watched</button>'
        )
        pl_add_btn = (
            '          <button class="watch-btn pl-add" type="button">+ Playlist</button>'
        )
        return [line for line in [
            f"        <li{data_attr}>",
            (
                f'          <a href="{href}" title="{html.escape(entry["name"])}">'
                f"{html.escape(entry['name'])}</a>"
            ),
            pl_add_btn,
            watch_btn,
            f'          <span class="meta">{" &middot; ".join(meta_parts)}</span>',
            "        </li>",
        ] if line]

    lines.append('    <div id="video-sections">')
    if latest:
        lines.append('    <section class="channel latest">')
        lines.append('      <h2>🆕 Latest</h2>')
        lines.append('      <ul>')
        for entry in latest:
            lines.extend(entry_lines(entry, show_channel=True))
        lines.append('      </ul>')
        lines.append('    </section>')

    for channel, entries in groups.items():
        lines.append(f'    <section class="channel" data-channel="{html.escape(channel)}">')
        lines.append(f"      <h2>{html.escape(channel)}</h2>")
        lines.append("      <ul>")
        for entry in entries:
            lines.extend(entry_lines(entry))
        lines.append("      </ul>")
        lines.append("    </section>")
    lines.append("    </div>")
    lines.extend([
        "    <footer>Generated by ytwatcher</footer>",
        "  </div>",
        f"<!-- index-fingerprint: {fp} -->",
        "<script>",
        "(function () {",
        '  var API = "http://" + location.hostname + ":' + str(api_port) + '";',
        '  var KEY = "ytwatcher:watched";',
        "  function load() {",
        "    try { return new Set(JSON.parse(localStorage.getItem(KEY) || '[]')); }",
        "    catch (e) { return new Set(); }",
        "  }",
        "  function save(s) { localStorage.setItem(KEY, JSON.stringify(Array.from(s))); }",
        "  var watched = load();",
        '  var watchStatus = document.getElementById("watch-status");',
        "  // The server (watched.json) is the source of truth: merge its IDs",
        "  // into the local set so marks sync across browsers and stale",
        "  // localStorage heals. On failure keep the local state.",
        '  fetch(API + "/watched").then(function (r) {',
        '    if (!r.ok) throw new Error("HTTP " + r.status);',
        "    return r.json();",
        "  }).then(function (d) {",
        "    (d.ids || []).forEach(function (id) { watched.add(id); });",
        "    save(watched);",
        "    // Drop playlist entries whose files are gone: watched-marked",
        "    // files are deleted or moved to watched/ at the next scan",
        "    // round, leaving dead links in the stored playlist.",
        "    var serverWatched = new Set(d.ids || []);",
        "    var playing = plIndex >= 0 ? pl[plIndex] : null;",
        "    pl = pl.filter(function (item) {",
        "      var m = item.name.match(/\\[([A-Za-z0-9_-]{11})\\]/);",
        "      return !m || !serverWatched.has(m[1]);",
        "    });",
        "    if (playing) {",
        "      plIndex = pl.indexOf(playing);",
        "      if (plIndex < 0) { plVideo.pause(); plPlayer.hidden = true; }",
        "    }",
        "    plSave();",
        "    plRender();",
        "    applyAll();",
        "  }).catch(function () {});",
        "  function report(id, isWatched) {",
        '    fetch(API + "/watched", {',
        '      method: "POST",',
        '      headers: { "Content-Type": "text/plain" },',
        '      body: JSON.stringify({ id: id, watched: isWatched }),',
        "    }).then(function (r) {",
        '      if (!r.ok) throw new Error("HTTP " + r.status);',
        '      watchStatus.textContent = "";',
        "    }).catch(function () {",
        "      // The server did not record the mark: undo the optimistic",
        "      // local change. Without the server record the file would",
        "      // never be deleted, so don't pretend it is marked.",
        "      if (isWatched) { watched.delete(id); } else { watched.add(id); }",
        "      save(watched);",
        "      applyAll();",
        '      watchStatus.textContent = "watched mark NOT saved (API unreachable) \\u2014 try again";',
        "    });",
        "  }",
        "  var dlForm = document.getElementById(\"dl-form\");",
        "  var dlStatus = document.getElementById(\"dl-status\");",
        "  function pollDownloads(jobId) {",
        "    fetch(API + \"/downloads\").then(function (r) { return r.json(); }).then(function (data) {",
        "      var job = null;",
        "      (data.jobs || []).forEach(function (j) { if (j.id === jobId) job = j; });",
        "      if (!job) { dlStatus.textContent = \"\"; return; }",
        "      if (job.status === \"running\") {",
        "        dlStatus.textContent = \"downloading\\u2026\";",
        "        setTimeout(function () { pollDownloads(jobId); }, 3000);",
        "      } else if (job.status === \"done\") {",
        "        dlStatus.textContent = \"done \\u2014 reloading\\u2026\";",
        "        setTimeout(function () { location.reload(); }, 1500);",
        "      } else {",
        "        dlStatus.textContent = \"failed: \" + (job.error || \"unknown error\");",
        "      }",
        "    }).catch(function () {",
        "      setTimeout(function () { pollDownloads(jobId); }, 5000);",
        "    });",
        "  }",
        "  dlForm.addEventListener(\"submit\", function (ev) {",
        "    ev.preventDefault();",
        "    var url = document.getElementById(\"dl-url\").value.trim();",
        "    var quality = document.getElementById(\"dl-quality\").value;",
        "    if (!url) return;",
        "    dlStatus.textContent = \"starting\\u2026\";",
        "    fetch(API + \"/download\", {",
        "      method: \"POST\",",
        "      headers: { \"Content-Type\": \"application/json\" },",
        "      body: JSON.stringify({ url: url, quality: quality }),",
        "    }).then(function (r) {",
        "      if (!r.ok) return r.json().then(function (d) { throw new Error(d.error || (\"HTTP \" + r.status)); });",
        "      return r.json();",
        "    }).then(function (d) {",
        "      dlStatus.textContent = \"downloading\\u2026\";",
        "      pollDownloads(d.job_id);",
        "    }).catch(function (e) {",
        "      dlStatus.textContent = \"failed: \" + e.message;",
        "    });",
        "  });",
        "  var configEditor = document.getElementById(\"config-editor\");",
        "  var configText = document.getElementById(\"config-text\");",
        "  var configStatus = document.getElementById(\"config-status\");",
        "  var configLoaded = false;",
        "  configEditor.addEventListener(\"toggle\", function () {",
        "    if (!configEditor.open || configLoaded) return;",
        "    configStatus.textContent = \"loading\\u2026\";",
        "    fetch(API + \"/config\").then(function (r) { return r.text(); }).then(function (text) {",
        "      configText.value = text;",
        "      configLoaded = true;",
        "      configStatus.textContent = \"\";",
        "    }).catch(function () { configStatus.textContent = \"could not load config\"; });",
        "  });",
        "  document.getElementById(\"config-save\").addEventListener(\"click\", function () {",
        "    configStatus.textContent = \"saving\\u2026\";",
        "    fetch(API + \"/config\", {",
        "      method: \"POST\",",
        "      headers: { \"Content-Type\": \"text/plain\" },",
        "      body: configText.value,",
        "    }).then(function (r) {",
        "      if (r.ok) { configStatus.textContent = \"saved \\u2014 applies from the next scan round\"; return; }",
        "      return r.json().then(function (d) {",
        "        configStatus.textContent = \"not saved: \" + (d.problems || [d.error || (\"HTTP \" + r.status)]).join(\"; \");",
        "      });",
        "    }).catch(function () { configStatus.textContent = \"save failed (API unreachable)\"; });",
        "  });",
        "  document.getElementById(\"cookies-file\").addEventListener(\"change\", function () {",
        "    var f = this.files[0];",
        "    if (!f) return;",
        "    f.text().then(function (text) {",
        "      document.getElementById(\"cookies-text\").value = text;",
        "      cookiesStatus.textContent = \"loaded \" + f.name + \" \\u2014 click Save cookies\";",
        "    });",
        "  });",
        "  var cookiesEditor = document.getElementById(\"cookies-editor\");",
        "  var cookiesText = document.getElementById(\"cookies-text\");",
        "  var cookiesStatus = document.getElementById(\"cookies-status\");",
        "  var cookiesLoaded = false;",
        "  function showCookiesState(d) {",
        "    cookiesStatus.textContent = d.set ? (\"cookies set (\" + d.lines + \" cookies)\") : \"no cookies set\";",
        "  }",
        "  cookiesEditor.addEventListener(\"toggle\", function () {",
        "    if (!cookiesEditor.open || cookiesLoaded) return;",
        "    fetch(API + \"/cookies\").then(function (r) { return r.json(); }).then(function (d) {",
        "      cookiesLoaded = true;",
        "      showCookiesState(d);",
        "    }).catch(function () { cookiesStatus.textContent = \"could not query cookies state\"; });",
        "  });",
        "  document.getElementById(\"cookies-save\").addEventListener(\"click\", function () {",
        "    cookiesStatus.textContent = \"saving\\u2026\";",
        "    fetch(API + \"/cookies\", {",
        "      method: \"POST\",",
        "      headers: { \"Content-Type\": \"text/plain\" },",
        "      body: cookiesText.value,",
        "    }).then(function (r) {",
        "      return r.json().then(function (d) {",
        "        if (!r.ok) { cookiesStatus.textContent = \"not saved: \" + (d.error || (\"HTTP \" + r.status)); return; }",
        "        cookiesText.value = \"\";",
        "        showCookiesState(d);",
        "      });",
        "    }).catch(function () { cookiesStatus.textContent = \"save failed (API unreachable)\"; });",
        "  });",
        "  var PL_KEY = \"ytwatcher:playlist\";",
        "  var PL_REPEAT_KEY = \"ytwatcher:playlist-repeat\";",
        "  function plLoad() {",
        "    try { return JSON.parse(localStorage.getItem(PL_KEY) || \"[]\"); }",
        "    catch (e) { return []; }",
        "  }",
        "  var pl = plLoad();",
        "  function plSave() { localStorage.setItem(PL_KEY, JSON.stringify(pl)); }",
        "  var plItems = document.getElementById(\"pl-items\");",
        "  var plEmpty = document.getElementById(\"pl-empty\");",
        "  var plPlayer = document.getElementById(\"pl-player\");",
        "  var plVideo = document.getElementById(\"pl-video\");",
        "  var plNow = document.getElementById(\"pl-now\");",
        "  var plRepeat = document.getElementById(\"pl-repeat\");",
        "  var plIndex = -1;",
        "  var plDragIndex = -1;",
        "  function plRemoveAt(i, markWatched) {",
        "    var removed = pl[i];",
        "    var removedCurrent = plIndex === i;",
        "    var nextIndex = -1;",
        "    pl.splice(i, 1);",
        "    if (removedCurrent) {",
        "      // The old next item shifts into the removed item's index.",
        "      if (i < pl.length) nextIndex = i;",
        "      else if (pl.length && plRepeat.checked) nextIndex = 0;",
        "      plIndex = -1;",
        "      plVideo.pause();",
        "      if (nextIndex < 0) plPlayer.hidden = true;",
        "    }",
        "    else if (plIndex > i) { plIndex--; }",
        "    plSave();",
        "    if (nextIndex >= 0) plPlayAt(nextIndex);",
        "    else { plSavePos(); plRender(); }",
        "    // Removing via the ✕ button means \"done with it\": mark the video",
        "    // watched (it will be deleted at the next scan round). Clearing",
        "    // the whole playlist or untoggling + Playlist does not mark.",
        "    if (markWatched && removed) {",
        "      var m = removed.name.match(/\\[([A-Za-z0-9_-]{11})\\]/);",
        "      if (m && !watched.has(m[1])) {",
        "        watched.add(m[1]);",
        "        save(watched);",
        "        report(m[1], true);",
        "        applyAll();",
        "      }",
        "    }",
        "  }",
        "  function plMoveTo(from, to) {",
        "    if (from < 0 || from >= pl.length || from === to) return;",
        "    var moved = pl.splice(from, 1)[0];",
        "    pl.splice(to, 0, moved);",
        "    // Keep plIndex on the playing item through the move.",
        "    if (plIndex === from) { plIndex = to; }",
        "    else {",
        "      if (plIndex > from) plIndex--;",
        "      if (plIndex >= to) plIndex++;",
        "    }",
        "    plSave();",
        "    plRender();",
        "  }",
        "  function plRender() {",
        "    plItems.innerHTML = \"\";",
        "    plEmpty.style.display = pl.length ? \"none\" : \"\";",
        "    if (plIndex >= 0 && pl[plIndex]) {",
        "      plNow.textContent = (plIndex + 1) + \"/\" + pl.length + \" \\u2014 \" + pl[plIndex].name;",
        "    }",
        "    pl.forEach(function (item, i) {",
        "      var li = document.createElement(\"li\");",
        "      if (i === plIndex) li.className = \"pl-current\";",
        "      // Drag-and-drop reordering with the mouse.",
        "      li.draggable = true;",
        "      li.addEventListener(\"dragstart\", function (ev) {",
        "        plDragIndex = i;",
        "        ev.dataTransfer.effectAllowed = \"move\";",
        "        // setData is required for the drag to start in Firefox.",
        "        ev.dataTransfer.setData(\"text/plain\", String(i));",
        "      });",
        "      li.addEventListener(\"dragover\", function (ev) {",
        "        ev.preventDefault();",
        "        ev.dataTransfer.dropEffect = \"move\";",
        "        li.classList.add(\"pl-drop-target\");",
        "      });",
        "      li.addEventListener(\"dragleave\", function () {",
        "        li.classList.remove(\"pl-drop-target\");",
        "      });",
        "      li.addEventListener(\"drop\", function (ev) {",
        "        ev.preventDefault();",
        "        li.classList.remove(\"pl-drop-target\");",
        "        plMoveTo(plDragIndex, i);",
        "      });",
        "      li.addEventListener(\"dragend\", function () {",
        "        plDragIndex = -1;",
        "        plItems.querySelectorAll(\".pl-drop-target\").forEach(function (x) {",
        "          x.classList.remove(\"pl-drop-target\");",
        "        });",
        "      });",
        "      var a = document.createElement(\"a\");",
        "      a.href = item.href;",
        "      a.textContent = item.name;",
        "      a.title = item.name;",
        "      a.addEventListener(\"click\", function (ev) { ev.preventDefault(); plPlayAt(i); });",
        "      var rm = document.createElement(\"button\");",
        "      rm.className = \"pl-remove\";",
        "      rm.type = \"button\";",
        "      rm.textContent = \"\\u2715\";",
        '      rm.title = "Remove and mark watched";',
        "      rm.addEventListener(\"click\", function () { plRemoveAt(i, true); });",
        "      li.appendChild(a);",
        "      li.appendChild(rm);",
        "      plItems.appendChild(li);",
        "    });",
        "    plUpdateButtons();",
        "  }",
        "  function plPlayAt(i) {",
        "    if (i < 0 || i >= pl.length) return;",
        "    plIndex = i;",
        "    plPlayer.hidden = false;",
        "    plNow.textContent = (i + 1) + \"/\" + pl.length + \" \\u2014 \" + pl[i].name;",
        "    plVideo.src = pl[i].href;",
        "    // Do not carry the previous item's speed into a new video.",
        "    plVideo.playbackRate = 1;",
        "    plVideo.play().catch(function () {});",
        "    // Tell the OS what is playing: Android keeps background audio",
        "    // (and screen-off track changes) alive only for an element with",
        "    // an active media session; without it the 'ended' -> play()",
        "    // transition is blocked once the screen sleeps.",
        "    if (\"mediaSession\" in navigator) {",
        "      navigator.mediaSession.metadata = new MediaMetadata({",
        "        title: pl[i].name, artist: \"ytwatcher\",",
        "      });",
        "    }",
        "    plRender();",
        "  }",
        "  if (\"mediaSession\" in navigator) {",
        "    navigator.mediaSession.setActionHandler(\"nexttrack\", function () {",
        "      if (plIndex + 1 < pl.length) plPlayAt(plIndex + 1);",
        "    });",
        "    navigator.mediaSession.setActionHandler(\"previoustrack\", function () {",
        "      if (plIndex > 0) plPlayAt(plIndex - 1);",
        "    });",
        "  }",
        "  plVideo.addEventListener(\"ended\", function () {",
        "    var next = plIndex + 1;",
        "    if (next >= pl.length) {",
        "      if (!plRepeat.checked) { plIndex = -1; plSavePos(); plRender(); return; }",
        "      next = 0;",
        "    }",
        "    plPlayAt(next);",
        "  });",
        "  // Persist the play position so a page refresh can resume.",
        "  var PL_POS_KEY = \"ytwatcher:playlist-pos\";",
        "  function plSavePos() {",
        "    if (plIndex < 0 || !pl[plIndex]) {",
        "      localStorage.removeItem(PL_POS_KEY);",
        "      return;",
        "    }",
        "    localStorage.setItem(PL_POS_KEY, JSON.stringify({",
        "      href: pl[plIndex].href, time: plVideo.currentTime,",
        "    }));",
        "  }",
        "  var plPosSavedAt = 0;",
        "  plVideo.addEventListener(\"timeupdate\", function () {",
        "    var now = Date.now();",
        "    if (now - plPosSavedAt < 5000) return;",
        "    plPosSavedAt = now;",
        "    plSavePos();",
        "  });",
        "  plVideo.addEventListener(\"pause\", plSavePos);",
        "  window.addEventListener(\"beforeunload\", plSavePos);",
        "  // Audio-only downloads may use a video container such as .webm,",
        "  // so inspect the loaded stream as well as known audio extensions.",
        "  plVideo.addEventListener(\"loadedmetadata\", function () {",
        "    if (plIndex < 0 || !pl[plIndex]) return;",
        "    var href = pl[plIndex].href.split(/[?#]/)[0];",
        "    var audioExtension = /\\.(m4a|mp3|opus|ogg|aac|wav|flac)$/i.test(href);",
        "    plVideo.playbackRate = audioExtension || plVideo.videoWidth === 0 ? 2 : 1;",
        "  });",
        "  // Resume after a refresh: restore the item (by href, robust",
        "  // against reordering) and position. If autoplay is blocked the",
        "  // video simply stays paused at the saved position.",
        "  function plTryResume() {",
        "    var saved;",
        "    try { saved = JSON.parse(localStorage.getItem(PL_POS_KEY) || \"null\"); }",
        "    catch (e) { saved = null; }",
        "    if (!saved || !saved.href) return;",
        "    var idx = pl.findIndex(function (item) { return item.href === saved.href; });",
        "    if (idx < 0) { localStorage.removeItem(PL_POS_KEY); return; }",
        "    plIndex = idx;",
        "    plPlayer.hidden = false;",
        "    plNow.textContent = (idx + 1) + \"/\" + pl.length + \" \\u2014 \" + pl[idx].name;",
        "    plVideo.src = pl[idx].href;",
        "    plVideo.playbackRate = 1;",
        "    if (saved.time > 0) {",
        "      plVideo.addEventListener(\"loadedmetadata\", function seek() {",
        "        plVideo.removeEventListener(\"loadedmetadata\", seek);",
        "        plVideo.currentTime = saved.time;",
        "      });",
        "    }",
        "    plVideo.play().catch(function () {});",
        "    plRender();",
        "  }",
        "  plRepeat.checked = localStorage.getItem(PL_REPEAT_KEY) === \"1\";",
        "  plRepeat.addEventListener(\"change\", function () {",
        "    localStorage.setItem(PL_REPEAT_KEY, plRepeat.checked ? \"1\" : \"0\");",
        "  });",
        "  document.getElementById(\"pl-play\").addEventListener(\"click\", function () {",
        "    plPlayAt(plIndex >= 0 ? plIndex : 0);",
        "  });",
        "  function plQueueFrom(selector, shuffle) {",
        "    // Queue every matching listed video that isn't queued yet.",
        "    var have = {};",
        "    pl.forEach(function (item) { have[item.href] = true; });",
        "    var fresh = [];",
        "    document.querySelectorAll(selector).forEach(function (li) {",
        "      var a = li.querySelector(\"a\");",
        "      var href = a.getAttribute(\"href\");",
        "      if (!have[href]) {",
        "        have[href] = true;",
        "        fresh.push({ href: href, name: a.textContent });",
        "      }",
        "    });",
        "    if (shuffle) {",
        "      // Fisher-Yates shuffle.",
        "      for (var i = fresh.length - 1; i > 0; i--) {",
        "        var j = Math.floor(Math.random() * (i + 1));",
        "        var t = fresh[i]; fresh[i] = fresh[j]; fresh[j] = t;",
        "      }",
        "    }",
        "    pl = pl.concat(fresh);",
        "    plSave();",
        "    // Queue was empty: start playing right away.",
        "    if (plIndex < 0 && pl.length === fresh.length && pl.length) {",
        "      plPlayAt(0);",
        "      return;",
        "    }",
        "    plRender();",
        "  }",
        "  document.getElementById(\"pl-add-all\").addEventListener(\"click\", function () {",
        "    plQueueFrom(\"li[data-id]\", true);",
        "  });",
        "  document.getElementById(\"pl-add-latest\").addEventListener(\"click\", function () {",
        "    plQueueFrom(\"section.latest li[data-id]\", false);",
        "  });",
        "  document.getElementById(\"pl-add-espanol\").addEventListener(\"click\", function () {",
        "    plQueueFrom(\"section[data-channel='Espanol'] li[data-id]\", false);",
        "  });",
        "  document.getElementById(\"pl-clear\").addEventListener(\"click\", function () {",
        "    pl = [];",
        "    plIndex = -1;",
        "    plSavePos();",
        "    plVideo.pause();",
        "    plPlayer.hidden = true;",
        "    plSave();",
        "    plRender();",
        "  });",
        "  function plUpdateButtons() {",
        "    var playingHref = plIndex >= 0 && pl[plIndex] ? pl[plIndex].href : null;",
        "    document.querySelectorAll(\".pl-add\").forEach(function (btn) {",
        "      var li = btn.closest(\"li\");",
        "      var href = li.querySelector(\"a\").getAttribute(\"href\");",
        "      var queued = pl.some(function (item) { return item.href === href; });",
        '      li.classList.toggle("pl-current-video", href === playingHref);',
        "      li.classList.toggle(\"pl-queued\", queued);",
        "      btn.classList.toggle(\"pl-added\", queued);",
        "      btn.textContent = queued ? \"\\u2713 In playlist\" : \"+ Playlist\";",
        "    });",
        "  }",
        "  plRender();",
        "  plTryResume();",
        "  var applyFns = [];",
        "  function applyAll() { applyFns.forEach(function (fn) { fn(); }); }",
        "  function bindAvailableVideos() {",
        "    applyFns = [];",
        '    document.querySelectorAll("#video-sections ul").forEach(function (ul) {',
        '    var items = Array.prototype.slice.call(ul.querySelectorAll("li[data-id]"));',
        "    if (!items.length) return;",
        "    var original = items.slice();",
        "    function apply() {",
        "      original.forEach(function (li) {",
        "        var isWatched = watched.has(li.dataset.id);",
        '        li.classList.toggle("watched", isWatched);',
        '        li.querySelector(".watch-toggle").textContent = isWatched ? "\\u2713 Watched" : "Mark watched";',
        "      });",
        "      original.filter(function (li) { return !watched.has(li.dataset.id); })",
        "        .concat(original.filter(function (li) { return watched.has(li.dataset.id); }))",
        "        .forEach(function (li) { ul.appendChild(li); });",
        "    }",
        "    applyFns.push(apply);",
        "    items.forEach(function (li) {",
        '      li.querySelector(".pl-add").addEventListener("click", function () {',
        '        var a = li.querySelector("a");',
        '        var href = a.getAttribute("href");',
        "        var idx = pl.findIndex(function (item) { return item.href === href; });",
        "        if (idx >= 0) { plRemoveAt(idx, false); return; }",
        "        pl.push({ href: href, name: a.textContent });",
        "        plSave();",
        "        // First item added to an empty playlist: start playing it.",
        "        if (pl.length === 1) { plPlayAt(0); return; }",
        "        plRender();",
        "      });",
        '      li.querySelector(".watch-toggle").addEventListener("click", function () {',
        "        var id = li.dataset.id;",
        "        var isWatched = !watched.has(id);",
        "        if (isWatched) { watched.add(id); } else { watched.delete(id); }",
        "        save(watched);",
        "        report(id, isWatched);",
        "        applyAll();",
        "      });",
        "    });",
        "    });",
        "    applyAll();",
        "    plUpdateButtons();",
        "  }",
        "  var libraryRefreshBusy = false;",
        "  function refreshAvailableVideos() {",
        "    if (libraryRefreshBusy || document.hidden) return;",
        "    libraryRefreshBusy = true;",
        '    fetch(location.pathname + "?_library=" + Date.now(), { cache: "no-store" })',
        "      .then(function (r) { if (!r.ok) throw new Error(\"HTTP \" + r.status); return r.text(); })",
        "      .then(function (text) {",
        '        var fresh = new DOMParser().parseFromString(text, "text/html");',
        '        var incoming = fresh.getElementById("video-sections");',
        '        var current = document.getElementById("video-sections");',
        "        if (!incoming || !current || incoming.innerHTML === current.innerHTML) return;",
        "        current.innerHTML = incoming.innerHTML;",
        '        var incomingStatus = fresh.getElementById("library-status");',
        '        if (incomingStatus) document.getElementById("library-status").innerHTML = incomingStatus.innerHTML;',
        "        bindAvailableVideos();",
        "      })",
        "      .catch(function () {})",
        "      .then(function () { libraryRefreshBusy = false; });",
        "  }",
        "  bindAvailableVideos();",
        "  setInterval(refreshAvailableVideos, 60000);",
        '  document.addEventListener("visibilitychange", function () {',
        "    if (!document.hidden) refreshAvailableVideos();",
        "  });",
        "})();",
        "</script>",
        "</body>",
        "</html>",
    ])
    return "\n".join(lines)


def update_index_html(download_dir, api_port=DEFAULT_API_PORT,
                      site_title=DEFAULT_SITE_TITLE, max_age_days=None):
    """Regenerate download_dir/index.html if the file listing has changed.

    The page is always built from a full recursive scan of download_dir, so
    deleted files disappear automatically. When max_age_days is set, files
    whose mtime is older than that many days are left out of the listing
    (they stay on disk); the "manually" folder is exempt. Watched files
    are never listed regardless: they are deleted or archived into
    'watched' subfolders.
    """
    groups = scan_downloads(download_dir)
    if max_age_days:
        cutoff = time.time() - max_age_days * 86400
        groups = {
            # "manually" is exempt: those downloads are deliberate one-offs,
            # and an old upload would otherwise vanish from the page the
            # moment it is downloaded.
            channel: ([e for e in entries if e["mtime"] >= cutoff]
                      if channel != "manually" else entries)
            for channel, entries in groups.items()
        }
        groups = {c: es for c, es in groups.items() if es}
    total = sum(len(entries) for entries in groups.values())
    channels = len(groups)
    fp = fingerprint(groups, site_title)
    index_path = Path(download_dir) / "index.html"
    if read_existing_fingerprint(index_path) == fp:
        return False, total, channels
    # Top 10 newest videos across all channels.
    latest = sorted(
        (entry for entries in groups.values() for entry in entries),
        key=lambda e: e["mtime"],
        reverse=True,
    )[:10]
    now_str = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    html_content = generate_index_html(groups, total, channels, now_str, fp, latest=latest, api_port=api_port, site_title=site_title)
    # Unique tmp name per process: a fixed "index.html.tmp" races when the
    # watcher and a manual download rebuild the index concurrently.
    tmp = index_path.with_name(f"{index_path.name}.{os.getpid()}.tmp")
    tmp.write_text(html_content, encoding="utf-8")
    tmp.replace(index_path)
    log.info("index.html updated (%d videos across %d channels)", total, channels)
    return True, total, channels


# ---------------------------------------------------------------------------
# HTTP API: watched marks, config editing, manual downloads (+ deletion)
# ---------------------------------------------------------------------------


def delete_watched_videos(download_dir, watched_ids, keep_channels=()):
    """Delete downloaded files whose video ID is in watched_ids.

    Files under a channel named in keep_channels are moved into a
    'watched' subdirectory of the channel folder instead of being
    deleted. Returns the number of files removed from the listing. The
    index page is rebuilt from a full scan, so they disappear from it
    automatically.
    """
    if not watched_ids:
        return 0
    root = Path(download_dir)
    if not root.is_dir():
        return 0
    removed = 0
    for path in root.rglob("*"):
        if not is_video_file(path):
            continue
        rel = path.relative_to(root)
        if "watched" in rel.parts[:-1]:
            # Already archived in a 'watched' subdirectory.
            continue
        id_match = VIDEO_ID_RE.search(path.name)
        if id_match:
            video_id = id_match.group(1)
        else:
            # Files without a YouTube ID in the name are marked on the
            # index page with a path-derived pseudo-ID (see entry_id);
            # compute the same ID here so those marks can be acted on.
            video_id = (
                "m" + hashlib.sha1(rel.as_posix().encode("utf-8")).hexdigest()[:10]
            )
        if video_id not in watched_ids:
            continue
        channel = rel.parts[0] if len(rel.parts) > 1 else None
        try:
            if channel in keep_channels:
                dest_dir = root / channel / "watched"
                dest_dir.mkdir(exist_ok=True)
                path.replace(dest_dir / path.name)
                removed += 1
                log.info("moved watched video to %s: %s", dest_dir.name, path.name)
            else:
                path.unlink()
                removed += 1
                log.info("deleted watched video: %s", path.name)
        except OSError as e:
            log.error("failed to remove %s: %s", path, e)
    return removed


class ApiHandler(BaseHTTPRequestHandler):
    """HTTP API backing the index page.

    GET  /watched   returns {"ids": [...]} — the server's watched set.
    POST /watched   {"id": "<video id>", "watched": true} adds or removes
                    the ID in watched.json. Nothing here deletes files;
                    deletion happens at the start of the next scan round,
                    so an accidental mark can be undone before it runs.
    GET  /config    returns the raw subscriptions.yaml text.
    POST /config    replaces subscriptions.yaml (raw YAML body) after
                    validation; 400 with {"problems": [...]} if invalid.
    POST /download  {"url": "...", "quality": "720"|"best"|"audio"} starts
                    a manual download job; 202 with {"job_id": "..."}.
    GET  /downloads returns the status of recent manual download jobs.
    GET  /cookies   returns whether cookies.txt is set (never its content).
    POST /cookies   replaces cookies.txt (raw Netscape export body); an
                    empty body removes it.
    """

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _json(self, status, data):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        return self.rfile.read(length)

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        if self.path == "/watched":
            # The page merges this into its localStorage watched set, so
            # marks sync across browsers and the server stays the source
            # of truth.
            with _watched_lock:
                self._json(200, {"ids": sorted(load_watched())})
        elif self.path == "/config":
            try:
                body = CONFIG_FILE.read_bytes()
            except OSError as e:
                self._json(500, {"error": str(e)})
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self._cors()
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/cookies":
            # Report only whether cookies are set — never the content:
            # this API is unauthenticated, and cookies are a session secret.
            lines = 0
            if COOKIES_FILE.exists():
                try:
                    lines = sum(
                        1 for line in
                        COOKIES_FILE.read_text(encoding="utf-8").splitlines()
                        if line.strip() and not line.startswith("#")
                    )
                except OSError:
                    pass
            self._json(200, {"set": COOKIES_FILE.exists(), "lines": lines})
        elif self.path == "/downloads":
            with _download_jobs_lock:
                jobs = sorted(_download_jobs.values(),
                              key=lambda j: j["created"], reverse=True)
            self._json(200, {"jobs": jobs})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):
        if self.path == "/watched":
            self._post_watched()
        elif self.path == "/config":
            self._post_config()
        elif self.path == "/download":
            self._post_download()
        elif self.path == "/cookies":
            self._post_cookies()
        else:
            self._json(404, {"error": "not found"})

    def _post_watched(self):
        try:
            data = json.loads(self._read_body() or b"{}")
            video_id = data.get("id", "")
            if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
                raise ValueError(f"bad video id: {video_id!r}")
            with _watched_lock:
                watched = load_watched()
                if data.get("watched"):
                    watched.add(video_id)
                else:
                    watched.discard(video_id)
                save_watched(watched)
            log.info(
                "marked %s: %s",
                "watched" if data.get("watched") else "unwatched", video_id,
            )
            self._json(200, {"ok": True})
        except (ValueError, json.JSONDecodeError) as e:
            log.warning("bad /watched request: %s", e)
            self._json(400, {"error": str(e)})

    def _post_config(self):
        text = self._read_body().decode("utf-8", errors="replace")
        problems = save_config_text(text)
        if problems:
            for problem in problems:
                log.warning("rejected config edit: %s", problem)
            self._json(400, {"problems": problems})
            return
        log.info("subscriptions.yaml updated via API")
        self._json(200, {"ok": True})

    def _post_cookies(self):
        text = self._read_body().decode("utf-8", errors="replace")
        if not text.strip():
            try:
                COOKIES_FILE.unlink(missing_ok=True)
            except OSError as e:
                self._json(500, {"error": str(e)})
                return
            log.info("cookies.txt removed via API")
            self._json(200, {"ok": True, "set": False})
            return
        # Netscape cookies.txt format: 7 tab-separated fields per line.
        cookie_lines = [
            line for line in text.splitlines()
            if line.strip() and not line.startswith("#")
        ]
        if not cookie_lines or any(line.count("\t") < 6 for line in cookie_lines):
            self._json(400, {
                "error": "not a Netscape cookies.txt export "
                         "(each cookie line needs 7 tab-separated fields)",
            })
            return
        try:
            COOKIES_FILE.write_text(text, encoding="utf-8")
            COOKIES_FILE.chmod(0o600)
        except OSError as e:
            self._json(500, {"error": str(e)})
            return
        log.info("cookies.txt updated via API (%d cookie lines)", len(cookie_lines))
        self._json(200, {"ok": True, "set": True, "lines": len(cookie_lines)})

    def _post_download(self):
        try:
            data = json.loads(self._read_body() or b"{}")
        except json.JSONDecodeError as e:
            self._json(400, {"error": str(e)})
            return
        url = str(data.get("url", "")).strip()
        quality = data.get("quality", "")
        if not url.startswith(("http://", "https://")):
            self._json(400, {"error": "url must start with http:// or https://"})
            return
        if quality not in MANUAL_QUALITY_PRESETS:
            self._json(400, {
                "error": "quality must be one of " + ", ".join(sorted(MANUAL_QUALITY_PRESETS)),
            })
            return
        job_id = uuid.uuid4().hex[:8]
        with _download_jobs_lock:
            _download_jobs[job_id] = {
                "id": job_id, "url": url, "quality": quality,
                "status": "running", "error": None, "created": time.time(),
            }
            # Cap the job history; never evict a still-running job.
            while len(_download_jobs) > MAX_DOWNLOAD_JOBS:
                oldest = min(_download_jobs,
                             key=lambda k: _download_jobs[k]["created"])
                if _download_jobs[oldest]["status"] == "running":
                    break
                del _download_jobs[oldest]
        settings = load_config().get("settings", {})
        thread = threading.Thread(
            target=run_download_job, args=(job_id, url, quality, settings),
            daemon=True,
        )
        thread.start()
        log.info("manual download job %s started: %s (%s)", job_id, url, quality)
        self._json(202, {"job_id": job_id})

    def log_message(self, fmt, *args):
        log.debug("api: " + fmt, *args)


def start_api(host, port):
    """Start the HTTP API in a daemon thread."""
    server = ThreadingHTTPServer((host, port), ApiHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    log.info("API listening on %s:%d", host, port)
    return server


# ---------------------------------------------------------------------------
# Telegram notifications
# ---------------------------------------------------------------------------

TELEGRAM_API_URL = "https://api.telegram.org/bot{token}/sendMessage"


def load_telegram_config():
    """Load Telegram credentials from .env; warn once if anything is missing."""
    load_dotenv()
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        log.warning(
            "Telegram notifications disabled: TELEGRAM_BOT_TOKEN and/or "
            "TELEGRAM_CHAT_ID not set in .env"
        )
        return None, None
    return token, chat_id


_cookie_alert_lock = threading.Lock()
_cookie_alert_last = 0.0
# At most one cookie-problem alert per this many seconds.
COOKIE_ALERT_INTERVAL = 12 * 3600


def notify_cookie_problem(stderr, context):
    """Telegram alert when a download fails for auth-type reasons.

    context says whether the failure happened with or without usable
    cookies. Throttled: repeated failures every scan round must not spam.
    """
    if not any(hint in stderr.lower() for hint in AUTH_ERROR_HINTS):
        return
    global _cookie_alert_last
    with _cookie_alert_lock:
        now = time.time()
        if now - _cookie_alert_last < COOKIE_ALERT_INTERVAL:
            return
        _cookie_alert_last = now
    token, chat_id = load_telegram_config()
    if not token or not chat_id:
        return
    send_telegram_message(
        token, chat_id,
        "⚠️ ytwatcher: download failed (" + context + "):\n"
        + stderr.strip()[:200]
        + "\nRefresh cookies.txt if it is missing or expired.",
    )


def send_telegram_message(token, chat_id, text):
    """Send a message; failures are logged but never raised."""
    url = TELEGRAM_API_URL.format(token=token)
    payload = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": True,
    }
    try:
        response = requests.post(url, json=payload, timeout=30)
        response.raise_for_status()
        return True
    except Exception as e:
        # The exception message embeds the request URL, which contains the
        # bot token; mask it before writing to the log/journal.
        safe = str(e).replace(token, "***")
        log.error("failed to send Telegram message: %s", safe)
        return False


def format_download_notification(item):
    return f"{item['channel']}\n{item['title']}\n({format_size(item['size'])})"


def notify_completed_downloads(token, chat_id, completed):
    """Send a single summary message for all videos completed in a round."""
    if not completed or not token or not chat_id:
        return
    if len(completed) == 1:
        header = "📥 New video downloaded"
    else:
        header = f"📥 {len(completed)} new videos downloaded"
    body = "\n\n".join(format_download_notification(item) for item in completed)
    send_telegram_message(token, chat_id, f"{header}\n{body}")


def set_mtime(path, timestamp):
    """Set a file's modification time to the given unix timestamp."""
    try:
        os.utime(path, (time.time(), timestamp))
    except OSError as e:
        log.warning("could not set mtime on %s: %s", path, e)


def fetch_upload_timestamp(video_id):
    """Return the video's YouTube upload time as a unix timestamp, or None.

    The flat-playlist listing doesn't include upload times, so this does
    one extra metadata query per downloaded video.
    """
    cmd = [
        YT_DLP,
        "--skip-download",
        "--print", "%(timestamp)s\t%(upload_date)s",
        f"https://www.youtube.com/watch?v={video_id}",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except Exception as e:
        log.warning("could not fetch upload time for %s: %s", video_id, e)
        return None
    if result.returncode != 0:
        log.warning(
            "could not fetch upload time for %s: %s",
            video_id, result.stderr.strip()[:200],
        )
        return None
    parts = result.stdout.strip().split("\t")
    try:
        return int(float(parts[0]))
    except (ValueError, IndexError):
        pass
    if len(parts) > 1:
        # Fall back to upload_date (YYYYMMDD) when no exact timestamp.
        try:
            return int(datetime.strptime(parts[1].strip(), "%Y%m%d").timestamp())
        except ValueError:
            pass
    return None


def run_yt_dlp(cmd):
    """Run a yt-dlp download command; retry once with cookies.txt on failure.

    Some videos (members-only, age-restricted, bot-checked) only download
    with a logged-in session. Returns the CompletedProcess of the last
    attempt. Raises subprocess.TimeoutExpired like subprocess.run.
    """
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
    if result.returncode == 0:
        return result
    # Log the real error before any retry: the retry's stderr replaces it
    # in the returned result and would otherwise hide it.
    log.info("download failed (first attempt): %s", result.stderr.strip()[:300])
    # Skip the retry when cookies.txt is empty: yt-dlp rejects it ("does
    # not look like a Netscape format cookies file"), masking the
    # original failure.
    if COOKIES_FILE.exists() and COOKIES_FILE.stat().st_size > 0:
        log.info("retrying with cookies from %s", COOKIES_FILE.name)
        result = subprocess.run(
            cmd + ["--cookies", str(COOKIES_FILE)],
            capture_output=True, text=True, timeout=3600,
        )
        if result.returncode != 0:
            notify_cookie_problem(result.stderr, "even with cookies.txt")
    else:
        notify_cookie_problem(result.stderr,
                              "cookies.txt is missing or empty")
    return result


def download_video(sub, video, download_dir):
    """Download a subscription video.

    Returns (status, file path, duration). status is "ok", "failed",
    "members_only", or "live"; path and duration are None unless "ok".
    """
    out_dir = Path(download_dir) / sub["name"]
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        YT_DLP,
        "-f", sub["quality"],
        # Truncate the title to 200 BYTES: CJK titles are 3 bytes/char and
        # would otherwise exceed the 255-byte filename limit (Errno 36).
        "-o", str(out_dir / "%(title).200B [%(id)s].%(ext)s"),
        "--no-playlist",
        "--print", "after_move:%(filepath)s\t%(duration)s",
        f"https://www.youtube.com/watch?v={video['id']}",
    ]
    result = run_yt_dlp(cmd)
    if result.returncode != 0:
        if is_members_only_error(result.stderr):
            return "members_only", None, None
        if is_live_error(result.stderr):
            return "live", None, None
        log.error(
            "[%s] download FAILED for %s: %s",
            sub["name"], video["id"], result.stderr.strip()[:300],
        )
        return "failed", None, None
    # Locate the finished file by the video id embedded in its name.
    downloaded = None
    for f in out_dir.iterdir():
        if video["id"] in f.name and is_video_file(f):
            downloaded = f
            break
    if downloaded is None:
        # yt-dlp exited 0 but the file isn't there — treat as a failed
        # download so the next round retries it.
        log.warning(
            "[%s] could not locate downloaded file for %s, will retry",
            sub["name"], video["id"],
        )
        return "failed", None, None
    return "ok", downloaded, parse_duration_print(result.stdout)


def download_manually(url, out_dir, fmt=None, sort=None):
    """Download url into out_dir via yt-dlp.

    Returns (video_id, file path) on success, else None. The finished
    file's path is taken from yt-dlp's after_move printout — a plain
    "--print id" can't be used here because it implies --skip-download.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        YT_DLP,
        "--no-playlist",
        "--print", "after_move:%(filepath)s\t%(duration)s",
        "-o", str(out_dir / "%(title).200B [%(id)s].%(ext)s"),
    ]
    if fmt:
        cmd += ["-f", fmt]
    if sort:
        cmd += ["-S", sort]
    cmd.append(url)
    log.info("running: %s", " ".join(cmd))
    try:
        result = run_yt_dlp(cmd)
    except subprocess.TimeoutExpired:
        log.error("download timed out for %s", url)
        return None
    if result.returncode != 0:
        log.error("download failed for %s:\n%s", url, result.stderr.strip()[:500])
        return None
    downloaded = None
    for line in result.stdout.splitlines():
        path_str, _, _ = line.rpartition("\t")
        path = Path(path_str.strip())
        if path.is_file() and path.parent == out_dir and is_video_file(path):
            downloaded = path
    if downloaded is None:
        log.error("yt-dlp exited 0 for %s but the file was not found", url)
        return None
    match = VIDEO_ID_RE.search(downloaded.name)
    if not match:
        log.warning("downloaded %s but the filename has no video ID", url)
        return None
    # Like watcher downloads, the file's date should reflect the YouTube
    # upload time, not the download time.
    timestamp = fetch_upload_timestamp(match.group(1))
    if timestamp:
        set_mtime(downloaded, timestamp)
    # out_dir is download_dir/manually, so its parent is the index root.
    record_duration(out_dir.parent, downloaded,
                    parse_duration_print(result.stdout))
    return match.group(1), downloaded


def record_manual_download(video_id, settings):
    """Record a manually downloaded video: mark it seen and rebuild the index.

    The ID goes into state.json so the watcher never re-downloads the
    video, even after the file is deleted via a watched mark.
    """
    with _state_lock:
        seen = load_state()
        seen.add(video_id)
        save_state(seen)
    update_index_html(
        settings.get("download_dir", "/srv/files"),
        api_port=settings.get("api_port", DEFAULT_API_PORT),
        site_title=settings.get("site_title", DEFAULT_SITE_TITLE),
        max_age_days=settings.get("watchlist_max_age_days"),
    )


def run_download_job(job_id, url, quality, settings):
    """Run a manual download job from the API in a background thread."""
    fmt = MANUAL_QUALITY_PRESETS[quality]
    out_dir = Path(settings.get("download_dir", "/srv/files")) / "manually"
    error = None
    try:
        result = download_manually(url, out_dir, fmt=fmt)
    except Exception as e:
        result = None
        error = str(e)
        log.error("manual download job %s errored: %s", job_id, e)
    with _download_jobs_lock:
        job = _download_jobs.get(job_id)
        if job is not None:
            if result is None:
                job["status"] = "failed"
                job["error"] = error or "download failed (see service log)"
            else:
                job["status"] = "done"
                job["video_id"] = result[0]
    if result is not None:
        record_manual_download(result[0], settings)
        log.info("manual download job %s done: %s", job_id, result[0])


def save_config_text(text):
    """Validate raw YAML text and atomically replace subscriptions.yaml.

    Returns a list of problems found; empty means the config was saved.
    """
    try:
        config = yaml.safe_load(text)
    except yaml.YAMLError as e:
        return [f"invalid YAML: {e}"]
    problems = validate_config(config)
    if problems:
        return problems
    tmp = CONFIG_FILE.with_suffix(".yaml.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    tmp.replace(CONFIG_FILE)
    return []


def fetch_description(video_id):
    """Return the video's description text, or None on failure.

    The flat-playlist listing doesn't include descriptions, so this does
    one extra metadata query. Used to give videos whose title doesn't
    match a second chance via their description.
    """
    cmd = [
        YT_DLP,
        "--skip-download",
        "--print", "%(description)s",
        f"https://www.youtube.com/watch?v={video_id}",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except Exception as e:
        log.warning("could not fetch description for %s: %s", video_id, e)
        return None
    if result.returncode != 0:
        log.warning(
            "could not fetch description for %s: %s",
            video_id, result.stderr.strip()[:200],
        )
        return None
    return result.stdout


def is_too_old(video, settings, now):
    """Return True if the video is older than settings.max_video_age_days.

    Videos with unknown upload times are not treated as old, to avoid
    skipping new videos on missing metadata.
    """
    max_age_days = settings.get("max_video_age_days")
    if not max_age_days:
        return False
    timestamp = video.get("timestamp")
    if timestamp is None:
        return False
    return now - timestamp > max_age_days * 86400


def process_subscription(sub, settings, seen, failed, scan_only=False):
    name = sub["name"]
    completed = []
    limit = settings.get("recent_videos_to_scan", 10)
    now = time.time()
    urls = sub["url"]
    if isinstance(urls, str):
        urls = [urls]
    videos = []
    seen_ids = set()
    for url in urls:
        try:
            for video in fetch_recent_videos(url, limit):
                if video["id"] not in seen_ids:
                    seen_ids.add(video["id"])
                    videos.append(video)
        except Exception as e:
            log.error("[%s] failed to list videos from %s: %s", name, url, e)

    log.info("[%s] scanned %d recent videos", name, len(videos))
    for video in videos:
        if video["id"] in seen:
            log.info("[%s] skipped (already seen): %s", name, video["title"])
            continue
        if video.get("live_status") in LIVE_PENDING_STATUSES:
            # Stream hasn't ended yet. Don't mark as seen so the next
            # round retries until the VOD becomes downloadable. Checked
            # before everything else: for live/upcoming streams the flat
            # listing reports bogus metadata (e.g. tiny durations) that
            # would otherwise trigger the shorts or age filters and skip
            # the video permanently.
            log.info("[%s] still live, will retry: %s", name, video["title"])
            continue
        # Flat-playlist entries carry no upload time (yt-dlp prints NA), so
        # fetch it lazily for unseen videos; otherwise max_video_age_days
        # would silently never apply.
        if video["timestamp"] is None and settings.get("max_video_age_days"):
            video["timestamp"] = fetch_upload_timestamp(video["id"])
        if is_too_old(video, settings, now):
            log.info("[%s] skipped (older than %s days): %s",
                     name, settings.get("max_video_age_days"), video["title"])
            if not scan_only:
                seen.add(video["id"])
            continue
        if video.get("availability") in MEMBERS_ONLY_AVAILABILITY:
            log.info("[%s] skipped (members only): %s", name, video["title"])
            if not scan_only:
                seen.add(video["id"])
            continue
        if is_short(video, sub):
            log.info("[%s] skipped (short): %s", name, video["title"])
            if not scan_only:
                seen.add(video["id"])
            continue
        if not matches(sub, video["title"]):
            # Title didn't match. Keyword-based subscriptions can get a
            # second chance via the video description (one extra metadata
            # query); enable per subscription with match_description: true.
            # Only the fixed match keywords count here — watchlist
            # tickers/company names are title-only (see matches_keywords).
            description_matched = False
            if (sub.get("match_description", False)
                    and sub.get("match", "all") != "all"):
                description = fetch_description(video["id"])
                if description and matches_keywords(sub, description,
                                                    include_watchlist=False):
                    description_matched = True
                    log.info("[%s] matched in description: %s", name, video["title"])
            if not description_matched:
                log.info("[%s] new, no match: %s", name, video["title"])
                if not scan_only:
                    seen.add(video["id"])
                continue
        if scan_only:
            log.info("[%s] new, MATCHED (would download): %s", name, video["title"])
            continue
        # Mark as seen regardless of download outcome so we never
        # re-evaluate this video. Failures are un-marked below so the
        # next round retries them (up to MAX_DOWNLOAD_ATTEMPTS times;
        # live streams retry without a cap).
        seen.add(video["id"])
        log.info("[%s] matched: %s", name, video["title"])
        log.info("[%s] downloading: %s", name, video["title"])
        try:
            status, downloaded, duration = download_video(
                sub, video, settings["download_dir"])
            if status == "ok":
                failed.pop(video["id"], None)
                if downloaded:
                    # File date/time should reflect the YouTube upload
                    # time, not the download time.
                    timestamp = video.get("timestamp") or fetch_upload_timestamp(video["id"])
                    if timestamp:
                        set_mtime(downloaded, timestamp)
                    record_duration(settings["download_dir"], downloaded, duration)
                size = downloaded.stat().st_size if downloaded else 0
                completed.append({
                    "channel": name,
                    "title": video["title"],
                    "size": size,
                })
                log.info("[%s] done: %s", name, video["title"])
            elif status == "members_only":
                # Channel membership often only means early access — the
                # video may become public later (e.g. bilibili donghua).
                # Keep retrying; in practice bounded by the recent-videos
                # scan window, which the video eventually ages out of.
                seen.discard(video["id"])
                log.info("[%s] members only (for now), will retry: %s",
                         name, video["title"])
            elif status == "live":
                # Still live despite the listing; retry next round.
                # Live retries are uncapped: a stream can legitimately
                # run for hours before its VOD becomes downloadable.
                seen.discard(video["id"])
                log.info("[%s] still live, will retry: %s", name, video["title"])
            elif status == "failed":
                note_download_failure(name, video, failed, seen)
        except Exception as e:
            note_download_failure(name, video, failed, seen)
            log.error("[%s] download error for %s: %s", name, video["id"], e)
    return completed


def run_round(config, seen, scan_only=False, telegram_token=None, telegram_chat_id=None):
    settings = config.get("settings", {})
    subs = config.get("subscriptions", [])
    mode = "scan-only" if scan_only else "scan"
    log.info("=== %s round started: %d subscriptions ===", mode, len(subs))
    completed = []
    failed = load_failed()
    if not scan_only:
        # Delete (or archive, for keep_watched subscriptions) files the
        # user marked as watched since the last round.
        download_dir = settings.get("download_dir", "/srv/files")
        keep_channels = {s["name"] for s in subs
                         if s.get("keep_watched") and "name" in s}
        removed = delete_watched_videos(download_dir, load_watched(), keep_channels)
        if removed:
            log.info("removed %d watched video(s)", removed)
            try:
                update_index_html(
                    download_dir,
                    api_port=settings.get("api_port", DEFAULT_API_PORT),
                    site_title=settings.get("site_title", DEFAULT_SITE_TITLE),
                    max_age_days=settings.get("watchlist_max_age_days"),
                )
            except Exception as e:
                log.error("failed to update index.html: %s", e)
    for sub in subs:
        try:
            completed.extend(
                process_subscription(sub, settings, seen, failed, scan_only=scan_only)
            )
        except Exception as e:
            log.error("[%s] unexpected error: %s", sub.get("name", "?"), e)
    if not scan_only:
        with _state_lock:
            # Merge in IDs recorded by manual downloads that finished while
            # this round was running, so they aren't lost from state.json.
            seen |= load_state()
            save_state(seen)
        save_failed(failed)
        if completed:
            try:
                update_index_html(
                    settings.get("download_dir", "/srv/files"),
                    api_port=settings.get("api_port", DEFAULT_API_PORT),
                    site_title=settings.get("site_title", DEFAULT_SITE_TITLE),
                    max_age_days=settings.get("watchlist_max_age_days"),
                )
            except Exception as e:
                log.error("failed to update index.html: %s", e)
            try:
                notify_completed_downloads(telegram_token, telegram_chat_id, completed)
            except Exception as e:
                log.error("failed to send Telegram notification: %s", e)
    log.info("=== %s round finished ===", mode)
    return completed


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
    parser.add_argument(
        "--generate-index", action="store_true",
        help="regenerate download_dir/index.html from existing files and exit",
    )
    parser.add_argument(
        "--test-notify", action="store_true",
        help="send a test Telegram message and exit",
    )
    parser.add_argument(
        "--check", action="store_true",
        help="validate subscriptions.yaml and exit",
    )
    args = parser.parse_args()

    if args.check:
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f)
        except (OSError, yaml.YAMLError) as e:
            log.error("%s: %s", CONFIG_FILE.name, e)
            return 1
        problems = validate_config(config)
        for problem in problems:
            log.error("%s: %s", CONFIG_FILE.name, problem)
        if problems:
            return 1
        log.info("%s: OK", CONFIG_FILE.name)
        return 0

    config = load_config()
    settings = config.get("settings", {})
    interval = settings.get("check_interval_minutes", 30)
    download_dir = settings.get("download_dir", "/srv/files")
    api_host = settings.get("api_host", "0.0.0.0")
    api_port = settings.get("api_port", DEFAULT_API_PORT)
    site_title = settings.get("site_title", DEFAULT_SITE_TITLE)
    telegram_token, telegram_chat_id = load_telegram_config()

    if args.scan:
        run_round(config, load_state(), scan_only=True)
        return 0

    if args.generate_index:
        update_index_html(download_dir, api_port=api_port, site_title=site_title,
                          max_age_days=settings.get("watchlist_max_age_days"))
        return 0

    if args.test_notify:
        if not telegram_token or not telegram_chat_id:
            log.warning("cannot send test notification: Telegram credentials missing")
            return 1
        text = "📥 Test notification from ytwatcher\nYour notification setup is working."
        if send_telegram_message(telegram_token, telegram_chat_id, text):
            log.info("test notification sent")
            return 0
        return 1

    if args.once:
        run_round(config, load_state(), telegram_token=telegram_token, telegram_chat_id=telegram_chat_id)
        return 0

    # Start the HTTP API backing the index page (watched marks, config
    # editing, manual downloads).
    try:
        start_api(api_host, api_port)
    except Exception as e:
        log.error("API failed to start: %s", e)

    # Generate the initial index once at startup so an existing library is
    # browseable before the first new download completes.
    try:
        update_index_html(download_dir, api_port=api_port, site_title=site_title,
                          max_age_days=settings.get("watchlist_max_age_days"))
    except Exception as e:
        log.error("failed to generate initial index.html: %s", e)

    log.info("starting watcher loop (every %d minutes)", interval)
    while True:
        try:
            # Re-read subscriptions.yaml every round so edits take effect
            # without restarting the service.
            config = load_config()
            interval = config.get("settings", {}).get("check_interval_minutes", 30)
            run_round(config, load_state(), telegram_token=telegram_token, telegram_chat_id=telegram_chat_id)
        except Exception as e:
            log.error("scan round failed: %s", e)
        time.sleep(interval * 60)


if __name__ == "__main__":
    sys.exit(main() or 0)
