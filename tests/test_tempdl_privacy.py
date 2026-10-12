"""Exercise account boundaries through the downloader's actual HTTP handler."""
import base64
import http.client
import json
import os
import threading
import time
from types import SimpleNamespace
from urllib.parse import quote, urlencode

import pytest

bcrypt = pytest.importorskip("bcrypt")
import yt_dl_temp as tempdl


def credentials(user, password="secret"):
    return "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    root = tmp_path / "private"
    root.mkdir()
    accounts = tmp_path / "users"
    hashed = bcrypt.hashpw(b"secret", bcrypt.gensalt(rounds=4)).decode()
    accounts.write_text(f"alice {hashed}\nbob {hashed}\n")
    monkeypatch.setattr(tempdl, "TEMP_DIR", root)
    monkeypatch.setattr(tempdl, "AUTH_USERS_FILE", accounts)
    monkeypatch.setattr(tempdl, "ACCESS_FILE", tmp_path / "access.json")
    monkeypatch.setattr(tempdl, "SETTINGS_FILE", tmp_path / "settings.json")
    monkeypatch.setattr(tempdl, "_settings", {"ttl_minutes": 60, "users": {}})
    monkeypatch.setattr(tempdl, "_jobs", {})
    monkeypatch.setattr(tempdl, "_access", {})
    monkeypatch.setattr(tempdl, "_auth_version", None)
    monkeypatch.setattr(tempdl, "_auth_accounts", {})
    monkeypatch.setattr(tempdl, "_auth_cache", {})
    for user in ("alice", "bob"):
        tempdl.user_directory(user, create=True)
    return root


