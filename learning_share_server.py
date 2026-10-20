"""Token-scoped, expiring lesson files on Frankfurt; uploads use SSH only."""
import json
import hashlib
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime, timezone
import mimetypes
from pathlib import Path
import re
import shutil
import sys
import tarfile
import time
import threading
import urllib.parse
import uuid

ROOT = Path(__file__).resolve().parent / '.learning-shares'
FILES = frozenset(('index.html', 'pack.json', 'learning_page.js', 'learning_page.css',
                   'learning_sw.js', 'learning_i18n.js', 'learning_share_ui.js', 'manifest.webmanifest', 'subtitles.vtt', 'media.mp4',
                   'media.m4a', 'offline-files.json', 'README.txt'))
TOKEN = re.compile(r'[a-f0-9]{32}')
MAX_BYTES = 2 * 1024 ** 3
MAX_STORAGE_BYTES = 2 * 1024 ** 3
log = logging.getLogger('ytwatcher.learning-share')
ACCESS_LOG = ROOT.parent / '.learning-access-logs' / 'access.jsonl'
_access_logger = None
_access_lock = threading.Lock()


def record_access(handler, status):
    """Bounded request logs; never record bearer URLs, cookies or credentials."""
    global _access_logger
    try:
        with _access_lock:
            if _access_logger is None:
                ACCESS_LOG.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                ACCESS_LOG.touch(mode=0o600, exist_ok=True)
                sink = RotatingFileHandler(ACCESS_LOG, maxBytes=10 * 1024 ** 2,
                                           backupCount=5, encoding='utf-8')
                sink.setFormatter(logging.Formatter('%(message)s'))
                _access_logger = logging.getLogger('ytwatcher.learning-share.access')
                _access_logger.setLevel(logging.INFO)
                _access_logger.propagate = False
                _access_logger.addHandler(sink)
        path = urllib.parse.unquote(urllib.parse.urlsplit(handler.path).path)
        match = re.fullmatch(r'/learn/([a-f0-9]{32})(?:/([^/]*))?', path)
        token, name = match.groups() if match else (None, None)
        info = metadata(token) if token else None
        asset = (name or 'index.html') if match else None
        row = {'time': datetime.now(timezone.utc).isoformat(),
               'method': handler.command, 'status': status,
               'share_id': hashlib.sha256(token.encode()).hexdigest()[:16] if token else None,
               'lesson_id': info.get('id') if info else None,
               'asset': asset if asset in FILES else None,
               'page_view': handler.command == 'GET' and status == 200 and asset == 'index.html',
               'user_agent': handler.headers.get('User-Agent', '')[:400]}
        _access_logger.info(json.dumps(row, ensure_ascii=True))
    except Exception:
        # Analytics must not interrupt playback, including when storage is full.
        log.exception('Could not write learning-page access log')


class _AccessHandler:
    def __init__(self, handler):
        self.handler = handler

    def __getattr__(self, name):
        return getattr(self.handler, name)

    def send_response(self, code, message=None):
        self.handler.send_response(code, message)
        record_access(self.handler, code)


def metadata(token):
    if not TOKEN.fullmatch(token):
        return None
    try:
        value = json.loads((ROOT / token / '.share.json').read_text())
        return value if value['expires'] > time.time() else None
    except (OSError, ValueError, KeyError, TypeError):
        return None


def cleanup():
    if not ROOT.is_dir():
        return
    for folder in ROOT.iterdir():
        if folder.is_dir() and TOKEN.fullmatch(folder.name) and metadata(folder.name) is None:
            shutil.rmtree(folder, ignore_errors=True)
        elif folder.name.startswith('.upload-') and folder.stat().st_mtime < time.time() - 86400:
            shutil.rmtree(folder, ignore_errors=True)


def message(handler, code, text):
    body = text.encode()
    handler.send_response(code)
    handler.send_header('Content-Type', 'text/plain; charset=utf-8')
    handler.send_header('Content-Length', str(len(body)))
    handler.send_header('Cache-Control', 'no-store')
    handler.send_header('Referrer-Policy', 'no-referrer')
    handler.end_headers()
    if handler.command != 'HEAD':
        handler.wfile.write(body)


