import main
import pytest


def test_static_links_rebuild_on_config_change(tmp_path, monkeypatch):
    config = {"static": [{"name": "Learning & Books", "path": "/srv/files/Learning Books"}]}
    monkeypatch.setattr(main, "load_config", lambda: config)
    monkeypatch.setattr(main, "scan_downloads", lambda *a, **k: {})
    monkeypatch.setattr(main, "load_watched", lambda: set())
    assert main.update_index_html(tmp_path)[0]
    page = (tmp_path / "index.html").read_text()
    assert 'href="/ytwatcher/static/Learning%20Books/"' in page
    assert "Learning &amp; Books" in page
    assert not main.update_index_html(tmp_path)[0]
    config["static"].append({"name": "Courses", "path": "/srv/files/Courses", "url": "/courses/"})
    assert main.update_index_html(tmp_path)[0]
    assert 'href="/courses/"' in (tmp_path / "index.html").read_text()
    config["static"] = []
    assert main.update_index_html(tmp_path)[0]
    assert 'class="static-links"' not in (tmp_path / "index.html").read_text()


@pytest.mark.parametrize("static", [None, {}, ["bad"], [{"name": "x", "path": "/etc"}],
    [{"name": "x", "path": "/srv/files/../etc"}],
    [{"name": "x", "path": "/srv/files/x", "url": "javascript:alert(1)"}],
    [{"name": "x", "path": "/srv/files/x", "url": "//example.com"}]])
def test_invalid_static_config(static):
    assert main.validate_config({"static": static})


def test_valid_static_config():
    assert not main.validate_config({"static": [{"name": "Learning", "path": "/srv/files/Learning"}]})


def test_nested_static_folder_link():
    page = main.generate_index_html({}, 0, 0, "now", "fp", static=[{
        "name": "Lectures", "path": "/srv/files/static/Courses/ML Lectures"}])
    assert 'href="/ytwatcher/static/Courses/ML%20Lectures/"' in page


def test_static_media_scan_and_rebuild(tmp_path, monkeypatch):
    folder = tmp_path / "static" / "Lectures"
    folder.mkdir(parents=True)
    media = folder / "Lesson [abcdefghijk].mp4"
    media.write_bytes(b"media")
    (folder / "Lesson [abcdefghijk].en.vtt").write_text("WEBVTT\n")
    (folder / "Incomplete.mp4.part").touch()
    (folder / "notes.pdf").touch()
    (folder / "loop").symlink_to(folder, target_is_directory=True)
    config = {"static": [{"name": "Lectures", "path": str(folder), "url": "/ytwatcher/static/Lectures/"}]}
    listing = main.scan_static_media(config["static"])
    assert len(listing[0]["media"]) == 1
    entry = listing[0]["media"][0]
    assert entry["href"].endswith("Lesson%20%5Babcdefghijk%5D.mp4")
    assert entry["subs"]["en"].endswith(".en.vtt")
    monkeypatch.setattr(main, "load_config", lambda: config)
    monkeypatch.setattr(main, "scan_downloads", lambda *a, **k: {})
    monkeypatch.setattr(main, "load_watched", lambda: {"abcdefghijk"})
    assert main.update_index_html(tmp_path)[0]
    page = (tmp_path / "index.html").read_text()
    assert 'data-static="true"' in page
    assert 'data-id="abcdefghijk"' not in page
    assert not main.update_index_html(tmp_path)[0]
    (folder / "Second.webm").touch()
    assert main.update_index_html(tmp_path)[0]
    assert media.read_bytes() == b"media"
