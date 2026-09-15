#!/usr/bin/env python3
"""Install shared static routing and migrate ReinforceLearning with --apply."""
import argparse
from contextlib import contextmanager
from datetime import datetime
import os
import pwd
from pathlib import Path
import shutil
import subprocess
import tempfile

SITE = Path("/etc/nginx/sites-available/homeserver")
ROOT = Path("/srv/files/static")
OLD_FOLDER = Path("/srv/files/ReinforceLearning")
NEW_FOLDER = ROOT / "ReinforceLearning"
MARKER = "    location /ytwatcher/ {"
LEGACY_ROUTE = """    # ytwatcher-static-reinforcelearning
    location = /ytwatcher/static/ReinforceLearning {
        return 301 /ytwatcher/static/ReinforceLearning/;
    }
    location ^~ /ytwatcher/static/ReinforceLearning/ {
        alias /srv/files/ReinforceLearning/;
        autoindex on;
        autoindex_exact_size off;
        autoindex_localtime on;
        disable_symlinks on;
        limit_except GET HEAD { deny all; }
    }

"""
ROUTE = """    # ytwatcher-static-root
    location = /ytwatcher/static {
        return 301 /ytwatcher/static/;
    }
    location ^~ /ytwatcher/static/ {
        alias /srv/files/static/;
        autoindex on;
        autoindex_exact_size off;
        autoindex_localtime on;
        limit_except GET HEAD { deny all; }
    }

"""


@contextmanager
def network_user():
    """Use the sudo caller's credentials on root-squashed network shares."""
    if os.geteuid() != 0:
        yield
        return
    username = os.environ.get("SUDO_USER")
    if not username or username == "root":
        raise RuntimeError("Run sudo from your normal network-share user account")
    account = pwd.getpwnam(username)
    old_gid, old_groups = os.getegid(), os.getgroups()
    try:
        os.initgroups(account.pw_name, account.pw_gid)
        os.setegid(account.pw_gid)
        os.seteuid(account.pw_uid)
        yield
    finally:
        os.seteuid(0)
        os.setegid(old_gid)
        os.setgroups(old_groups)


def updated_config(original):
    if ROUTE in original:
        return original
    if LEGACY_ROUTE in original:
        return original.replace(LEGACY_ROUTE, ROUTE, 1)
    if "/ytwatcher/static" in original:
        raise ValueError("An existing route needs manual review")
    if original.count(MARKER) != 1:
        raise ValueError("Expected exactly one ytwatcher location in the homeserver site")
    return original.replace(MARKER, ROUTE + MARKER, 1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Install, validate and reload nginx")
    args = parser.parse_args()
    original = SITE.read_text()
    candidate = updated_config(original)
    with network_user():
        if OLD_FOLDER.exists() and NEW_FOLDER.exists():
            parser.error("Both old and new ReinforceLearning folders exist; refusing to overwrite either")
        if not OLD_FOLDER.is_dir() and not NEW_FOLDER.is_dir():
            parser.error("ReinforceLearning folder not found at either location")
    if not args.apply:
        print(ROUTE)
        if OLD_FOLDER.exists():
            print(f"Will move {OLD_FOLDER} to {NEW_FOLDER}")
        print("Preview only. Apply with: sudo python3 install_static_route.py --apply")
        return
    if os.geteuid() != 0:
        parser.error("--apply requires sudo")
    nginx = shutil.which("nginx") or "/usr/sbin/nginx"
    subprocess.run([nginx, "-t"], check=True)
    backup = None
    if candidate != original:
        backup = SITE.with_name(SITE.name + ".bak-static-" + datetime.now().strftime("%Y%m%d%H%M%S%f"))
        shutil.copy2(SITE, backup)
        with tempfile.NamedTemporaryFile(mode="w", dir=SITE.parent, delete=False) as f:
            f.write(candidate)
            temporary = Path(f.name)
        shutil.copystat(SITE, temporary)
        temporary.replace(SITE)
    moved = False
    try:
        subprocess.run([nginx, "-t"], check=True)
        with network_user():
            ROOT.mkdir(mode=0o755, exist_ok=True)
            if OLD_FOLDER.exists():
                if NEW_FOLDER.exists():
                    raise FileExistsError(f"Refusing to overwrite {NEW_FOLDER}")
                OLD_FOLDER.rename(NEW_FOLDER)
                moved = True
        subprocess.run(["systemctl", "reload", "nginx"], check=True)
    except (OSError, subprocess.CalledProcessError):
        try:
            if moved:
                with network_user():
                    NEW_FOLDER.rename(OLD_FOLDER)
        finally:
            if backup:
                shutil.copy2(backup, SITE)
        raise
    if backup:
        print(f"Previous configuration saved to {backup}")
    if moved:
        print(f"Moved {OLD_FOLDER} to {NEW_FOLDER}")
    print("Ready: https://192.168.0.9/ytwatcher/static/ReinforceLearning/")


if __name__ == "__main__":
    main()