def serve(handler):
    """Return True for /learn routes. Never enumerate folders or private downloads."""
    path = urllib.parse.unquote(urllib.parse.urlsplit(handler.path).path)
    if path != '/learn' and not path.startswith('/learn/'):
        return False
    handler = _AccessHandler(handler)
    match = re.fullmatch(r'/learn/([a-f0-9]{32})(?:/([^/]*))?', path)
    if not match:
        message(handler, 404, 'Learning link not found.')
        return True
    token, name = match.groups()
    if metadata(token) is None:
        message(handler, 410, 'This learning link has expired or was revoked.')
        return True
    if name is None:
        handler.send_response(308)
        handler.send_header('Location', '/learn/' + token + '/index.html')
        handler.send_header('Content-Length', '0')
        handler.end_headers()
        return True
    name = name or 'index.html'
    file = ROOT / token / name
    if name not in FILES or file.is_symlink() or not file.is_file():
        message(handler, 404, 'Lesson file not found.')
        return True
    try:
        with file.open('rb') as source:
            size = file.stat().st_size
            begin, end = 0, size - 1
            requested = handler.headers.get('Range')
            if requested:
                span = re.fullmatch(r'bytes=(\d*)-(\d*)', requested)
                if not span or not any(span.groups()):
                    message(handler, 416, 'Invalid media range.')
                    return True
                begin = int(span[1]) if span[1] else max(0, size - int(span[2]))
                end = min(int(span[2]), size - 1) if span[1] and span[2] else size - 1
                if begin > end or begin >= size:
                    handler.send_response(416)
                    handler.send_header('Content-Range', f'bytes */{size}')
                    handler.send_header('Content-Length', '0')
                    handler.end_headers()
                    return True
            handler.send_response(206 if requested else 200)
            types = {'.js': 'application/javascript', '.webmanifest': 'application/manifest+json', '.vtt': 'text/vtt'}
            handler.send_header('Content-Type', types.get(file.suffix) or mimetypes.guess_type(name)[0] or 'application/octet-stream')
            handler.send_header('Content-Length', str(max(0, end - begin + 1)))
            handler.send_header('Accept-Ranges', 'bytes')
            if requested:
                handler.send_header('Content-Range', f'bytes {begin}-{end}/{size}')
            handler.send_header('Cache-Control', 'private, max-age=0, must-revalidate')
            handler.send_header('Referrer-Policy', 'no-referrer')
            handler.send_header('X-Robots-Tag', 'noindex, nofollow, noarchive')
            handler.send_header('X-Content-Type-Options', 'nosniff')
            handler.end_headers()
            if handler.command != 'HEAD':
                source.seek(begin)
                remaining = end - begin + 1
                while remaining > 0:
                    data = source.read(min(256 * 1024, remaining))
                    if not data:
                        break
                    handler.wfile.write(data)
                    remaining -= len(data)
    except (BrokenPipeError, ConnectionResetError):
        pass
    except FileNotFoundError:
        # Revocation/expiry can remove the file between validation and opening.
        message(handler, 410, 'This learning link has expired or was revoked.')
    return True


def publish(token, days, stream):
    if not TOKEN.fullmatch(token) or days not in (1, 5):
        raise ValueError('Invalid share request')
    ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
    cleanup()
    folder = ROOT / ('.upload-' + uuid.uuid4().hex)
    folder.mkdir(mode=0o700)
    try:
        total, received = 0, set()
        with tarfile.open(fileobj=stream, mode='r|') as archive:
            for member in archive:
                if member.name not in FILES or not member.isfile() or member.name in received:
                    raise ValueError('Invalid lesson asset')
                total += member.size
                if total > MAX_BYTES or member.size < 0:
                    raise ValueError('Lesson package exceeds 2 GB')
                received.add(member.name)
                with archive.extractfile(member) as source, (folder / member.name).open('wb') as target:
                    shutil.copyfileobj(source, target, length=256 * 1024)
        required = FILES - {'media.mp4', 'media.m4a'}
        if not required.issubset(received) or not received.intersection({'media.mp4', 'media.m4a'}):
            raise ValueError('Incomplete learning package')
        used = sum(file.stat().st_size for directory in ROOT.iterdir()
                   if directory.is_dir() and TOKEN.fullmatch(directory.name)
                   for file in directory.iterdir() if file.is_file())
        if used + total > MAX_STORAGE_BYTES:
            raise ValueError('Frankfurt learning shares have reached their 2 GB storage limit. Revoke older links or choose a shorter clip.')
        pack = json.loads((folder / 'pack.json').read_text())
        expires = time.time() + days * 86400
        pack.update(shared=True, share_expires=expires)
        (folder / 'pack.json').write_text(json.dumps(pack, ensure_ascii=False))
        offline = json.loads((folder / 'offline-files.json').read_text())
        offline['files'] = sorted(received - {'README.txt', 'offline-files.json'})
        (folder / 'offline-files.json').write_text(json.dumps(offline))
        data = json.dumps(pack, ensure_ascii=False).replace('<', '\\u003c').replace('\u2028', '\\u2028').replace('\u2029', '\\u2029')
        page = (folder / 'index.html').read_text()
        page = re.sub(r'(<script type="application/json" id="pack-data">).*?(</script>)',
                      lambda m: m[1] + data + m[2], page, count=1, flags=re.S)
        # Old exports may predate the runtime shared-page header handling.
        page = re.sub(r'<a href="(?:\.\./index\.html|/ytwatcher/)">.*?</a>', '', page)
        (folder / 'index.html').write_text(page)
        info = {'token': token, 'expires': expires, 'id': pack['id'], 'created': time.time()}
        (folder / '.share.json').write_text(json.dumps(info))
        if (ROOT / token).exists():
            raise ValueError('Share already exists')
        folder.rename(ROOT / token)
        print(json.dumps(info), flush=True)
    finally:
        if folder.exists():
            shutil.rmtree(folder, ignore_errors=True)


if __name__ == '__main__':
    action, token = sys.argv[1:3]
    if not TOKEN.fullmatch(token):
        raise ValueError('Invalid link token')
    if action == 'publish':
        publish(token, int(sys.argv[3]), sys.stdin.buffer)
    elif action == 'revoke':
        shutil.rmtree(ROOT / token, ignore_errors=True)
        print(json.dumps({'revoked': True}))
    else:
        raise ValueError('Unknown action')
