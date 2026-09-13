import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import main
from yt_dlp import YoutubeDL


@pytest.mark.parametrize("info,expected", [
    ({"automatic_captions": {"en": [1], "de-orig": [1], "de": [1]}}, "de-orig"),
    ({"subtitles": {"de": [1]}, "automatic_captions": {"de-orig": [1]}}, "de"),
    ({"language": "de", "subtitles": {"en": [1], "de": [1]}}, "de"),
    ({"subtitles": {"es": [1]}, "automatic_captions": {"en": [1]}}, "es"),
    ({"automatic_captions": {"fr": [1], "en": [1]}}, "en"),
    ({"automatic_captions": {"fr": [1]}}, "fr"),
])
def test_original_subtitle_language(info, expected):
    assert main.original_subtitle_language(info) == expected


def test_original_subtitle_language_missing():
    with pytest.raises(RuntimeError, match="No published"):
        main.original_subtitle_language({"subtitles": {"live_chat": [1]}})


@pytest.mark.parametrize("published", [True, False])
def test_published_captions_preferred_with_auto_fallback(published):
    normal = {"en": [{"ext": "vtt", "url": "https://example.com/manual"}]} if published else {}
    automatic = {"en": [{"ext": "vtt", "url": "https://example.com/auto"}]}
    with YoutubeDL({"writesubtitles": True, "writeautomaticsub": True,
                    "subtitleslangs": ["en.*"], "subtitlesformat": "vtt",
                    "quiet": True}) as ydl:
        chosen = ydl.process_subtitles("abcdefghijk", normal, automatic)
    assert chosen["en"]["url"].endswith("manual" if published else "auto")


@pytest.mark.parametrize("available,returncode", [(True, 0), (True, 1), (False, 0), (False, 1)])
def test_subtitle_worker(tmp_path, monkeypatch, available, returncode):
    path = tmp_path / "100% title [abcdefghijk].webm"
    path.write_bytes(b"original media")
    monkeypatch.setattr(main, "_download_jobs", {"job": {"status": "running"}})

    def download(cmd, **kwargs):
        assert "--skip-download" in cmd
        assert "--ignore-errors" in cmd
        assert "--write-subs" in cmd and "--write-auto-subs" in cmd
        assert cmd[cmd.index("--sub-langs") + 1] == "es.*"
        if available:
            output = Path(cmd[cmd.index("-o") + 1].replace("%(ext)s", "es.vtt"))
            output.write_text("WEBVTT\n\n00:00.000 --> 00:01.000\nHola\n")
        return SimpleNamespace(returncode=returncode)

    rebuild = Mock(side_effect=lambda *a, **k: main._download_jobs["job"]["status"] == "running")
    monkeypatch.setattr(main, "run_yt_dlp", download)
    monkeypatch.setattr(main, "update_index_html", rebuild)
    main.run_subtitle_download_job("job", path, "abcdefghijk", {"download_dir": str(tmp_path)}, "es.*")
    assert path.read_bytes() == b"original media"
    assert main._download_jobs["job"]["status"] == ("done" if available else "failed")
    assert path.with_suffix(".es.vtt").exists() == available
    assert rebuild.call_count == int(available)


def test_subtitle_api_uses_config_and_rejects_escape(tmp_path, monkeypatch):
    folder = tmp_path / "Espanol"
    folder.mkdir()
    media = folder / "Title [abcdefghijk].webm"
    media.touch()
    monkeypatch.setattr(main, "load_config", lambda: {
        "settings": {"download_dir": str(tmp_path)},
        "subscriptions": [{"name": "Espanol", "subtitles": ["es", "es-419"]}]})
    monkeypatch.setattr(main, "_download_jobs", {})
    thread = Mock()
    monkeypatch.setattr(main.threading, "Thread", thread)
    handler = object.__new__(main.ApiHandler)
    handler._json = Mock()
    handler._read_body = lambda: json.dumps({"rel": str(media.relative_to(tmp_path))}).encode()
    handler._post_video_upgrade(subtitles=True)
    assert handler._json.call_args.args[0] == 202
    assert thread.call_args.kwargs["target"] == main.run_subtitle_download_job
    assert thread.call_args.kwargs["args"][-1] == "es,es-419"
    handler._post_video_upgrade(subtitles=True)
    assert handler._json.call_args.args[0] == 409
    handler._read_body = lambda: b'{"rel": "../outside.webm"}'
    handler._post_video_upgrade(subtitles=True)
    assert handler._json.call_args.args[0] == 400


@pytest.mark.parametrize("has_subtitles", [False, True])
def test_subtitle_button_in_both_sections(has_subtitles):
    entry = {"name": "Title [mabcdefghij].webm", "rel": "C/Title [mabcdefghij].webm",
             "size": 1, "mtime": 1, "has_video": True, "channel": "C",
             "subs": {"en": "C/Title [mabcdefghij].en.vtt"} if has_subtitles else {}}
    page = main.generate_index_html({"C": [entry]}, 1, 1, "now", "fp", latest=[entry])
    assert page.count('class="watch-btn subtitle-download"') == 2
    assert "⇩ Subtitles" in page
    assert '"/subtitle-download"' in page
    assert page.count('disabled title="Already has subtitles"') == (2 if has_subtitles else 0)


def test_failed_variant_does_not_block_primary_track(tmp_path, monkeypatch):
    """Exercise yt-dlp's actual track loop with a failing first variant."""
    from yt_dlp.utils import DownloadError
    with YoutubeDL({"writesubtitles": True, "writeautomaticsub": True,
                    "ignoreerrors": True, "quiet": True,
                    "outtmpl": str(tmp_path / "%(id)s.%(ext)s")}) as ydl:
        attempted = []

        def download(filename, info, **kwargs):
            attempted.append(info["url"])
            if info["url"].endswith("variant"):
                raise DownloadError("HTTP Error 429: Too Many Requests")
            Path(filename).write_text("WEBVTT\n\n00:00.000 --> 00:01.000\nHola\n")

        monkeypatch.setattr(ydl, "dl", download)
        info = {"id": "abcdefghijk", "title": "Test", "ext": "webm", "requested_subtitles": {
            "es-en-US": {"ext": "vtt", "url": "https://example.com/variant"},
            "es": {"ext": "vtt", "url": "https://example.com/primary"}}}
        result = ydl._write_subtitles(info, str(tmp_path / "abcdefghijk.webm"))
    assert len(attempted) == 2
    assert len(result) == 1
    assert (tmp_path / "abcdefghijk.es.vtt").read_text().startswith("WEBVTT")
