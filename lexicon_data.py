"""Language-pair lexicons, loaded lazily and refreshed after atomic rebuilds."""
import json
from pathlib import Path
import threading

ROOT = Path(__file__).parent
TARGETS = {"es": ("en", "de", "zh"), "de": ("es",)}
PAIRS = tuple((src, dst) for src, targets in TARGETS.items() for dst in targets)
_cache = {}
_lock = threading.Lock()


def language(code):
    return code.lower().split("-")[0]


def path_for(src, dst):
    return ROOT / f"lexicon-{language(src)}-{language(dst)}.json"


def signature(src, dst):
    path = path_for(src, dst)
    try:
        info = path.stat()
        return f"{info.st_mtime_ns}:{info.st_size}"
    except FileNotFoundError:
        return "missing"


def revision(src):
    src = language(src)
    return {dst: signature(src, dst) for dst in TARGETS.get(src, ("en",))}


def load(src, dst):
    pair = (language(src), language(dst))
    stamp = signature(*pair)
    with _lock:
        previous, data = _cache.get(pair, (None, {}))
        if previous != stamp:
            if stamp == "missing":
                data = {}
            else:
                with path_for(*pair).open(encoding="utf-8") as file:
                    data = json.load(file)
                if not isinstance(data, dict):
                    raise ValueError("Invalid offline lexicon")
            _cache[pair] = (stamp, data)
        return data


def result(entry):
    if not entry:
        return None
    meanings = entry.get("g") or ([entry["e"]] if entry.get("e") else [])
    if not meanings:
        return None
    answer = {"en": meanings[0]}
    if len(meanings) > 1:
        answer["meanings"] = meanings[1:]
    if entry.get("p"):
        answer["pos"] = entry["p"]
    if entry.get("i"):
        answer["inf"] = entry["i"]
    return answer


def lookup(entries, word, source):
    if language(source) == "de":
        return entries.get(word) or entries.get(word.lower()) or entries.get(word.capitalize())
    return entries.get(word.lower())
