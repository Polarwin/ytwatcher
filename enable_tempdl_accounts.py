#!/usr/bin/env python3
"""One-time migration: keep HTTPS proxying, let the app own login accounts.

Run --stage without sudo to prepare/validate the exact Caddyfile change.
Run with sudo to persist it, reload Caddy, and activate account management.
No other site's authentication or routes are changed.
"""
import argparse
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time

PROJECT = Path(__file__).resolve().parent
CADDYFILE = Path('/etc/caddy/Caddyfile')
STAGED = PROJECT / '.tempdl-Caddyfile.staged'
STAMP = PROJECT / '.tempdl-Caddyfile.original-sha256'
ENABLED = PROJECT / '.account-management-enabled'


def migrated_config(original):
    lines = original.splitlines(keepends=True)
    starts = [i for i, line in enumerate(lines)
              if line.strip() == 'ytwatcher.duckdns.org {']
    if len(starts) != 1:
        raise RuntimeError('Expected exactly one ytwatcher.duckdns.org site.')
    start = starts[0]
    depth = 1
    stop = start + 1
    while stop < len(lines) and depth:
        depth += lines[stop].count('{') - lines[stop].count('}')
        stop += 1
    if depth:
        raise RuntimeError('Unbalanced Caddy site block.')
    site = lines[start:stop]
    auth = [i for i, line in enumerate(site) if line.strip() == 'basic_auth {']
    if not auth:
        if 'reverse_proxy http://127.0.0.1:8792' not in ''.join(site):
            raise RuntimeError('Unexpected downloader upstream.')
        return original
    if len(auth) != 1:
        raise RuntimeError('Expected one downloader basic_auth block.')
    a = auth[0]
    b = a + 1
    while b < len(site) and site[b].strip() != '}':
        # Only accept ordinary username/hash lines inside this simple block.
        if '{' in site[b] or '}' in site[b]:
            raise RuntimeError('Unexpected downloader authentication structure.')
        b += 1
    if b == len(site):
        raise RuntimeError('Unclosed authentication block.')
    replacement = site[:a] + site[b + 1:]
    if 'reverse_proxy http://127.0.0.1:8792' not in ''.join(replacement):
        raise RuntimeError('Unexpected downloader upstream.')
    return ''.join(lines[:start] + replacement + lines[stop:])


def validate(path):
    result = subprocess.run(['caddy', 'validate', '--config', str(path),
                             '--adapter', 'caddyfile'], capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError('Caddy validation failed; the active configuration is unchanged.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage', action='store_true')
    args = parser.parse_args()
    if args.stage:
        original = CADDYFILE.read_text()
        STAGED.write_text(migrated_config(original))
        STAGED.chmod(0o600)
        STAMP.write_text(hashlib.sha256(original.encode()).hexdigest())
        validate(STAGED)
        print('Staged and validated: remove Basic auth only from ytwatcher.duckdns.org.')
        return
    if os.geteuid() != 0:
        raise RuntimeError('Activation requires sudo to persist /etc/caddy/Caddyfile.')
    original = CADDYFILE.read_text()
    if hashlib.sha256(original.encode()).hexdigest() != STAMP.read_text().strip():
        raise RuntimeError('Caddyfile changed after preparation. Run --stage again.')
    expected = migrated_config(original)
    if STAGED.read_text() != expected:
        raise RuntimeError('Staged configuration differs from the prepared migration.')
    if 'def update_account(' not in (PROJECT / 'yt_dl_temp.py').read_text():
        raise RuntimeError('Deploy the account-management backend first.')
    # Read credentials and verify account names without displaying any hashes.
    accounts = dict(line.split() for line in (PROJECT / '.web-users').read_text().splitlines()
                    if line.strip() and not line.lstrip().startswith('#'))
    if 'justin' not in accounts:
        raise RuntimeError('Admin account justin is missing.')
    validate(STAGED)
    backup = Path('/var/backups') / ('tempdl-Caddyfile-' + str(time.time_ns()))
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(CADDYFILE, backup)
    backup.chmod(0o600)
    fd, name = tempfile.mkstemp(prefix='.tempdl-', dir=CADDYFILE.parent)
    try:
        with os.fdopen(fd, 'w') as out:
            out.write(expected)
            out.flush()
            os.fsync(out.fileno())
        shutil.copystat(CADDYFILE, name)
        os.replace(name, CADDYFILE)
        result = subprocess.run(['systemctl', 'reload', 'caddy'], capture_output=True, text=True)
        if result.returncode:
            shutil.copy2(backup, CADDYFILE)
            subprocess.run(['systemctl', 'reload', 'caddy'], capture_output=True)
            raise RuntimeError('Caddy reload failed. Original configuration restored.')
        ENABLED.touch(mode=0o600)
        owner = (PROJECT / '.web-users').stat()
        os.chown(ENABLED, owner.st_uid, owner.st_gid)
        print('Activated. justin can add users; every user can change their own password.')
        print('Account changes take effect immediately without service restarts.')
    finally:
        Path(name).unlink(missing_ok=True)


if __name__ == '__main__':
    try:
        main()
    except (OSError, RuntimeError, ValueError) as exc:
        raise SystemExit(str(exc))
