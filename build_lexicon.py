#!/usr/bin/env python3
"""Build compact offline dictionaries from downloaded Kaikki/Wiktionary data.

python build_lexicon.py --all
python build_lexicon.py --lang es --to de

Source JSONL files are retained in .cache/lexicon-source for repeatable rebuilds.
English definitions come directly from source-language entries. Other pairs use
explicit translations first, then translations aligned WITHIN ONE English sense
(never the whole English headword, which would mix unrelated meanings).
No Google or LLM calls are used. Missing translations remain missing.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unicodedata

from dictionary_corrections import CORRECTIONS
from lexicon_data import PAIRS, ROOT, path_for

NAMES = {"es": "Spanish", "de": "German", "en": "English"}
DISFAVORED = {"archaic", "obsolete", "rare", "dated", "historical", "nonstandard"}


def key(word, lang="es"):
    word = unicodedata.normalize("NFC", word).strip()
    return word if lang == "de" else word.lower()


def source_word(word):
    return isinstance(word, str) and 1 <= len(word) <= 100 and not any(c.isspace() for c in word)


def usable(sense):
    return not (sense.get("form_of") or sense.get("alt_of") or
                {"form-of", "alt-of", "no-gloss"} & set(sense.get("tags", [])))


def translations(sense, dst):
    codes = {"zh", "cmn"} if dst == "zh" else {dst}
    values = []
    for tr in sense.get("translations", []):
        word = tr.get("word")
        if (tr.get("lang_code") not in codes or not isinstance(word, str) or
                not word.strip() or len(word) > 500 or
                DISFAVORED & set(tr.get("tags", []))):
            continue
        if dst == "zh" and tr.get("lang", "Chinese") not in ("Chinese", "Chinese Mandarin", "Mandarin"):
            continue
        dialects = {"Hokkien", "Cantonese", "Hakka", "Wu", "Min-Nan", "Dungan"}
        if dst == "zh" and dialects & set(tr.get("tags", [])):
            continue
        if dst == "de" and {"Alemannic-German", "Bavarian", "Low-German"} & set(tr.get("tags", [])):
            continue
        word = unicodedata.normalize("NFC", word.strip())
        if dst == "zh" and "/" in word:
            word = word.rsplit("/", 1)[-1].strip()
        if dst == "zh" and not any("\u3400" <= c <= "\u9fff" for c in word):
            continue
        if word not in values:
            values.append(word)
    return values


def translation_groups(entry):
    """Kaikki keeps unassigned translations at entry level, with sense labels.

    Align only identical nonempty labels; do not mix all translations of a
    polysemous English headword. Entry order retains the usual sense first.
    """
    groups = {}
    for tr in entry.get("translations", []):
        label = tr.get("sense", "").strip()
        if label:
            groups.setdefault(label, []).append(tr)
    for values in groups.values():
        yield {"translations": values}
    for sense in entry.get("senses", []):
        if usable(sense):
            yield sense


def english_meanings(entry):
    meanings = []
    senses = [s for s in entry.get("senses", []) if usable(s)]
    senses.sort(key=lambda s: bool(DISFAVORED & set(s.get("tags", []))))
    for sense in senses:
        for gloss in sense.get("glosses", []) + translations(sense, "en"):
            if isinstance(gloss, str) and 0 < len(gloss) <= 500 and gloss not in meanings:
                meanings.append(gloss)
    return meanings[:6]


def download(lang, directory):
    name = NAMES[lang]
    path = directory / f"{name}.jsonl"
    if path.is_file():
        return path
    directory.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".jsonl.part")
    url = f"https://kaikki.org/dictionary/{name}/kaikki.org-dictionary-{name}.jsonl"
    print(f"Downloading {name} data (resumable): {url}", flush=True)
    subprocess.run(["curl", "--fail", "--location", "--retry", "3", "--connect-timeout", "30",
                    "--continue-at", "-", "--output", str(temporary), url], check=True)
    temporary.replace(path)
    return path


def entries(path):
    with path.open("rb") as file:
        for number, raw in enumerate(file, 1):
            entry = json.loads(raw)
            if number % 200000 == 0:
                print(f"{path.stem}: {number:,} entries", flush=True)
            yield entry


def add(out, word, meanings, metadata=None, src="es", replace=False):
    if not source_word(word) or not meanings:
        return
    word = key(word, src)
    rec = out.setdefault(word, {})
    if metadata:
        for name in ("p", "i"):
            if metadata.get(name) and not rec.get(name):
                rec[name] = metadata[name]
    glosses = [] if replace else rec.get("g", [])
    for meaning in meanings:
        if meaning not in glosses:
            glosses.append(meaning)
    rec["g"] = glosses[:6]


def atomic_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix="." + path.name)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            json.dump(data, file, ensure_ascii=False, separators=(",", ":"))
        temporary.chmod(0o644)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def build(pairs, directory):
    outputs = {pair: {} for pair in pairs}
    direct = {pair: set() for pair in pairs}
    morphology = {}
    definitions = {}
    ranks = {pair: {} for pair in pairs}
    started = time.time()
    for src in sorted({src for src, dst in pairs}):
        forms = morphology[src] = {}
        definitions[src] = {}
        canonical = set()
        for entry in entries(download(src, directory)):
            word, pos = entry.get("word"), entry.get("pos", "")
            if not source_word(word):
                continue
            normalized = key(word, src)
            own_meanings = english_meanings(entry)
            if own_meanings and normalized not in canonical:
                forms[normalized] = {"p": pos}
                definitions[src][normalized] = own_meanings
                canonical.add(normalized)
            meta = {"p": pos}
            aliases = entry.get("alt_of", []) + [v for sense in entry.get("senses", [])
                                                 for v in sense.get("alt_of", [])]
            lemmas = entry.get("form_of", []) + [v for sense in entry.get("senses", [])
                                                for v in sense.get("form_of", [])] + aliases
            if lemmas and source_word(lemmas[0].get("word")):
                meta["l"] = key(lemmas[0]["word"], src)
                if pos == "verb":
                    meta["i"] = meta["l"]
            existing = forms.setdefault(normalized, {})
            if normalized not in canonical and existing.get("p") == pos:
                existing.update({name: value for name, value in meta.items() if value and not existing.get(name)})
            for pair in pairs:
                if pair[0] != src:
                    continue
                dst = pair[1]
                values = own_meanings if dst == "en" else [
                    value for sense in translation_groups(entry)
                    for value in translations(sense, dst)]
                if values:
                    add(outputs[pair], word, values, forms[normalized], src=src)
                    direct[pair].add(normalized)
            if not meta.get("l") or aliases:
                for form in entry.get("forms", []):
                    value = form.get("form")
                    if not source_word(value) or key(value, src) == normalized:
                        continue
                    form_meta = {"p": pos, "l": normalized}
                    if pos == "verb":
                        form_meta["i"] = normalized
                    forms.setdefault(key(value, src), form_meta)
    print("Aligning translations within English senses…", flush=True)
    languages = {v for pair in pairs for v in pair} - {"en"}
    for entry in entries(download("en", directory)):
        english = entry.get("word")
        if not source_word(english):
            continue
        for sense in translation_groups(entry):
            if not usable(sense) or DISFAVORED & set(sense.get("tags", [])):
                continue
            by_lang = {lang: translations(sense, lang) for lang in languages}
            for pair in pairs:
                src, dst = pair
                values = [english] if dst == "en" else by_lang[dst]
                if not values:
                    continue
                for word in by_lang[src]:
                    normalized = key(word, src)
                    if normalized in direct[pair]:
                        continue
                    meta = morphology[src].get(normalized, {"p": entry.get("pos", "")})
                    if meta.get("p") and meta["p"] != entry.get("pos"):
                        continue
                    # Prefer the source word's primary English definition over
                    # incidental co-translations from unrelated English headwords.
                    own = definitions[src].get(normalized, [])
                    primary = own[0].lower().removeprefix("to ").split(" (")[0].split(",")[0].strip() if own else ""
                    rank = 2 if primary == english.lower() else 1
                    previous = ranks[pair].get(normalized, 0)
                    if rank < previous:
                        continue
                    add(outputs[pair], word, values, meta, src=src, replace=rank > previous)
                    ranks[pair][normalized] = rank
    for (src, dst), out in outputs.items():
        forms = morphology[src]
        for iteration in range(4):
            changed = False
            for word, meta in forms.items():
                lemma = out.get(meta.get("l", ""))
                if word not in out and lemma and lemma.get("g"):
                    out[word] = {"g": list(lemma["g"]), "p": meta.get("p", "")}
                    if meta.get("i"):
                        out[word]["i"] = meta["i"]
                    changed = True
                elif word in out and meta.get("i") and not out[word].get("i"):
                    out[word]["i"] = meta["i"]
            if not changed:
                break
        for pair, correction in CORRECTIONS.items():
            source, target, word = pair.split(":", 2)
            if (source, target) == (src, dst):
                out[word] = {"g": [correction["en"], *correction.get("meanings", [])],
                             "p": correction["pos"], "i": correction["inf"]}
        if not out:
            raise RuntimeError(f"No translations for {src}->{dst}; previous dictionary retained")
        path = path_for(src, dst)
        atomic_json(path, out)
        print(f"Wrote {path.name}: {len(out):,} words, {path.stat().st_size / 1e6:.1f} MB", flush=True)
    atomic_json(ROOT / "lexicon-build-info.json", {
        "format": 2, "created": time.time(), "seconds": time.time() - started,
        "pairs": {f"{src}:{dst}": len(out) for (src, dst), out in outputs.items()},
        "sources": {path.name: {"bytes": path.stat().st_size, "mtime": path.stat().st_mtime}
                    for path in directory.glob("*.jsonl")},
        "method": "direct definitions/translations; fallback translation alignment within one English sense",
    })


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lang", choices=("es", "de"), default="es")
    parser.add_argument("--to", choices=("en", "es", "de", "zh"), default="en")
    parser.add_argument("--all", action="store_true", help="Build all four supported language pairs")
    parser.add_argument("--source-dir", type=Path, default=ROOT / ".cache/lexicon-source")
    args = parser.parse_args()
    pairs = PAIRS if args.all else ((args.lang, args.to),)
    if any(pair not in PAIRS for pair in pairs):
        parser.error("Supported pairs: es:en, es:de, de:es, es:zh (or --all)")
    build(pairs, args.source_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
