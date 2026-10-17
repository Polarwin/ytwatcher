"""Copy one learning package to Frankfurt and manage its expiring link."""
import json
import logging
import os
from pathlib import Path
import re
import subprocess
import tarfile
import threading
import time
import uuid

import learning_export
from learning_share_server import FILES, MAX_BYTES

STATE = Path(__file__).with_name('.learning-shares.json')
HOST = os.environ.get('YTWATCHER_SHARE_SSH', 'frankfurt')
REMOTE = '/home/justin/ytwatcher/learning_share_server.py'
PUBLIC = 'https://ytwatcher.duckdns.org/learn/'
_lock = threading.Lock()
_jobs = {}
_gate = threading.BoundedSemaphore(1)
log = logging.getLogger('ytwatcher.learning-share')


def _saved():
    try:
        data = json.loads(STATE.read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _store(data):
    temporary = STATE.with_name(STATE.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        temporary.write_text(json.dumps(data))
        temporary.chmod(0o600)
        temporary.replace(STATE)
    finally:
        temporary.unlink(missing_ok=True)


def _id(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-f0-9]{32}', value):
        raise ValueError('Choose an exported learning clip.')
    return value


def status(pack_id):
    _id(pack_id)
    with _lock:
        if pack_id in _jobs:
            job = dict(_jobs[pack_id])
            if job['status'] == 'done' and job['expires'] <= time.time():
                job['status'] = 'expired'
                job.pop('stage', None)
            return job
        info = _saved().get(pack_id)
        if info:
            return dict(info, status='done' if info['expires'] > time.time() else 'expired')
        return {'id': pack_id, 'status': 'none'}


def start(data, revoke=False):
    if not isinstance(data, dict):
        raise ValueError('Expected a share request.')
    pack_id = _id(data.get('id'))
    days = data.get('days', 5)
    if type(days) is not int or days not in (1, 5):
        raise ValueError('Choose a 1-day or 5-day link.')
    folder = learning_export.OUTPUT / pack_id
    if not revoke and not (folder / 'pack.json').is_file():
        raise ValueError('Export the learning clip first.')
    with _lock:
        job = _jobs.get(pack_id)
        if job and job['status'] in ('uploading', 'revoking'):
            return dict(job)
        info = _saved().get(pack_id)
        if not revoke and info and info['expires'] > time.time():
            return dict(info, status='done')
        if revoke and not info:
            return {'id': pack_id, 'status': 'revoked'}
        if not _gate.acquire(blocking=False):
            raise ValueError('Another share is being uploaded. Please wait.')
        job = {'id': pack_id, 'status': 'revoking' if revoke else 'uploading', 'stage': 'Revoking link' if revoke else 'Copying lesson to Frankfurt'}
        _jobs[pack_id] = job
        token = info['token'] if revoke else uuid.uuid4().hex
        threading.Thread(target=_worker, args=(pack_id, token, days, revoke), daemon=True).start()
        return dict(job)


def _worker(pack_id, token, days, revoke):
    process = None
    try:
        args = ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=15', '-o', 'ServerAliveInterval=20',
                '-o', 'ServerAliveCountMax=3', HOST, 'python3', REMOTE, 'revoke' if revoke else 'publish', token]
        if not revoke:
            args.append(str(days))
        process = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if not revoke:
            folder = learning_export.OUTPUT / pack_id
            # Use current standalone scripts, including shared-page behavior, for older exports too.
            total = 0
            with tarfile.open(fileobj=process.stdin, mode='w|') as archive:
                for name in sorted(FILES):
                    file = folder / name
                    if name in ('learning_page.js', 'learning_page.css', 'learning_sw.js', 'learning_share_ui.js'):
                        file = Path(__file__).with_name(name)
                    if not file.is_file():
                        continue
                    if file.is_symlink():
                        raise ValueError('Invalid lesson asset')
                    total += file.stat().st_size
                    if total > MAX_BYTES:
                        raise ValueError('This lesson exceeds the 2 GB sharing limit.')
                    archive.add(file, arcname=name, recursive=False)
        process.stdin.close()
        process.stdin = None
        output, errors = process.communicate(timeout=3600)
        if process.returncode:
            log.error('Frankfurt share command failed: %s', errors.decode(errors='replace')[-2000:])
            raise RuntimeError('Could not revoke the link on Frankfurt. Please try again.' if revoke else 'Could not publish the lesson on Frankfurt. Please try again.')
        result = json.loads(output)
        with _lock:
            saved = _saved()
            if revoke:
                saved.pop(pack_id, None)
                job = {'id': pack_id, 'status': 'revoked', 'stage': 'Link revoked'}
            else:
                info = {'id': pack_id, 'token': token, 'expires': result['expires'],
                        'url': PUBLIC + token + '/index.html'}
                saved[pack_id] = info
                job = dict(info, status='done', stage='Ready to share')
            _store(saved)
            _jobs[pack_id] = job
    except Exception as exc:
        if process and process.poll() is None:
            process.kill()
            if process.stdin and process.stdin.closed:
                process.stdin = None
            process.communicate()
        log.exception('Learning share failed')
        with _lock:
            _jobs[pack_id] = {'id': pack_id, 'status': 'failed', 'error': str(exc)[:400]}
    finally:
        _gate.release()
