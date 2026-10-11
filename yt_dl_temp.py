#!/usr/bin/env python3
"""Minimal YouTube download page.

Paste a link, the server downloads it into static/temp, and the file can
be fetched from the list. Files (and partials) vanish TTL_SECONDS after
the download finished. Run behind the frankfurt Caddy (basic auth);
binds the tailscale IP so the proxy can reach it.
"""
import html
import json
import mimetypes
import os
import re
import subprocess
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import main  # same project: yt-dlp path + quality presets

TEMP_DIR = Path(os.environ.get("YT_TEMP_DIR", "/srv/files/static/temp"))
TTL_SECONDS = int(os.environ.get("YT_TEMP_TTL", "600"))
PORT = int(os.environ.get("YT_TEMP_PORT", "8792"))
BIND = os.environ.get("YT_TEMP_BIND", "")
# Last-fetch timestamps survive restarts. The NFS mount is noatime, so
# the access time must be tracked by the app itself.
ACCESS_FILE = Path(os.environ.get(
    "YT_TEMP_ACCESS", str(TEMP_DIR.parent / ".yt_temp_access.json")))

PRESETS = {
    "video": main.MANUAL_QUALITY_PRESETS["720"],
    # m4a first: plays natively on iPhones, unlike opus/webm audio.
    "audio": "bestaudio[ext=m4a]/bestaudio",
}
URL_RE = re.compile(r"^https?://\S+$")

_jobs = {}
_jobs_lock = threading.Lock()
# filename -> last fetch timestamp (from their device); kept in ACCESS_FILE.
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
        tmp = ACCESS_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(_access), encoding="utf-8")
        tmp.replace(ACCESS_FILE)
    except OSError:
        pass


def note_access(name):
    with _access_lock:
        _access[name] = time.time()
        save_access()


def last_activity(path):
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return 0
    with _access_lock:
        return max(mtime, _access.get(path.name, 0))


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


def cleanup_loop():
    while True:
        now = time.time()
        try:
            names = set()
            for p in TEMP_DIR.iterdir():
                if p.name == ACCESS_FILE.name:
                    continue
                names.add(p.name)
                try:
                    if now - last_activity(p) > TTL_SECONDS:
                        p.unlink()
                except OSError:
                    pass
            # Drop access entries whose files are gone.
            with _access_lock:
                gone = [n for n in _access if n not in names]
                if gone:
                    for n in gone:
                        del _access[n]
                    save_access()
        except OSError:
            pass
        with _jobs_lock:
            stale = [j for j, v in _jobs.items() if now - v["ts"] > 3600]
            for j in stale:
                del _jobs[j]
        time.sleep(30)


