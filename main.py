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

# Download attempts before a failing video is marked as seen for good.
MAX_DOWNLOAD_ATTEMPTS = 5

# Port for the tiny HTTP endpoint that receives "watched" marks from the
# browser. Overridable via settings.api_port in subscriptions.yaml.
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
                    "api_port", "max_video_age_days"):
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
        exclude = sub.get("exclude", [])
        if not (isinstance(exclude, list)
                and all(isinstance(kw, str) for kw in exclude)):
            problems.append(f"{label}: 'exclude' must be a list of keywords")
        if "shorts_max_duration" in sub and not isinstance(
            sub["shorts_max_duration"], (int, float)
        ):
            problems.append(f"{label}: 'shorts_max_duration' must be a number")
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


def matches_keywords(sub, text):
    """Return True if text contains any of the subscription's match keywords.

    A subscription with match: all (or no match list) matches everything.
    """
    match = sub.get("match", "all")
    if match == "all":
        return True
    text_lower = text.lower()
    return any(kw.lower() in text_lower for kw in match)


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
    """Return True for completed video files under download_dir."""
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


def scan_downloads(download_dir):
    """Scan download_dir recursively and group video files by top-level subfolder.

    Returns an ordered dict mapping channel/subfolder name to a list of
    entries sorted newest-first by file mtime. Each entry is a dict with
    keys: rel, name, size, mtime, channel.
    """
    root = Path(download_dir)
    if not root.is_dir():
        return {}
    groups = {}
    for path in root.rglob("*"):
        if not is_video_file(path):
            continue
        rel = path.relative_to(root)
        if len(rel.parts) > 1:
            channel = rel.parts[0]
        else:
            channel = "(root)"
        stat = path.stat()
        groups.setdefault(channel, []).append({
            "rel": rel.as_posix(),
            "name": path.name,
            "size": stat.st_size,
            "mtime": stat.st_mtime,
            "channel": channel,
        })
    for entries in groups.values():
        entries.sort(key=lambda e: e["mtime"], reverse=True)
    return dict(sorted(groups.items(), key=lambda kv: kv[0].casefold()))


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
    return hashlib.sha1((site_title + "\n" + canonical).encode("utf-8")).hexdigest()


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
        "      align-items: flex-start;",
        "      gap: 1rem;",
        "      padding: .75rem;",
        "      border-bottom: 1px solid #2a2a2a;",
        "    }",
        "    li:last-child { border-bottom: none; }",
        "    a { color: #8ab4f8; text-decoration: none; word-break: break-word; flex: 1; }",
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
        "    li.watched { opacity: .45; }",
        "    li.watched a { text-decoration: line-through; }",
        "    li.watched .watch-btn { color: #7bd88a; border-color: #7bd88a; }",
        "    footer { margin-top: 2rem; padding-top: 1rem; border-top: 1px solid #333; color: #888; font-size: .85rem; text-align: center; }",
        "    @media (max-width: 600px) {",
        "      li { flex-direction: column; gap: .25rem; }",
        "      .meta { text-align: left; white-space: normal; }",
        "    }",
        "  </style>",
        "</head>",
        "<body>",
        '  <div class="container">',
        "    <header>",
        f"      <h1>{escaped_title}</h1>",
        f"      <p>Last updated: {html.escape(now_str)} &mdash; {total} video(s) across {channels} channel(s)</p>",
        "    </header>",
    ]

    def entry_lines(entry, show_channel=False):
        href = urllib.parse.quote(entry["rel"], safe="/")
        size = format_size(entry["size"])
        mtime_str = datetime.fromtimestamp(entry["mtime"]).strftime("%Y-%m-%d %H:%M")
        meta_parts = [mtime_str, size]
        if show_channel:
            meta_parts.insert(0, html.escape(entry.get("channel", "")))
        data_attr = f' data-id="{entry_id(entry)}"'
        watch_btn = (
            '          <button class="watch-btn" type="button">Mark watched</button>'
        )
        return [line for line in [
            f"        <li{data_attr}>",
            (
                f'          <a href="{href}" title="{html.escape(entry["name"])}">'
                f"{html.escape(entry['name'])}</a>"
            ),
            watch_btn,
            f'          <span class="meta">{" &middot; ".join(meta_parts)}</span>',
            "        </li>",
        ] if line]

    if latest:
        lines.append('    <section class="channel latest">')
        lines.append('      <h2>🆕 Latest</h2>')
        lines.append('      <ul>')
        for entry in latest:
            lines.extend(entry_lines(entry, show_channel=True))
        lines.append('      </ul>')
        lines.append('    </section>')

    for channel, entries in groups.items():
        lines.append('    <section class="channel">')
        lines.append(f"      <h2>{html.escape(channel)}</h2>")
        lines.append("      <ul>")
        for entry in entries:
            lines.extend(entry_lines(entry))
        lines.append("      </ul>")
        lines.append("    </section>")
    lines.extend([
        "    <footer>Generated by ytwatcher</footer>",
        "  </div>",
        f"<!-- index-fingerprint: {fp} -->",
        "<script>",
        "(function () {",
        '  var KEY = "ytwatcher:watched";',
        "  function load() {",
        "    try { return new Set(JSON.parse(localStorage.getItem(KEY) || '[]')); }",
        "    catch (e) { return new Set(); }",
        "  }",
        "  function save(s) { localStorage.setItem(KEY, JSON.stringify(Array.from(s))); }",
        "  var watched = load();",
        "  function report(id, isWatched) {",
        '    fetch("http://" + location.hostname + ":' + str(api_port) + '/watched", {',
        '      method: "POST",',
        '      headers: { "Content-Type": "text/plain" },',
        '      body: JSON.stringify({ id: id, watched: isWatched }),',
        "    }).catch(function () {});",
        "  }",
        "  var applyFns = [];",
        "  function applyAll() { applyFns.forEach(function (fn) { fn(); }); }",
        '  document.querySelectorAll("ul").forEach(function (ul) {',
        '    var items = Array.prototype.slice.call(ul.querySelectorAll("li[data-id]"));',
        "    if (!items.length) return;",
        "    var original = items.slice();",
        "    function apply() {",
        "      original.forEach(function (li) {",
        "        var isWatched = watched.has(li.dataset.id);",
        '        li.classList.toggle("watched", isWatched);',
        '        li.querySelector(".watch-btn").textContent = isWatched ? "\\u2713 Watched" : "Mark watched";',
        "      });",
        "      original.filter(function (li) { return !watched.has(li.dataset.id); })",
        "        .concat(original.filter(function (li) { return watched.has(li.dataset.id); }))",
        "        .forEach(function (li) { ul.appendChild(li); });",
        "    }",
        "    applyFns.push(apply);",
        "    items.forEach(function (li) {",
        '      li.querySelector(".watch-btn").addEventListener("click", function () {',
        "        var id = li.dataset.id;",
        "        var isWatched = !watched.has(id);",
        "        if (isWatched) { watched.add(id); } else { watched.delete(id); }",
        "        save(watched);",
        "        report(id, isWatched);",
        "        applyAll();",
        "      });",
        "    });",
        "  });",
        "  applyAll();",
        "})();",
        "</script>",
        "</body>",
        "</html>",
    ])
    return "\n".join(lines)


