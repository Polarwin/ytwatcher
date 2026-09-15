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
