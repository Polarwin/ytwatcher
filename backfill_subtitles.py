#!/usr/bin/env python3
"""Backfill sidecar subtitles for already-downloaded videos.

For every video file under a download folder that has a YouTube ID in its
name and no matching .vtt sidecar yet, fetch subtitles with yt-dlp
(--skip-download, real subs first, auto-generated as fallback, converted
to WebVTT). Files land as "<video stem>.<lang>.vtt" next to the video,
which is exactly what scan_downloads picks up for the web player.

Usage:
    .venv/bin/python backfill_subtitles.py [--dry-run] [--langs es.*] [DIR]

DIR defaults to the Espanol folder of the configured download_dir.
The index page picks new sidecars up at the next scan round (the page
fingerprint covers them, so index.html is rebuilt automatically).
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import main  # noqa: E402

log = main.log


def needs_subtitles(path, langs):
    """True when no .vtt sidecar for the video exists yet."""
    try:
        return not any(
            p.suffix == ".vtt" and p.name.startswith(path.stem + ".")
            for p in path.parent.iterdir()
        )
    except OSError:
        return False


def fetch_subtitles(path, video_id, langs, dry_run):
    # Output template = existing filename with %(ext)s, so the sidecar
    # lands as "<stem>.<lang>.vtt" next to the video. Escape literal %
    # for yt-dlp's template syntax.
    template = str(path.parent / (path.stem.replace("%", "%%") + ".%(ext)s"))
    cmd = [
        main.YT_DLP,
        "--skip-download",
        "--write-subs",
        "--write-auto-subs",
        "--sub-langs", langs,
        "--convert-subs", "vtt",
        "-o", template,
        f"https://www.youtube.com/watch?v={video_id}",
    ]
    if dry_run:
        print(f"[dry-run] {path.name}")
        return True
    result = main.run_yt_dlp(cmd, context=f"backfill subs {video_id}")
    if result.returncode != 0:
        # yt-dlp fails the whole run when one of several matched subtitle
        # variants (e.g. es-en auto-translate) hits HTTP 429 — but the
        # main sidecar may already be written. Count that as success.
        if not needs_subtitles(path, langs):
            log.warning("subtitle backfill partial for %s: rc=%d, "
                        "but a sidecar exists", path.name, result.returncode)
            return True
        log.error("subtitle backfill FAILED for %s (%s): %s",
                  path.name, video_id, result.stderr.strip()[:200])
        return False
    return not needs_subtitles(path, langs)


def main_cli():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--langs", default="es.*",
                        help="yt-dlp --sub-langs value (default: es.*)")
    parser.add_argument("--delay", type=float, default=2.0,
                        help="seconds between requests (default: 2)")
    parser.add_argument("dir", nargs="?", default=None,
                        help="folder to scan (default: <download_dir>/Espanol)")
    args = parser.parse_args()

    if args.dir:
        root = Path(args.dir)
    else:
        cfg = main.load_config()
        root = Path(cfg.get("settings", {}).get(
            "download_dir", "/srv/files")) / "Espanol"
    if not root.is_dir():
        sys.exit(f"not a directory: {root}")

    todo, done, failed, skipped = 0, 0, 0, 0
    for path in sorted(root.rglob("*")):
        if not main.is_video_file(path):
            continue
        if "watched" in path.relative_to(root).parts[:-1]:
            skipped += 1
            continue  # archived watched files
        match = main.VIDEO_ID_RE.search(path.name)
        if not match:
            skipped += 1
            continue  # no YouTube ID in the name
        if not needs_subtitles(path, args.langs):
            skipped += 1
            continue
        todo += 1
        print(f"[{todo}] {path.relative_to(root)}", flush=True)
        ok = fetch_subtitles(path, match.group(1), args.langs, args.dry_run)
        if ok:
            done += 1
        else:
            failed += 1
        if not args.dry_run and args.delay:
            time.sleep(args.delay)
    print(f"done: {done} with subtitles, {failed} failed, "
          f"{skipped} skipped (already had subs / no ID / watched)")


if __name__ == "__main__":
    main_cli()