def update_index_html(download_dir, api_port=DEFAULT_API_PORT, site_title=DEFAULT_SITE_TITLE):
    """Regenerate download_dir/index.html if the file listing has changed.

    The page is always built from a full recursive scan of download_dir, so
    deleted files disappear automatically.
    """
    groups = scan_downloads(download_dir)
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
    tmp = index_path.with_suffix(".html.tmp")
    tmp.write_text(html_content, encoding="utf-8")
    tmp.replace(index_path)
    log.info("index.html updated (%d videos across %d channels)", total, channels)
    return True, total, channels


# ---------------------------------------------------------------------------
# Watched marks: HTTP endpoint + deletion
# ---------------------------------------------------------------------------


def delete_watched_videos(download_dir, watched_ids):
    """Delete downloaded files whose video ID is in watched_ids.

    Returns the number of files deleted. The index page is rebuilt from a
    full scan, so deleted files disappear from it automatically.
    """
    if not watched_ids:
        return 0
    root = Path(download_dir)
    if not root.is_dir():
        return 0
    deleted = 0
    for path in root.rglob("*"):
        if not is_video_file(path):
            continue
        id_match = VIDEO_ID_RE.search(path.name)
        if id_match and id_match.group(1) in watched_ids:
            try:
                path.unlink()
                deleted += 1
                log.info("deleted watched video: %s", path.name)
            except OSError as e:
                log.error("failed to delete %s: %s", path, e)
    return deleted


