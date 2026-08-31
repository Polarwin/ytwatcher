"""Unit tests for ytwatcher's pure/helper functions.

Run with: .venv/bin/python -m pytest tests/ -q
"""
import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main  # noqa: E402


# ---------------------------------------------------------------------------
# host_allowed
# ---------------------------------------------------------------------------

PATTERNS = ["192.168.0.0/24", "100.64.0.0/10", "192.168.1.*", "homeserver.lan"]


def test_host_allowed_exact():
    assert main.host_allowed("homeserver.lan", PATTERNS)
    assert main.host_allowed("HOMESERVER.LAN", PATTERNS)  # case-insensitive
    assert not main.host_allowed("other.lan", PATTERNS)


def test_host_allowed_cidr():
    assert main.host_allowed("192.168.0.9", PATTERNS)
    assert main.host_allowed("100.82.220.43", PATTERNS)
    assert not main.host_allowed("10.0.0.5", PATTERNS)
    assert not main.host_allowed("100.63.1.1", PATTERNS)  # below Tailscale range
    assert not main.host_allowed("8.8.8.8", PATTERNS)


def test_host_allowed_wildcard_ip_literals_only():
    assert main.host_allowed("192.168.1.7", PATTERNS)
    # DNS-rebinding gap (audit S1): a hostname that merely starts with the
    # IP prefix must NOT match an IP wildcard.
    assert not main.host_allowed("192.168.1.5.evil.com", PATTERNS)


def test_host_allowed_bare_star_ignored():
    assert not main.host_allowed("anything.example.com", ["*"])
    assert not main.host_allowed("1.2.3.4", ["*"])


def test_host_allowed_hostname_wildcard_ignored():
    # Right-side hostname wildcards are unsupported; only IP prefixes.
    assert not main.host_allowed("example.evil.com", ["example.*"])


# ---------------------------------------------------------------------------
# entry_id / is_pseudo_id
# ---------------------------------------------------------------------------

def test_entry_id_real_id_from_filename():
    entry = {"name": "Title [mAbCdEfGhIj].webm", "rel": "C/Title [mAbCdEfGhIj].webm"}
    assert main.entry_id(entry) == "mAbCdEfGhIj"


def test_entry_id_pseudo_format():
    entry = {"name": "plain.webm", "rel": "C/plain.webm"}
    vid = main.entry_id(entry)
    assert vid.startswith("m_") and len(vid) == 12
    assert vid == "m_" + hashlib.sha1(b"C/plain.webm").hexdigest()[:10]


def test_is_pseudo_id():
    assert main.is_pseudo_id("m_0123abcdef")
    assert main.is_pseudo_id("m0123abcdef")          # legacy format
    assert not main.is_pseudo_id("mAbCdEfGhIj")      # real ID starting with m
    assert not main.is_pseudo_id("m_XYZ1234567")     # 11 chars, not strict
    assert not main.is_pseudo_id("m_0123abcdef0")    # 13 chars, not strict
    assert not main.is_pseudo_id("z0123456789")


def test_video_id_api_re():
    assert main.VIDEO_ID_API_RE.fullmatch("mAbCdEfGhIj")
    assert main.VIDEO_ID_API_RE.fullmatch("m_0123abcdef")
    assert main.VIDEO_ID_API_RE.fullmatch("m0123abcdef")
    assert not main.VIDEO_ID_API_RE.fullmatch("../../etc")
    assert not main.VIDEO_ID_API_RE.fullmatch("")


# ---------------------------------------------------------------------------
# prune_watched_marks / delete_watched_videos / scan_downloads
# ---------------------------------------------------------------------------

def _make_library(tmp_path):
    chan = tmp_path / "Chan"
    chan.mkdir()
    files = {}
    for name in ("Video A [mAbCdEfGhIj].webm", "plain file.webm", "other file.webm"):
        (chan / name).write_text("x")
        files[name] = chan / name
    return files


def _digest(rel):
    return hashlib.sha1(rel.encode()).hexdigest()[:10]


def test_prune_keeps_real_m_id_without_file(tmp_path):
    _make_library(tmp_path)
    watched = {"mZZZZZZZZZZ"}  # real ID, no file -> must survive pruning
    pruned = main.prune_watched_marks(tmp_path, watched)
    assert "mZZZZZZZZZZ" in pruned


def test_prune_live_and_dead_pseudo(tmp_path):
    _make_library(tmp_path)
    live_new = "m_" + _digest("Chan/plain file.webm")
    live_legacy = "m" + _digest("Chan/other file.webm")
    watched = {live_new, live_legacy, "m_" + "0" * 10, "m" + "1" * 10}
    pruned = main.prune_watched_marks(tmp_path, watched)
    assert live_new in pruned
    assert live_legacy in pruned
    assert "m_" + "0" * 10 not in pruned
    assert "m" + "1" * 10 not in pruned