@pytest.fixture
def http_request(isolated):
    server = tempdl.ThreadingHTTPServer(("127.0.0.1", 0), tempdl.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def send(path="/", user="alice", method="GET", data=None, headers=None):
        fields = dict(headers or {})
        if user is not None:
            fields["Authorization"] = credentials(user)
        body = urlencode(data) if data is not None else None
        if body is not None:
            fields["Content-Type"] = "application/x-www-form-urlencoded"
        connection = http.client.HTTPConnection(*server.server_address, timeout=5)
        try:
            connection.request(method, path, body=body, headers=fields)
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    yield send
    server.shutdown()
    server.server_close()
    thread.join()


def test_login_validation_and_revocation(isolated):
    assert tempdl.authenticated_user(credentials("alice")) == "alice"
    assert tempdl.authenticated_user(credentials("bob")) == "bob"
    assert tempdl.authenticated_user(credentials("alice", "wrong")) is None
    assert tempdl.authenticated_user(credentials("unknown")) is None
    assert tempdl.authenticated_user("Basic invalid!") is None
    assert tempdl.authenticated_user("Bearer alice") is None
    tempdl.AUTH_USERS_FILE.write_text("")
    assert tempdl.authenticated_user(credentials("alice")) is None
    tempdl.AUTH_USERS_FILE.unlink()
    assert tempdl.authenticated_user(credentials("bob")) is None


@pytest.mark.parametrize("path", ["/", "/files/secret.mp4", "/raw/secret.mp4", "/play/secret.mp4", "/settings", "/download"])
def test_every_route_requires_verified_login(http_request, path):
    method = "POST" if path in ("/settings", "/download") else "GET"
    status, headers, _ = http_request(path, user=None, method=method,
                                 headers={"X-Remote-User": "alice"})
    assert status == 401
    assert "WWW-Authenticate" in headers
    assert headers["Cache-Control"] == "private, no-store"


def test_listing_and_job_history_are_private(http_request, isolated):
    (tempdl.user_directory("alice") / "alice-only.mp4").write_bytes(b"alice")
    (tempdl.user_directory("bob") / "bob-only.mp4").write_bytes(b"bob")
    (isolated / "legacy-shared.mp4").write_bytes(b"legacy")
    for user in ("alice", "bob"):
        tempdl._jobs[user] = {"user": user, "url": f"https://example.com/{user}-job",
                             "status": "failed", "error": f"{user}-error", "ts": time.time()}
    status, headers, page = http_request()
    assert status == 200
    assert b"alice-only.mp4" in page and b"alice-job" in page and b"alice-error" in page
    assert b"bob-only.mp4" not in page and b"bob-job" not in page and b"bob-error" not in page
    assert b"legacy-shared.mp4" not in page
    assert headers["Vary"] == "Authorization"
    assert b"alice-only.mp4" not in http_request(user="bob")[2]


@pytest.mark.parametrize("prefix", ["files", "raw", "play"])
def test_direct_links_cannot_read_another_users_files(http_request, isolated, prefix):
    filename = "private video.mp4"
    (tempdl.user_directory("bob") / filename).write_bytes(b"bob-private-content")
    path = f"/{prefix}/{quote(filename)}"
    assert http_request(path, user="alice")[0] == 404
    assert http_request(path, user="bob")[0] == 200
    for escaped in [f"../{tempdl.user_key('bob')}/{filename}", f"/{tempdl.user_directory('bob')}/{filename}"]:
        assert http_request(f"/{prefix}/{quote(escaped, safe='')}", user="alice")[0] == 404
    (tempdl.user_directory("alice") / "linked.mp4").symlink_to(tempdl.user_directory("bob") / filename)
    assert http_request(f"/{prefix}/linked.mp4", user="alice")[0] == 404
    (isolated / "legacy.mp4").write_bytes(b"legacy")
    assert http_request(f"/{prefix}/legacy.mp4", user="alice")[0] == 404


def test_identical_names_and_range_playback_stay_private(http_request, isolated):
    for user, contents in [("alice", b"012345"), ("bob", b"abcdef")]:
        (tempdl.user_directory(user) / "same.mp4").write_bytes(contents)
    assert http_request("/files/same.mp4", user="alice")[2] == b"012345"
    assert http_request("/files/same.mp4", user="bob")[2] == b"abcdef"
    status, headers, data = http_request("/raw/same.mp4", user="bob", headers={"Range": "bytes=1-3"})
    assert status == 206 and data == b"bcd"
    assert headers["Content-Range"] == "bytes 1-3/6"
    assert headers["Cache-Control"] == "private, no-store"
    assert len(tempdl._access) == 2


def test_retention_settings_do_not_change_other_accounts(http_request, isolated):
    assert http_request("/settings", method="POST", data={"ttl_minutes": 5})[0] == 303
    assert tempdl.current_ttl("alice") == 300
    assert tempdl.current_ttl("bob") == 3600
    assert json.loads(tempdl.SETTINGS_FILE.read_text())["users"] == {"alice": 5}
    tempdl.load_settings()
    assert tempdl.current_ttl("alice") == 300
    assert tempdl.current_ttl("bob") == 3600


def test_download_endpoint_assigns_authenticated_owner(http_request, isolated, monkeypatch):
    invoked = threading.Event()
    calls = []

    def worker(*args):
        calls.append(args)
        invoked.set()

    monkeypatch.setattr(tempdl, "run_download", worker)
    status, _, _ = http_request("/download", user="bob", method="POST",
                           data={"url": "https://example.com/video", "preset": "audio", "user": "alice"})
    assert status == 303
    assert invoked.wait(2)
    job_id, url, preset, user = calls[0]
    assert user == "bob" and preset == "audio"
    assert tempdl._jobs[job_id]["user"] == "bob"
    assert b"https://example.com/video" not in http_request(user="alice")[2]


def test_worker_downloads_into_owner_folder_and_starts_retention_on_completion(isolated, monkeypatch):
    tempdl._jobs["job"] = {"user": "bob", "status": "starting", "ts": 0}
    output = tempdl.user_directory("bob") / "result.mp4"

    def download(cmd, **kwargs):
        assert str(tempdl.user_directory("bob")) in cmd[cmd.index("-o") + 1]
        assert "--no-mtime" in cmd
        output.write_bytes(b"video")
        os.utime(output, (1, 1))
        return SimpleNamespace(returncode=0, stdout=str(output) + "\n", stderr="")

    monkeypatch.setattr(tempdl.subprocess, "run", download)
    tempdl.run_download("job", "https://example.com/video", "video", "bob")
    assert tempdl._jobs["job"]["status"] == "done"
    assert tempdl.last_activity(output) > time.time() - 10
    assert tempdl.user_file("alice", "result.mp4") is None


def test_cleanup_applies_owner_retention_and_preserves_running_downloads(isolated):
    now = time.time()
    tempdl._settings["users"] = {"alice": 5, "bob": 60}
    a = tempdl.user_directory("alice") / "same.mp4"
    b = tempdl.user_directory("bob") / "same.mp4"
    for path in (a, b):
        path.write_bytes(b"media")
        os.utime(path, (now - 600, now - 600))
    tempdl.cleanup_once(now)
    assert not a.exists() and b.exists()
    partial = tempdl.user_directory("alice") / "pending.mp4.part"
    partial.touch()
    os.utime(partial, (1, 1))
    tempdl._jobs["busy"] = {"user": "alice", "status": "starting", "ts": 1}
    tempdl.cleanup_once(now)
    assert partial.exists() and "busy" in tempdl._jobs