def run_download(job_id, url, preset):
    out = TEMP_DIR / "%(title).200B [%(id)s].%(ext)s"
    cmd = [main.YT_DLP, "--no-playlist", "-f", PRESETS[preset],
           "-o", str(out), url]
    # Datacenter IPs need the logged-in session to pass YouTube's bot
    # wall; residential connections usually don't.
    try:
        if main.COOKIES_FILE.exists() and main.COOKIES_FILE.stat().st_size:
            cmd += ["--cookies", str(main.COOKIES_FILE)]
    except OSError:
        pass
    try:
        result = subprocess.run(cmd, capture_output=True, text=True,
                                timeout=1800)
        ok = result.returncode == 0
        err = "" if ok else result.stderr.strip()[-1500:]
    except subprocess.TimeoutExpired:
        ok, err = False, "download timed out"
    if not ok:
        # Full stderr to the journal; the page only shows a tail.
        print(f"download failed for {url}:\n{err}", flush=True)
    with _jobs_lock:
        _jobs[job_id]["status"] = "done" if ok else "failed"
        _jobs[job_id]["error"] = err


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
 input[type=url] {{ flex:1; min-width:14rem; padding:.5rem;
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
<form method="post" action="/download">
 <input type="url" name="url" placeholder="https://www.youtube.com/watch?v=..."
        required autofocus>
 <select name="preset">
  <option value="video">Video (≤720p, iPhone-kompatibel)</option>
  <option value="audio">nur Audio</option>
 </select>
 <button type="submit">Download</button>
</form>
{jobs}
{files}
<p class="meta">Dateien werden {ttl} Minuten nach dem letzten Abruf
automatisch gelöscht (abrufen = Download auf dein Gerät). Seite
aktualisiert sich alle 10 s.</p>
</body></html>
"""


def render_page():
    now = time.time()
    job_rows = []
    with _jobs_lock:
        jobs = list(_jobs.values())
    for j in sorted(jobs, key=lambda v: v["ts"], reverse=True)[:5]:
        cls = "err" if j["status"] == "failed" else "meta"
        note = {"downloading": "lädt…", "done": "fertig",
                "failed": html.escape(j["error"] or "fehlgeschlagen")}
        job_rows.append(
            f'<div class="job"><span class="meta">{html.escape(j["url"])}'
            f'</span> — <span class="{cls}">{note.get(j["status"], j["status"])}'
            f"</span></div>")
    file_rows = []
    try:
        entries = sorted(TEMP_DIR.iterdir(), key=lambda p: p.stat().st_mtime,
                         reverse=True)
    except OSError:
        entries = []
    for p in entries:
        if p.name == ACCESS_FILE.name or p.suffix in (".part", ".ytdl") \
                or not p.is_file():
            continue
        left = max(0, TTL_SECONDS - (now - last_activity(p)))
        file_rows.append(
            f'<div class="file"><a href="/files/{urllib.parse.quote(p.name)}"'
            f' download>{html.escape(p.name)}</a>'
            f'<div class="meta">{fmt_size(p.stat().st_size)} · '
            f'wird in {int(left // 60)}:{int(left % 60):02d} min gelöscht'
            f"</div></div>")
    jobs_html = ("<h2>Jobs</h2>" + "".join(job_rows)) if job_rows else ""
    files_html = ("<h2>Dateien</h2>" + "".join(file_rows)) if file_rows else ""
    return PAGE.format(jobs=jobs_html, files=files_html,
                       ttl=TTL_SECONDS // 60)


class Handler(BaseHTTPRequestHandler):
    server_version = "yt-dl-temp/1.0"

    def _send(self, code, body, ctype="text/html; charset=utf-8"):
        data = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = urllib.parse.urlsplit(self.path).path
        if path in ("/", "/index.html"):
            self._send(200, render_page())
        elif path.startswith("/files/"):
            name = Path(urllib.parse.unquote(path[len("/files/"):])).name
            self._serve_file(name)
        else:
            self._send(404, "not found", "text/plain")

    def _serve_file(self, name):
        p = TEMP_DIR / name
        if not name:
            self._send(404, "not found", "text/plain")
            return
        try:
            size = p.stat().st_size
            f = open(p, "rb")
        except OSError:
            self._send(404, "not found", "text/plain")
            return
        ctype = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
        note_access(p.name)  # the 10-min clock restarts on every fetch
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
        path = urllib.parse.urlsplit(self.path).path
        if path != "/download":
            self._send(404, "not found", "text/plain")
            return
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length).decode("utf-8", "replace")
        ctype = self.headers.get("Content-Type", "")
        if "application/json" in ctype:
            try:
                data = json.loads(raw or "{}")
            except json.JSONDecodeError:
                data = {}
        else:
            data = dict(urllib.parse.parse_qsl(raw))
        url = str(data.get("url", "")).strip()
        preset = data.get("preset", "video")
        if not URL_RE.match(url) or preset not in PRESETS:
            self._send(400, render_page().replace(
                "<h1>YouTube Download</h1>",
                '<h1>YouTube Download</h1><div class="job err">ungültige '
                "URL oder Format</div>"))
            return
        job_id = f"{int(time.time() * 1000):x}"
        with _jobs_lock:
            _jobs[job_id] = {"url": url, "preset": preset, "ts": time.time(),
                             "status": "starting", "error": ""}
        threading.Thread(target=run_download,
                         args=(job_id, url, preset), daemon=True).start()
        self.send_response(303)
        self.send_header("Location", "/")
        self.end_headers()

    def log_message(self, fmt, *args):  # quieter journal
        if args and isinstance(args[1], str) and args[1].startswith("POST"):
            super().log_message(fmt, *args)


def main_():
    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    load_access()
    threading.Thread(target=cleanup_loop, daemon=True).start()
    host = default_bind()
    server = ThreadingHTTPServer((host, PORT), Handler)
    print(f"serving on http://{host}:{PORT}, temp dir {TEMP_DIR}, "
          f"ttl {TTL_SECONDS}s", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main_()