def test_delete_watched_both_pseudo_formats(tmp_path):
    files = _make_library(tmp_path)
    walk = main.walk_video_files(tmp_path)
    assert len(walk) == 3
    watched = {"mAbCdEfGhIj", "m_" + _digest("Chan/plain file.webm"),
               "m" + _digest("Chan/other file.webm")}
    removed = main.delete_watched_videos(tmp_path, watched, files=walk)
    assert len(removed) == 3
    assert all(not f.exists() for f in files.values())


def test_delete_watched_keep_channel_archives(tmp_path):
    files = _make_library(tmp_path)
    removed = main.delete_watched_videos(
        tmp_path, {"mAbCdEfGhIj"}, keep_channels={"Chan"})
    assert len(removed) == 1
    archived = tmp_path / "Chan" / "watched" / "Video A [mAbCdEfGhIj].webm"
    assert archived.exists()
    assert not files["Video A [mAbCdEfGhIj].webm"].exists()


def test_scan_downloads_skips_vanished_files(tmp_path):
    files = _make_library(tmp_path)
    walk = main.walk_video_files(tmp_path)
    files["plain file.webm"].unlink()  # vanish between walk and scan
    groups = main.scan_downloads(tmp_path, files=walk)
    names = [e["name"] for es in groups.values() for e in es]
    assert "plain file.webm" not in names
    assert len(names) == 2


# ---------------------------------------------------------------------------
# parse_flat_playlist
# ---------------------------------------------------------------------------

def test_parse_flat_playlist_basic():
    out = "abcDEF12345\tSome Title\tpublic\t360\tnot_live\t1700000000\t20231114\n"
    (video,) = main.parse_flat_playlist(out)
    assert video["id"] == "abcDEF12345"
    assert video["title"] == "Some Title"
    assert video["availability"] == "public"
    assert video["duration"] == 360
    assert video["live_status"] == "not_live"
    assert video["timestamp"] == 1700000000


def test_parse_flat_playlist_tab_in_title():
    out = "abcDEF12345\tPart 1\tPart 2\tpublic\t360\tnot_live\t1700000000\t20231114\n"
    (video,) = main.parse_flat_playlist(out)
    assert video["title"] == "Part 1\tPart 2"
    assert video["availability"] == "public"
    assert video["duration"] == 360
    assert video["timestamp"] == 1700000000


def test_parse_flat_playlist_upload_date_fallback():
    out = "abcDEF12345\tT\tpublic\tNA\tnot_live\tNA\t20231114\n"
    (video,) = main.parse_flat_playlist(out)
    assert video["duration"] is None
    assert video["timestamp"] is not None  # parsed from upload_date


# ---------------------------------------------------------------------------
# matches / resolve_download_rel
# ---------------------------------------------------------------------------

def test_matches_include_exclude():
    sub = {"match": ["nvda"], "exclude": ["trailer"]}
    assert main.matches(sub, "NVDA earnings explode")
    assert not main.matches(sub, "NVDA trailer leaked")
    assert not main.matches(sub, "unrelated")
    assert main.matches({"match": "all"}, "anything")


def test_resolve_download_rel(tmp_path):
    good = main.resolve_download_rel(tmp_path, "Chan/file.webm")
    assert good is not None and str(good).startswith(str(tmp_path))
    assert main.resolve_download_rel(tmp_path, "../outside.webm") is None
    assert main.resolve_download_rel(tmp_path, "/etc/passwd") is None
    assert main.resolve_download_rel(tmp_path, "Chan/../../etc/passwd") is None


# ---------------------------------------------------------------------------
# _origin_allowed (handler-level, no socket needed)
# ---------------------------------------------------------------------------

def _origin_ok(host, origin=None, allowed=("192.168.0.0/24", "127.0.0.1")):
    handler = main.ApiHandler.__new__(main.ApiHandler)
    main.ApiHandler.allowed_hosts = frozenset(allowed)
    handler.headers = {"Host": host}
    if origin:
        handler.headers["Origin"] = origin
    return handler._origin_allowed()


def test_origin_allowed():
    assert _origin_ok("192.168.0.9:443")
    assert _origin_ok("192.168.0.9:443", "https://192.168.0.9")
    assert not _origin_ok("192.168.0.9:443", "https://evil.com")
    assert not _origin_ok("evil.com", "https://evil.com")  # DNS rebinding


# ---------------------------------------------------------------------------
# _file_creation_time
# ---------------------------------------------------------------------------

def test_file_creation_time(tmp_path):
    f = tmp_path / "x.webm"
    f.write_text("x")
    ctime = main._file_creation_time(f)
    assert ctime > 0
    # binding is cached after first use
    assert main._statx_binding is not None