class WatchedHandler(BaseHTTPRequestHandler):
    """Receives watched/unwatched marks from the index page.

    POST /watched with a JSON body {"id": "<video id>", "watched": true}
    adds or removes the ID in watched.json. Nothing here deletes files;
    deletion happens at the start of the next scan round, so an accidental
    mark can be undone before the round runs.
    """

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_POST(self):
        if self.path != "/watched":
            self.send_response(404)
            self._cors()
            self.end_headers()
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(length) or b"{}")
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
            self.send_response(200)
        except (ValueError, json.JSONDecodeError) as e:
            log.warning("bad /watched request: %s", e)
            self.send_response(400)
        self._cors()
        self.end_headers()

    def log_message(self, fmt, *args):
        log.debug("watched-api: " + fmt, *args)


def start_watched_api(host, port):
    """Start the watched-mark endpoint in a daemon thread."""
    server = ThreadingHTTPServer((host, port), WatchedHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    log.info("watched-mark API listening on %s:%d", host, port)
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


def download_video(sub, video, download_dir):
    out_dir = Path(download_dir) / sub["name"]
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        YT_DLP,
        "-f", sub["quality"],
        "-o", str(out_dir / "%(title)s [%(id)s].%(ext)s"),
        "--no-playlist",
        f"https://www.youtube.com/watch?v={video['id']}",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
    if result.returncode != 0:
        if is_members_only_error(result.stderr):
            return "members_only", None
        if is_live_error(result.stderr):
            return "live", None
        log.error(
            "[%s] download FAILED for %s: %s",
            sub["name"], video["id"], result.stderr.strip()[:300],
        )
        return "failed", None
    # Locate the finished file by the video id embedded in its name.
    downloaded = None
    for f in out_dir.iterdir():
        if video["id"] in f.name and is_video_file(f):
            downloaded = f
            break
    if downloaded is None:
        log.warning(
            "[%s] could not locate downloaded file for %s",
            sub["name"], video["id"],
        )
    return "ok", downloaded


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
            # Title didn't match. Keyword-based subscriptions get a second
            # chance via the video description (one extra metadata query);
            # disable per subscription with match_description: false.
            description_matched = False
            if (sub.get("match_description", True)
                    and sub.get("match", "all") != "all"):
                description = fetch_description(video["id"])
                if description and matches_keywords(sub, description):
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
            status, downloaded = download_video(sub, video, settings["download_dir"])
            if status == "ok":
                failed.pop(video["id"], None)
                if downloaded:
                    # File date/time should reflect the YouTube upload
                    # time, not the download time.
                    timestamp = video.get("timestamp") or fetch_upload_timestamp(video["id"])
                    if timestamp:
                        set_mtime(downloaded, timestamp)
                size = downloaded.stat().st_size if downloaded else 0
                completed.append({
                    "channel": name,
                    "title": video["title"],
                    "size": size,
                })
                log.info("[%s] done: %s", name, video["title"])
            elif status == "members_only":
                log.info("[%s] skipped (members only): %s", name, video["title"])
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
        # Delete files the user marked as watched since the last round.
        download_dir = settings.get("download_dir", "/srv/files")
        deleted = delete_watched_videos(download_dir, load_watched())
        if deleted:
            log.info("deleted %d watched video(s)", deleted)
            try:
                update_index_html(
                    download_dir,
                    api_port=settings.get("api_port", DEFAULT_API_PORT),
                    site_title=settings.get("site_title", DEFAULT_SITE_TITLE),
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
        save_state(seen)
        save_failed(failed)
        if completed:
            try:
                update_index_html(
                    settings.get("download_dir", "/srv/files"),
                    api_port=settings.get("api_port", DEFAULT_API_PORT),
                    site_title=settings.get("site_title", DEFAULT_SITE_TITLE),
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
        update_index_html(download_dir, api_port=api_port, site_title=site_title)
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

    # Start the endpoint that receives watched marks from the index page.
    try:
        start_watched_api(api_host, api_port)
    except Exception as e:
        log.error("watched-mark API failed to start: %s", e)

    # Generate the initial index once at startup so an existing library is
    # browseable before the first new download completes.
    try:
        update_index_html(download_dir, api_port=api_port, site_title=site_title)
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
