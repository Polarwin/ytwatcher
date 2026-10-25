"""Conservative episode identity for alternate uploads of subscription episodes."""
import json
import os
from pathlib import Path
import re
import unicodedata


def episode_key(title):
    """Return series/season/episode, or None when the title is ambiguous."""
    title = unicodedata.normalize('NFKC', title).casefold()
    if re.search(r'preview|trailer|\bclip\b|预告|預告|花絮|合集|全集|总集|總集|'
                 r'上集|下集|上篇|下篇|前篇|后篇|後篇|\bpart\s*\d+', title):
        return None
    pattern = r'(?<![a-z0-9])ep(?:isode)?\.?\s*(\d+)(?!\d)|第\s*(\d+)\s*[集话話]'
    matches = list(re.finditer(pattern, title))
    episodes = {int(m[1] or m[2]) for m in matches}
    if len(episodes) != 1:
        return None
    # Compilations such as EP216-218 must not occupy a single episode key.
    if any(re.match(r'\s*[-~–—至到]\s*(?:ep\s*)?\d+', title[m.end():])
           for m in matches):
        return None
    aliases = (
        ('斗破苍穹', ('斗破苍穹', '斗破蒼穹', 'battle through the heavens')),
        ('凡人修仙传', ('凡人修仙传', '凡人修仙傳', "a mortal's journey",
                       'a record of a mortal')),
    )
    series = next((name for name, names in aliases if any(n in title for n in names)), None)
    if series is None:
        named = re.findall(r'《([^》]+)》', title)
        if len(set(named)) != 1:
            return None
        series = re.sub(r'\s+', '', named[0])
    season = re.search(r'\b(?:season\s*|s)(\d+)\b|第\s*(\d+)\s*季', title)
    return [series, int(season[1] or season[2]) if season else None, episodes.pop()]


class EpisodeHistory:
    """A subscription-local ledger of completed downloads, retained after deletion.

    Only the subscription watcher writes this file; manual downloads stay explicit.
    """
    def __init__(self, root, files):
        self.root = Path(root)
        self.path = self.root / '.episode-history.json'
        self.entries = json.loads(self.path.read_text()) if self.path.exists() else {}
        if not isinstance(self.entries, dict):
            raise ValueError('Invalid episode history')
        self.changed = False
        for path in sorted(files):
            # yt-dlp may leave separate audio/video streams while a merge runs.
            if re.search(r'\.f\d+\.', path.name):
                continue
            match = re.search(r'\[([A-Za-z0-9_-]{11})\]', path.name)
            if match:
                relative = path.relative_to(self.root)
                source = '/'.join(p for p in relative.parts[:-1] if p != 'watched')
                self.remember(source, path.name, match[1])

    def key(self, source, title):
        identity = episode_key(title)
        return json.dumps([source, *identity], ensure_ascii=False) if identity else None

    def find(self, source, title):
        return self.entries.get(self.key(source, title))

    def remember(self, source, title, video_id):
        key = self.key(source, title)
        if key and key not in self.entries:
            self.entries[key] = {'video_id': video_id, 'title': title}
            self.changed = True

    def save(self):
        if not self.changed:
            return
        self.root.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(self.path.name + f'.{os.getpid()}.tmp')
        try:
            temporary.write_text(json.dumps(self.entries, ensure_ascii=False, indent=2))
            temporary.replace(self.path)
        finally:
            temporary.unlink(missing_ok=True)
        self.changed = False
