#!/usr/bin/env python3
"""Refresh subtitle word dictionaries for the current library, entirely locally."""
import argparse
import json
import re
import shutil
from pathlib import Path

import main as watcher
import lexicon_data
import learning_export


def refresh_lessons():
    refreshed = 0
    failed = 0
    for folder in sorted(learning_export.OUTPUT.iterdir()):
        if not folder.is_dir() or not re.fullmatch(r'[a-f0-9]{32}', folder.name):
            continue
        try:
            pack = json.loads((folder / 'pack.json').read_text())
            source = lexicon_data.language(pack.get('source', 'und'))
            if source in lexicon_data.TARGETS and not pack.get('listening_only'):
                dictionaries, _, _ = learning_export.vocabulary(pack['sentences'], source)
                pack['dictionary'] = dictionaries
                pack['dictionary_revision'] = lexicon_data.revision(source)
                payload = json.dumps(pack, ensure_ascii=False).replace('<', '\\u003c').replace('\u2028', '\\u2028').replace('\u2029', '\\u2029')
                page = (folder / 'index.html').read_text()
                page, count = re.subn(r'(<script type="application/json" id="pack-data">).*?(</script>)',
                    lambda match: match[1] + payload + match[2], page, count=1, flags=re.S)
                if count != 1:
                    raise ValueError('Missing embedded lesson data')
                learning_export.atomic(folder / 'pack.json', json.dumps(pack, ensure_ascii=False))
                learning_export.atomic(folder / 'index.html', page)
            for name in ('learning_i18n.js', 'learning_share_ui.js', 'learning_page.css', 'learning_page.js', 'learning_sw.js'):
                shutil.copyfile(learning_export.ASSETS / name, folder / name)
            refreshed += 1
            print(f'Lesson refreshed: {folder.name}', flush=True)
        except Exception as exc:
            failed += 1
            print(f'Lesson refresh failed: {folder.name}: {exc}', flush=True)
    learning_export.publish_library()
    print(f'Refreshed {refreshed} learning pages; {failed} failed.', flush=True)
    return failed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, help="Defaults to configured download_dir")
    parser.add_argument("--skip-lessons", action="store_true", help="Refresh subtitle sidecars only")
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
    if not args.skip_lessons and learning_export.OUTPUT.is_dir():
        failed += refresh_lessons()
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
