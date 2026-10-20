"""Language-pair lexicons, loaded lazily and refreshed after atomic rebuilds."""
import json
from pathlib import Path
import threading
import urllib.parse

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
    if entry.get("s"):
        answer["senses"] = []
        for sense in entry["s"]:
            detail = {"pos": sense.get("p", ""), "meanings": sense["g"],
                      "method": sense.get("o", "direct")}
            for compact, public in (("l", "lemma"), ("i", "inf"), ("f", "form"),
                                    ("t", "tags"), ("id", "source_id"), ("d", "definition")):
                if sense.get(compact):
                    detail[public] = sense[compact]
            reference = sense.get("q") or sense.get("w") or entry.get("w", "")
            source_id = sense.get("id", "")
            marker = "-" + entry.get("src", "") + "-"
            if not sense.get("q") and source_id.startswith("en-") and marker in source_id:
                reference = source_id[3:].rsplit(marker, 1)[0]
            source_language = "English" if sense.get("q") else {"es": "Spanish", "de": "German"}.get(entry.get("src"), "")
            if sense.get("o") != "reviewed":
                detail["source_url"] = "https://en.wiktionary.org/wiki/" + urllib.parse.quote(reference, safe="") + "#" + source_language
            if sense.get("v"):
                detail["translation_method"] = sense["v"]["method"]
                if sense["v"].get("word"):
                    detail["translation_source_url"] = "https://en.wiktionary.org/wiki/" + urllib.parse.quote(sense["v"]["word"], safe="") + "#English"
            answer["senses"].append(detail)
        answer["source"] = "Kaikki/Wiktionary"
    return answer


def _spelling(entries, word, source):
    if language(source) == "de":
        return next((w for w in (word, word.lower(), word.capitalize()) if w in entries), None)
    return word.lower() if word.lower() in entries else None


def _resolve(entries, word, source, pos=None, trail=()):
    spelling = _spelling(entries, word, source)
    marker = (spelling, pos)
    if spelling is None or marker in trail or len(trail) >= 16:
        return []
    entry = entries[spelling]
    if "s" not in entry:
        if pos and entry.get("p") and entry["p"] != pos:
            return []
        return [dict(entry, _root=spelling)] if entry.get("g") or entry.get("e") else []
    found = []
    for node in entry["s"]:
        if pos and node.get("p") != pos:
            continue
        parents = _resolve(entries, node["l"], source, node.get("p"), (*trail, marker)) if node.get("l") else []
        variants = [node] if node.get("g") else parents
        for variant in variants:
            resolved = dict(node)
            resolved["g"] = list(node.get("g") or variant.get("g") or [])
            if not node.get("g"):
                via = variant.get("v")
                if not via and variant.get("o") in ("aligned", "reviewed"):
                    via = {"method": variant["o"], "word": variant.get("q", "")}
                if via:
                    resolved["v"] = via
            if not resolved["g"]:
                continue
            root = (parents[0].get("_root") if node.get("g") and parents else variant.get("_root")) or spelling
            resolved["_root"] = root
            if node.get("p") == "verb" and node.get("l") and parents:
                resolved["i"] = parents[0].get("i") or root
            if node.get("l") and not node.get("f"):
                resolved["f"] = " ".join(node.get("t", [])) + " of " + node["l"]
            # A table can contain duplicate grammatical routes. Keep distinct
            # noun/verb meanings and source forms while avoiding repeat glosses.
            signature = (resolved.get("p"), tuple(resolved["g"]), resolved.get("f"), resolved.get("l"))
            if not any((s.get("p"), tuple(s["g"]), s.get("f"), s.get("l")) == signature for s in found):
                found.append(resolved)
    return found


def lookup(entries, word, source):
    spelling = _spelling(entries, word, source)
    if spelling is None:
        return None
    entry = entries[spelling]
    if "s" not in entry:
        return entry
    senses = _resolve(entries, spelling, source)
    if not senses:
        return None
    first = senses[0]
    glosses = list(dict.fromkeys(g for sense in senses for g in sense["g"]))
    answer = {"g": glosses, "p": first.get("p", ""), "s": senses, "w": spelling, "src": language(source)}
    if first.get("i"):
        answer["i"] = first["i"]
    return answer
