#!/usr/bin/env python3
"""Minimal YouTube download page.

Each authenticated account downloads into its own private folder. Files
expire after that user's retention period since their last access. Run
behind Frankfurt Caddy; the app verifies login credentials itself so
both the listing and direct file URLs enforce ownership.
"""
import base64
import binascii
import hashlib
import fcntl
import hmac
import html
import json
import mimetypes
import os
import re
import subprocess
import threading
import time
import urllib.parse
import uuid
from http.cookies import SimpleCookie, CookieError
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import bcrypt

import main  # same project: yt-dlp path + quality presets

TEMP_DIR = Path(os.environ.get("YT_TEMP_DIR", "/srv/files/yt-dl-private"))
AUTH_USERS_FILE = Path(os.environ.get(
    "YT_TEMP_USERS_FILE", str(Path(__file__).with_name(".web-users"))))
ADMIN_USER = "justin"
ACCOUNT_MANAGEMENT_FILE = Path(os.environ.get(
    "YT_TEMP_ACCOUNT_MANAGEMENT_FILE", str(Path(__file__).with_name(".account-management-enabled"))))
TTL_SECONDS = int(os.environ.get("YT_TEMP_TTL", "3600"))
PORT = int(os.environ.get("YT_TEMP_PORT", "8792"))
BIND = os.environ.get("YT_TEMP_BIND", "")
# Last-fetch timestamps survive restarts. The NFS mount is noatime, so
# the access time must be tracked by the app itself.
ACCESS_FILE = Path(os.environ.get(
    "YT_TEMP_ACCESS", str(TEMP_DIR.parent / ".yt_temp_access.json")))
# On-screen settings (e.g. how long files are kept); the env values
# above are only the initial defaults.
SETTINGS_FILE = Path(os.environ.get(
    "YT_TEMP_SETTINGS", str(TEMP_DIR.parent / ".yt_temp_settings.json")))
