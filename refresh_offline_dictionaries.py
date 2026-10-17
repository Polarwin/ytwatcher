#!/usr/bin/env python3
"""Refresh subtitle word dictionaries for the current library, entirely locally."""
import argparse
from pathlib import Path

import main as watcher
import lexicon_data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, help="Defaults to configured download_dir")
    args = parser.parse_args()
    root = args.root or Path(watcher.load_config().get("settings", {}).get("download_dir", "/srv/files"))
    paths = set()
    directories = {}
    for video in watcher.walk_video_files(root):
        if "watched" in video.relative_to(root).parts[:-1]:
            continue
        if video.parent not in directories:
            directories[video.parent] = [path for path in video.parent.iterdir() if path.suffix == ".vtt"]
        for vtt in directories[video.parent]:
            if not vtt.name.startswith(video.stem + "."):
                continue
            if lexicon_data.language(watcher.subtitle_language(vtt)) in lexicon_data.TARGETS:
                paths.add(vtt)
    failed = 0
    for index, path in enumerate(sorted(paths), 1):
        job = {"status": "running", "done": 0, "total": 0}
        watcher._run_dict_job(path, str(path.relative_to(root)), job)
        if job["status"] != "done":
            failed += 1
        print(f"{index}/{len(paths)} {job['status']}: {path.name}", flush=True)
    print(f"Refreshed {len(paths) - failed} subtitle dictionaries; {failed} failed.", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