_settings = {"ttl_minutes": max(1, TTL_SECONDS // 60), "users": {}}
_settings_lock = threading.Lock()
_auth_lock = threading.Lock()
_auth_version = None
_auth_accounts = {}
_auth_cache = {}
_auth_secret = os.urandom(32)


def _read_accounts():
    accounts = {}
    for line in AUTH_USERS_FILE.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        name, hashed = line.split()
        if name in accounts or not hashed.startswith(("$2a$", "$2b$", "$2y$")):
            raise ValueError("Invalid bcrypt account file")
        accounts[name] = hashed.encode("ascii")
    return accounts


def _refresh_accounts():
    """Called with _auth_lock held; fail closed if credentials disappear."""
    global _auth_version, _auth_accounts
    try:
        stat = AUTH_USERS_FILE.stat()
        version = (stat.st_mtime_ns, stat.st_size, stat.st_ino)
        if version != _auth_version:
            _auth_accounts = _read_accounts()
            _auth_version = version
            _auth_cache.clear()
        return True
    except (OSError, ValueError, UnicodeError):
        _auth_cache.clear()
        _auth_accounts = {}
        _auth_version = None
        return False


def authenticated_user(authorization):
    """Verify Basic credentials; file changes invalidate cached passwords."""
    if not authorization or len(authorization) > 4096:
        return None
    scheme, _, encoded = authorization.partition(" ")
    if scheme.lower() != "basic":
        return None
    try:
        decoded = base64.b64decode(encoded, validate=True).decode("utf-8")
    except (binascii.Error, UnicodeError):
        return None
    user, separator, password = decoded.partition(":")
    if not separator or not user or len(user) > 256:
        return None
    password = password.encode("utf-8")
    if len(password) > 72:
        return None
    with _auth_lock:
        if not _refresh_accounts():
            return None
        hashed = _auth_accounts.get(user)
        if hashed is None:
            return None
        key = hmac.digest(_auth_secret, decoded.encode("utf-8"), "sha256")
        if _auth_cache.get(key, 0) > time.monotonic():
            return user
        try:
            valid = bcrypt.checkpw(password, hashed)
        except ValueError:
            valid = False
        if not valid:
            return None
        if len(_auth_cache) >= 256:
            _auth_cache.clear()
        _auth_cache[key] = time.monotonic() + 300
        return user


def account_token(user):
    # Bound to the current password hash, and never accepted as login credentials.
    with _auth_lock:
        if not _refresh_accounts() or user not in _auth_accounts:
            return ""
        return hmac.digest(_auth_secret, b"csrf:" + user.encode() + b":" +
                           _auth_accounts[user], "sha256").hex()


def make_session(user):
    with _auth_lock:
        if not _refresh_accounts() or user not in _auth_accounts:
            raise ValueError("Account unavailable")
        payload = json.dumps([user, int(time.time()) + 43200,
                              hashlib.sha256(_auth_accounts[user]).hexdigest()]).encode()
    encoded = base64.urlsafe_b64encode(payload).decode()
    signature = hmac.digest(_auth_secret, b"session:" + encoded.encode(), "sha256").hex()
    return encoded + "." + signature


def session_user(cookie_header):
    if not cookie_header or len(cookie_header) > 8192:
        return None
    try:
        cookies = SimpleCookie(cookie_header)
        token = cookies["yt_session"].value
        encoded, signature = token.split(".", 1)
        expected = hmac.digest(_auth_secret, b"session:" + encoded.encode(), "sha256").hex()
        if not hmac.compare_digest(signature, expected):
            return None
        user, expires, fingerprint = json.loads(base64.urlsafe_b64decode(encoded))
        if not isinstance(user, str) or not isinstance(expires, int) or expires <= time.time():
            return None
        with _auth_lock:
            if not _refresh_accounts() or user not in _auth_accounts:
                return None
            if not hmac.compare_digest(fingerprint, hashlib.sha256(_auth_accounts[user]).hexdigest()):
                return None
        return user
    except (CookieError, KeyError, ValueError, TypeError, UnicodeError, binascii.Error):
        return None


def update_account(actor, username, password, *, current_password=None, csrf=""):
    """Serialize updates across threads/processes; write only bcrypt hashes."""
    if not ACCOUNT_MANAGEMENT_FILE.is_file():
        raise ValueError("Account management has not been activated yet.")
    if not isinstance(password, str) or (len(password) < 8 or len(password.encode("utf-8")) > 72):
        raise ValueError("Password must contain at least 8 characters and at most 72 UTF-8 bytes.")
    if current_password is None:
        if actor != ADMIN_USER:
            raise PermissionError("Only justin can add users.")
        if not isinstance(username, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", username):
            raise ValueError("Username: 1–64 letters, digits, dots, underscores or hyphens.")
    else:
        username = actor
        if not isinstance(current_password, str) or len(current_password.encode()) > 72:
            raise ValueError("Current password is incorrect.")
    with _auth_lock:
        lock_path = AUTH_USERS_FILE.with_name(AUTH_USERS_FILE.name + ".lock")
        with open(lock_path, "a", encoding="utf-8") as lock:
            os.chmod(lock_path, 0o600)
            fcntl.flock(lock, fcntl.LOCK_EX)
            accounts = _read_accounts()
            if actor not in accounts:
                raise PermissionError("Account unavailable.")
            expected = hmac.digest(_auth_secret, b"csrf:" + actor.encode() + b":" +
                                   accounts[actor], "sha256").hex()
            if not isinstance(csrf, str) or not re.fullmatch(r"[0-9a-f]{64}", csrf) or not hmac.compare_digest(csrf, expected):
                raise PermissionError("Form expired. Reload and try again.")
            if current_password is None:
                if username in accounts:
                    raise ValueError("This username already exists.")
            elif not bcrypt.checkpw(current_password.encode(), accounts[actor]):
                raise ValueError("Current password is incorrect.")
            accounts[username] = bcrypt.hashpw(password.encode(), bcrypt.gensalt())
            tmp = main._tmp_path(AUTH_USERS_FILE)
            try:
                with open(tmp, "x", encoding="utf-8", opener=lambda path, flags: os.open(path, flags, 0o600)) as out:
                    out.write("".join(name + " " + hashed.decode("ascii") + "\n"
                                      for name, hashed in sorted(accounts.items())))
                    out.flush()
                    os.fsync(out.fileno())
                tmp.replace(AUTH_USERS_FILE)
            finally:
                tmp.unlink(missing_ok=True)
            _refresh_accounts()


def render_account_page(user, message="", error=False):
    token = html.escape(account_token(user), quote=True)
    notice = ('<p role="status" class="' + ("err" if error else "meta") + '">' +
              html.escape(message) + '</p>') if message else ""
    forms = f'''<h2>Passwort ändern</h2>
<form method="post" action="/account/password">
<input type="hidden" name="csrf" value="{token}">
<label>Aktuelles Passwort <input type="password" name="current_password" autocomplete="current-password" required></label>
<label>Neues Passwort <input type="password" name="password" autocomplete="new-password" minlength="8" required></label>
<label>Passwort bestätigen <input type="password" name="confirm_password" autocomplete="new-password" minlength="8" required></label>
<button type="submit">Passwort ändern</button></form>'''
    if user == ADMIN_USER:
        with _auth_lock:
            _refresh_accounts()
            names = ", ".join(html.escape(name) for name in sorted(_auth_accounts))
        forms += f'''<h2>Benutzer hinzufügen</h2><p class="meta">Benutzer: {names}</p>
<form method="post" action="/account/users">
<input type="hidden" name="csrf" value="{token}">
<label>Benutzername <input name="username" autocomplete="off" maxlength="64" pattern="[A-Za-z0-9][A-Za-z0-9_.-]*" required></label>
<label>Passwort <input type="password" name="password" autocomplete="new-password" minlength="8" required></label>
<label>Passwort bestätigen <input type="password" name="confirm_password" autocomplete="new-password" minlength="8" required></label>
<button type="submit">Benutzer hinzufügen</button></form>'''
    return ('''<!doctype html><html lang="de"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Konto</title>
<style>body{background:#141414;color:#eee;font-family:sans-serif;max-width:44rem;margin:2rem auto;padding:0 1rem}
form,label{display:flex;flex-direction:column;gap:.5rem}form{margin-bottom:2rem}
input,button{padding:.6rem;background:#222;color:#fff;border:1px solid #555;border-radius:4px}
a{color:#8ab4f8}.err{color:#ff7b72}.meta{color:#bbb}</style></head><body>
<a href="/">← Downloads</a><h1>Konto: ''' + html.escape(user) + '</h1>' + notice + forms +
            '<p class="meta">Mindestens 8 Zeichen, maximal 72 UTF-8 Bytes. Änderungen gelten sofort.</p></body></html>')


def user_key(user):
    return "u_" + hashlib.sha256(user.encode("utf-8")).hexdigest()


def user_directory(user, create=False):
    folder = TEMP_DIR / user_key(user)
    if folder.is_symlink():
        raise ValueError("User folder must not be a symlink")
    if create:
        folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    return folder


def user_file(user, name):
    """Only a regular, completed file directly inside this user's folder."""
    if not name or name in (".", "..") or Path(name).name != name:
        return None
    try:
        path = user_directory(user) / name
        if path.is_symlink() or not path.is_file() or path.suffix in (".part", ".ytdl"):
            return None
        return path
    except (OSError, ValueError):
        return None


def load_settings():
    global _settings
    try:
        data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            minutes = int(data.get("ttl_minutes", _settings["ttl_minutes"]))
            users = data.get("users", {})
            if not isinstance(users, dict):
                users = {}
            _settings = {"ttl_minutes": max(1, min(minutes, 7 * 24 * 60)),
                         "users": {str(user): max(1, min(int(value), 7 * 24 * 60))
                                   for user, value in users.items()}}
    except (OSError, ValueError, TypeError):
        pass


def save_settings():
    try:
        tmp = main._tmp_path(SETTINGS_FILE)
        tmp.write_text(json.dumps(_settings), encoding="utf-8")
        tmp.replace(SETTINGS_FILE)
    except OSError:
        pass


def current_ttl(user=None):
    with _settings_lock:
        return _settings["users"].get(user, _settings["ttl_minutes"]) * 60

PRESETS = {
    "video": main.MANUAL_QUALITY_PRESETS["720"],
    # m4a first: plays natively on iPhones, unlike opus/webm audio.
    "audio": "bestaudio[ext=m4a]/bestaudio",
}
URL_RE = re.compile(r"^https?://\S+$")

_jobs = {}
_jobs_lock = threading.Lock()
# Private relative path -> last fetch timestamp; kept in ACCESS_FILE.
_access = {}
_access_lock = threading.Lock()


def load_access():
    global _access
    try:
        data = json.loads(ACCESS_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            _access = {str(k): float(v) for k, v in data.items()}
    except (OSError, ValueError):
        _access = {}


def save_access():
    try:
        tmp = main._tmp_path(ACCESS_FILE)
        tmp.write_text(json.dumps(_access), encoding="utf-8")
        tmp.replace(ACCESS_FILE)
    except OSError:
        pass


def note_access(path):
    with _access_lock:
        _access[path.relative_to(TEMP_DIR).as_posix()] = time.time()
        save_access()


def last_activity(path):
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return 0
    with _access_lock:
        return max(mtime, _access.get(path.relative_to(TEMP_DIR).as_posix(), 0))


def default_bind():
    if BIND:
        return BIND
    try:
        out = subprocess.run(["tailscale", "ip", "-4"], capture_output=True,
                             text=True, timeout=5)
        ip = out.stdout.strip().splitlines()
        if ip:
            return ip[0]
    except Exception:
        pass
    return "127.0.0.1"


def cleanup_once(now=None):
    now = time.time() if now is None else now
    with _settings_lock:
        default_ttl = _settings["ttl_minutes"] * 60
        user_ttls = {user_key(u): minutes * 60 for u, minutes in _settings["users"].items()}
    with _jobs_lock:
        active = {user_key(j["user"]) for j in _jobs.values()
                  if j["status"] in ("starting", "downloading")}
    names = set()
    try:
        for folder in TEMP_DIR.iterdir():
            if folder.is_symlink():
                continue
            # Old shared files have no known owner: never list them for any
            # account, but let the normal retention cleanup expire them.
            if folder.is_file():
                files, ttl, busy = [folder], default_ttl, False
            elif folder.is_dir() and re.fullmatch(r"u_[0-9a-f]{64}", folder.name):
                files, ttl, busy = list(folder.iterdir()), user_ttls.get(folder.name, default_ttl), folder.name in active
            else:
                continue
            for path in files:
                if path in (ACCESS_FILE, SETTINGS_FILE) or path.is_symlink() or not path.is_file():
                    continue
                try:
                    if not busy and now - last_activity(path) > ttl:
                        path.unlink()
                    else:
                        names.add(path.relative_to(TEMP_DIR).as_posix())
                except OSError:
                    pass
        with _access_lock:
            gone = [n for n in _access if n not in names]
            if gone:
                for name in gone:
                    del _access[name]
                save_access()
    except OSError:
        pass
    with _jobs_lock:
        stale = [key for key, job in _jobs.items()
                 if job["status"] not in ("starting", "downloading")
                 and now - job["ts"] > current_ttl(job["user"])]
        for key in stale:
            del _jobs[key]


def cleanup_loop():
    while True:
        cleanup_once()
        time.sleep(30)


def run_download(job_id, url, preset, user):
    folder = TEMP_DIR / user_key(user)
    out = folder / "%(title).200B [%(id)s].%(ext)s"
    cmd = [main.YT_DLP, "--no-playlist", "--no-mtime",
           "--print", "after_move:%(filepath)s", "-f", PRESETS[preset],
           "-o", str(out), url]
    # Datacenter IPs need the logged-in session to pass YouTube's bot
    # wall; residential connections usually don't.
    try:
        if main.COOKIES_FILE.exists() and main.COOKIES_FILE.stat().st_size:
            cmd += ["--cookies", str(main.COOKIES_FILE)]
    except OSError:
        pass
    try:
        user_directory(user, create=True)
        result = subprocess.run(cmd, capture_output=True, text=True,
                                timeout=1800)
        ok = result.returncode == 0
        err = "" if ok else result.stderr.strip()[-1500:]
        if ok:
            for line in result.stdout.splitlines():
                path = Path(line.strip())
                if path.parent == folder and user_file(user, path.name) is not None:
                    note_access(path)
    except subprocess.TimeoutExpired:
        ok, err = False, "download timed out"
    except (OSError, ValueError) as exc:
        ok, err = False, str(exc)
    if not ok:
        # Full stderr to the journal; the page only shows a tail.
        print(f"download failed for {url}:\n{err}", flush=True)
    with _jobs_lock:
        job = _jobs.get(job_id)
        if job is not None:
            job["status"] = "done" if ok else "failed"
            job["error"] = err
            job["ts"] = time.time()


def fmt_size(n):
    for unit in ("B", "KiB", "MiB", "GiB"):
        if n < 1024 or unit == "GiB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


PAGE = """<!doctype html>
<html><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="10">
<title>YouTube Download</title>
<style>
 body {{ background:#141414; color:#e0e0e0; font-family:sans-serif;
        max-width:44rem; margin:2rem auto; padding:0 .8rem; }}
 h1 {{ font-size:1.3rem; }}
 form {{ display:flex; gap:.5rem; flex-wrap:wrap; margin:1rem 0; }}
 input[type=url], input[type=password], input[name=username] {{ flex:1; min-width:14rem; padding:.5rem;
        background:#1e1e1e; border:1px solid #444; border-radius:4px;
        color:#e0e0e0; }}
 select, button {{ padding:.5rem .8rem; background:#2a6f2a;
        border:1px solid #444; border-radius:4px; color:#fff;
        cursor:pointer; }}
 .file, .job {{ background:#1e1e1e; border:1px solid #333; border-radius:4px;
        padding:.5rem .7rem; margin:.4rem 0; }}
 .meta {{ color:#999; font-size:.85rem; }}
 .err {{ color:#ff7b72; }}
 a {{ color:#8ab4f8; text-decoration:none; }}
 a:hover {{ text-decoration:underline; }}
</style></head><body>
<h1>YouTube Download</h1>
{account_link}
<form method="post" action="/download">
 <input type="url" name="url" placeholder="https://www.youtube.com/watch?v=..."
        required autofocus>
 <select name="preset">
  <option value="video">Video (≤720p, iPhone-kompatibel)</option>
  <option value="audio">nur Audio</option>
 </select>
 <button type="submit">Download</button>
</form>
<form method="post" action="/settings" class="settings">
 <label>Dateien behalten für
  <input type="number" name="ttl_minutes" min="1" max="10080"
         value="{ttl_minutes}" style="width:5.5em"> Minuten</label>
 <button type="submit">Speichern</button>
</form>
{jobs}
{files}
<p class="meta">Dateien und Verlauf werden {ttl} Minuten nach dem letzten
Abruf automatisch gelöscht (abrufen = Download auf dein Gerät). Seite
aktualisiert sich alle 10 s.</p>
</body></html>
"""


PLAY_PAGE = """<!doctype html>
<html><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
 html, body {{ margin:0; height:100%; background:#000; }}
 video {{ width:100vw; height:100vh; object-fit:contain; background:#000; }}
 #bar {{ position:fixed; top:.4rem; right:.4rem; display:flex; gap:.4rem; }}
 #bar button {{ padding:.45rem .9rem; background:rgba(42,111,42,.9);
        border:1px solid #444; border-radius:4px; color:#fff;
        cursor:pointer; font-size:1rem; }}
 #title {{ position:fixed; left:.6rem; top:.4rem; color:#bbb;
        font:.85rem sans-serif; text-shadow:0 0 4px #000;
        max-width:70vw; overflow:hidden; text-overflow:ellipsis;
        white-space:nowrap; }}
</style></head><body>
<video id="v" src="__SRC__" controls autoplay playsinline></video>
<div id="bar">
 <button type="button" onclick="full()">&#x26F6; Fullscreen</button>
 <button type="button" onclick="history.back()">&#x2715; Zurück</button>
</div>
<div id="title">__TITLE__</div>
<script>
function full() {{
  var v = document.getElementById("v");
  if (v.requestFullscreen) v.requestFullscreen();
  else if (v.webkitEnterFullscreen) v.webkitEnterFullscreen(); // iOS
}}
document.getElementById("v").addEventListener("dblclick", full);
</script>
</body></html>
"""


def render_page(user):
    now = time.time()
    job_rows = []
    with _jobs_lock:
        jobs = [dict(job) for job in _jobs.values() if job["user"] == user]
    for j in sorted(jobs, key=lambda v: v["ts"], reverse=True)[:5]:
        cls = "err" if j["status"] == "failed" else "meta"
        note = {"starting": "lädt…", "downloading": "lädt…", "done": "fertig",
                "failed": html.escape(j["error"] or "fehlgeschlagen")}
        job_rows.append(
            f'<div class="job"><span class="meta">{html.escape(j["url"])}'
            f'</span> — <span class="{cls}">{note.get(j["status"], j["status"])}'
            f"</span></div>")
    file_rows = []
    try:
        entries = sorted(user_directory(user).iterdir(), key=lambda p: p.stat().st_mtime,
                         reverse=True)
    except (OSError, ValueError):
        entries = []
    ttl = current_ttl(user)
    for p in entries:
        if p.name in (ACCESS_FILE.name, SETTINGS_FILE.name) \
                or user_file(user, p.name) is None:
            continue
        left = max(0, ttl - (now - last_activity(p)))
        ctype = mimetypes.guess_type(p.name)[0] or ""
        quoted = urllib.parse.quote(p.name)
        play = (f' · <a href="/play/{quoted}" target="_blank">▶ Play</a>'
                if ctype.startswith(("video/", "audio/")) else "")
        file_rows.append(
            f'<div class="file"><a href="/files/{quoted}"'
            f' download>{html.escape(p.name)}</a>{play}'
            f'<div class="meta">{fmt_size(p.stat().st_size)} · '
            f'wird in {int(left // 60)}:{int(left % 60):02d} min gelöscht'
            f"</div></div>")
    jobs_html = ("<h2>Jobs</h2>" + "".join(job_rows)) if job_rows else ""
    files_html = ("<h2>Dateien</h2>" + "".join(file_rows)) if file_rows else ""
    minutes = ttl // 60
    return PAGE.format(jobs=jobs_html, files=files_html, ttl=minutes,
                       ttl_minutes=minutes, account_link=(
                           '<p><a href="/account">Konto / Passwort ändern</a></p>'
                           if ACCOUNT_MANAGEMENT_FILE.is_file() else ""))


class Handler(BaseHTTPRequestHandler):
    server_version = "yt-dl-temp/2.0"

    def _private_headers(self):
        self.send_header("Cache-Control", "private, no-store")
        self.send_header("Vary", "Authorization")

    def _require_user(self):
        credentials = self.headers.get_all("Authorization") or []
        self.user = session_user(self.headers.get("Cookie"))
        if self.user is None:
            self.user = authenticated_user(credentials[0]) if len(credentials) == 1 else None
        if self.user is not None:
            return True
        body = b"Authentication required"
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="YouTube Download", charset="UTF-8"')
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._private_headers()
        self.end_headers()
        self.wfile.write(body)
        return False

    def _send(self, code, body, ctype="text/html; charset=utf-8"):
        data = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self._private_headers()
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if not self._require_user():
            return
        path = urllib.parse.urlsplit(self.path).path
        if path in ("/", "/index.html"):
            self._send(200, render_page(self.user))
        elif path == "/account" and ACCOUNT_MANAGEMENT_FILE.is_file():
            self._send(200, render_account_page(self.user,
                "Password changed. Use the new password for your next login."
                if urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query).get("changed") == ["1"] else ""))
        elif path.startswith("/files/"):
            name = urllib.parse.unquote(path[len("/files/"):])
            self._serve_file(name)
        elif path.startswith("/raw/"):
            name = urllib.parse.unquote(path[len("/raw/"):])
            self._serve_raw(name)
        elif path.startswith("/play/"):
            name = urllib.parse.unquote(path[len("/play/"):])
            self._play(name)
        else:
            self._send(404, "not found", "text/plain")

    def _play(self, name):
        p = user_file(self.user, name)
        if p is None:
            self._send(404, "not found", "text/plain")
            return
        ctype = mimetypes.guess_type(p.name)[0] or ""
        if not ctype.startswith(("video/", "audio/")):
            self._send(404, "not a media file", "text/plain")
            return
        note_access(p)  # watching counts as access too
        quoted = urllib.parse.quote(p.name)
        body = PLAY_PAGE.replace("__SRC__", f"/raw/{quoted}") \
                        .replace("__TITLE__", html.escape(p.name))
        self._send(200, body)

    def _serve_raw(self, name):
        """Inline file streaming (no attachment) with HTTP Range support —
        browsers need ranges to seek, and iPhone Safari refuses to play
        without them."""
        p = user_file(self.user, name)
        if p is None:
            self._send(404, "not found", "text/plain")
            return
        try:
            size = p.stat().st_size
            f = open(p, "rb")
        except OSError:
            self._send(404, "not found", "text/plain")
            return
        note_access(p)
        ctype = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
        rng = self.headers.get("Range", "")
        if rng.startswith("bytes="):
            try:
                start_s, _, end_s = rng[6:].partition("-")
                start = int(start_s) if start_s else 0
                end = int(end_s) if end_s else size - 1
                start, end = max(0, start), min(end, size - 1)
                if start > end:
                    raise ValueError
                self.send_response(206)
                self.send_header("Content-Type", ctype)
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Content-Range",
                                 f"bytes {start}-{end}/{size}")
                self.send_header("Content-Length", str(end - start + 1))
                self._private_headers()
                self.end_headers()
                f.seek(start)
                remaining = end - start + 1
                with f:
                    while remaining > 0:
                        chunk = f.read(min(256 * 1024, remaining))
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        remaining -= len(chunk)
                return
            except (ValueError, OSError):
                try:
                    f.close()
                except OSError:
                    pass
        try:
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(size))
            self._private_headers()
            self.end_headers()
            with f:
                while True:
                    chunk = f.read(256 * 1024)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
        except (OSError, BrokenPipeError):
            pass  # client went away or cleanup removed the file mid-stream

    def _serve_file(self, name):
        p = user_file(self.user, name)
        if p is None:
            self._send(404, "not found", "text/plain")
            return
        try:
            size = p.stat().st_size
            f = open(p, "rb")
        except OSError:
            self._send(404, "not found", "text/plain")
            return
        ctype = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
        note_access(p)  # the user's retention clock restarts on every fetch
        # Header values are latin-1; non-ASCII titles (CJK, fullwidth
        # punctuation) must ride in the RFC 5987 filename* parameter.
        fallback = p.name.encode("ascii", "replace").decode().replace(
            "\\", "").replace('"', "")
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(size))
        # attachment: browsers save instead of playing inline.
        self.send_header(
            "Content-Disposition",
            f"attachment; filename=\"{fallback}\"; "
            f"filename*=UTF-8''{urllib.parse.quote(p.name)}")
        self._private_headers()
        self.end_headers()
        try:
            with f:
                while True:
                    chunk = f.read(256 * 1024)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
        except (OSError, BrokenPipeError):
            # Client went away, or cleanup deleted the file mid-stream.
            pass

    def do_POST(self):
        if not self._require_user():
            return
        path = urllib.parse.urlsplit(self.path).path
        if path not in ("/download", "/settings", "/account/password", "/account/users"):
            self._send(404, "not found", "text/plain")
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            self._send(400, "Invalid Content-Length", "text/plain")
            return
        if not 0 <= length <= main.MAX_REQUEST_BODY:
            self._send(413, "Request body too large", "text/plain")
            return
        self.connection.settimeout(main.REQUEST_BODY_TIMEOUT)
        raw = self.rfile.read(length).decode("utf-8", "replace")
        ctype = self.headers.get("Content-Type", "")
        if "application/json" in ctype:
            try:
                data = json.loads(raw or "{}")
                if not isinstance(data, dict):
                    raise ValueError("Expected a JSON object")
            except ValueError:
                data = {}
        else:
            data = dict(urllib.parse.parse_qsl(raw))
        if path in ("/account/password", "/account/users"):
            if not ACCOUNT_MANAGEMENT_FILE.is_file():
                self._send(503, "Account management has not been activated yet.", "text/plain")
                return
            if path == "/account/users" and self.user != ADMIN_USER:
                self._send(403, "Only justin can add users.", "text/plain")
                return
            origin = self.headers.get("Origin")
            if self.headers.get("Sec-Fetch-Site") == "cross-site" or (origin and
                    urllib.parse.urlsplit(origin).netloc != self.headers.get("Host")):
                self._send(403, "Cross-site account update denied.", "text/plain")
                return
            try:
                password = data.get("password", "")
                if password != data.get("confirm_password"):
                    raise ValueError("Passwords do not match.")
                update_account(self.user, data.get("username", ""), password,
                               current_password=(data.get("current_password", "")
                                                 if path == "/account/password" else None),
                               csrf=data.get("csrf", ""))
            except (ValueError, PermissionError) as exc:
                self._send(403 if isinstance(exc, PermissionError) else 400,
                           render_account_page(self.user, str(exc), error=True))
                return
            except OSError:
                self._send(500, render_account_page(self.user, "Could not save account. Try again.", error=True))
                return
            if path == "/account/password":
                self.send_response(303)
                self.send_header("Set-Cookie", "yt_session=" + make_session(self.user) +
                                 "; Path=/; Secure; HttpOnly; SameSite=Strict; Max-Age=43200")
                self.send_header("Location", "/account?changed=1")
                self._private_headers()
                self.end_headers()
            else:
                self._send(200, render_account_page(self.user, "User added. They can log in immediately."))
            return
        if path == "/settings":
            try:
                minutes = int(data.get("ttl_minutes", ""))
            except (TypeError, ValueError):
                minutes = 0
            if not 1 <= minutes <= 7 * 24 * 60:
                self._send(400, render_page(self.user).replace(
                    "<h1>YouTube Download</h1>",
                    '<h1>YouTube Download</h1><div class="job err">'
                    "Aufbewahrungsfrist zwischen 1 und 10080 Minuten"
                    "</div>"))
                return
            with _settings_lock:
                _settings["users"][self.user] = minutes
                save_settings()
            self.send_response(303)
            self.send_header("Location", "/")
            self._private_headers()
            self.end_headers()
            return
        url = str(data.get("url", "")).strip()
        preset = data.get("preset", "video")
        if not URL_RE.match(url) or preset not in PRESETS:
            self._send(400, render_page(self.user).replace(
                "<h1>YouTube Download</h1>",
                '<h1>YouTube Download</h1><div class="job err">ungültige '
                "URL oder Format</div>"))
            return
        try:
            user_directory(self.user, create=True)
        except (OSError, ValueError):
            self._send(500, "Private download folder unavailable", "text/plain")
            return
        job_id = uuid.uuid4().hex
        with _jobs_lock:
            _jobs[job_id] = {"user": self.user, "url": url, "preset": preset, "ts": time.time(),
                             "status": "starting", "error": ""}
        threading.Thread(target=run_download,
                         args=(job_id, url, preset, self.user), daemon=True).start()
        self.send_response(303)
        self.send_header("Location", "/")
        self._private_headers()
        self.end_headers()

    def log_message(self, fmt, *args):  # quieter journal
        if args and isinstance(args[1], str) and args[1].startswith("POST"):
            super().log_message(fmt, *args)


def main_():
    if TEMP_DIR.resolve().is_relative_to(Path("/srv/files/static").resolve()):
        raise RuntimeError("Private downloads must be stored outside /srv/files/static")
    if not AUTH_USERS_FILE.is_file():
        raise RuntimeError(f"Missing bcrypt login accounts: {AUTH_USERS_FILE}")
    TEMP_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    load_access()
    load_settings()
    threading.Thread(target=cleanup_loop, daemon=True).start()
    host = default_bind()
    server = ThreadingHTTPServer((host, PORT), Handler)
    print(f"serving on http://{host}:{PORT}, temp dir {TEMP_DIR}, "
          f"ttl {current_ttl()}s", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main_()
