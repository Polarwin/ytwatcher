#!/usr/bin/env python3
"""Build compact offline dictionaries from downloaded Kaikki/Wiktionary data.

python build_lexicon.py --all
python build_lexicon.py --lang es --to de

Source JSONL files are retained in .cache/lexicon-source for repeatable rebuilds.
Definitions retain separate source senses, parts of speech, grammatical tags,
and same-POS form/alternative links. Other pairs prefer explicit translations,
then labelled alignment WITHIN ONE English sense for missing translations.
No Google or LLM calls are used. Missing translations remain missing.
"""
import argparse
import json
import gc
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unicodedata

from dictionary_corrections import CORRECTIONS
from lexicon_data import PAIRS, ROOT

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
                not word.strip() or len(word) > 500):
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
    for label, values in groups.items():
        yield {"translations": values, "glosses": [label]}
    for sense in entry.get("senses", []):
        if usable(sense):
            yield sense


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


def pivot_entries(directory):
    """Reuse a lossless projection of the English groups needed by our pairs.

    Original JSONL stays untouched. Metadata pins this derived cache to its
    exact source size/mtime and projection version; it rebuilds on change.
    """
    source = download("en", directory)
    stat = source.stat()
    signature = {"format": 1, "bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns}
    cache = directory / "derived" / "english-pivot-v3.jsonl"
    metadata = cache.with_suffix(".meta.json")
    try:
        current = json.loads(metadata.read_text()) == signature and cache.is_file()
    except (OSError, ValueError):
        current = False
    if not current:
        cache.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(dir=cache.parent, prefix=".english-pivot-")
        temporary = Path(name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as file:
                for entry in entries(source):
                    groups = []
                    for group in translation_groups(entry):
                        selected = [tr for tr in group.get("translations", [])
                                    if tr.get("lang_code") in {"es", "de", "zh", "cmn"}]
                        if not selected:
                            continue
                        compact = {k: group[k] for k in ("glosses", "tags", "id", "form_of", "alt_of") if k in group}
                        compact["translations"] = selected
                        groups.append(compact)
                    if groups:
                        file.write(json.dumps({"word": entry.get("word"), "pos": entry.get("pos", ""),
                            "senses": groups}, ensure_ascii=False, separators=(",", ":")) + "\n")
            temporary.chmod(0o644)
            temporary.replace(cache)
            atomic_json(metadata, signature)
        finally:
            temporary.unlink(missing_ok=True)
        print(f"Cached English pivot groups: {cache.stat().st_size / 1e6:.1f} MB", flush=True)
    yield from entries(cache)


def clean_glosses(values):
    return list(dict.fromkeys(v.strip() for v in values if isinstance(v, str) and v.strip()))


def add_sense(records, word, sense, src, explicit=False):
    word = key(word, src)
    if not source_word(word):
        return
    record = records.setdefault(word, {"s": []})
    pos = sense.get("p", "")
    explicit_parts = record.setdefault("_explicit", set())
    if explicit:
        if pos not in explicit_parts:
            record["s"][:] = [s for s in record["s"] if not (s.get("o") == "table" and s.get("p") == pos)]
        explicit_parts.add(pos)
    elif sense.get("o") == "table" and pos in explicit_parts:
        return
    signature = (pos, sense.get("l"), sense.get("o"), tuple(sense.get("t", [])),
                 tuple(sense.get("g", [])), sense.get("f"), sense.get("id"), sense.get("q"), sense.get("d"))
    seen = record.setdefault("_seen", set())
    if signature not in seen:
        seen.add(signature)
        record["s"].append(sense)


def source_senses(records, entry, src, dst, position):
    word, pos = entry["word"], entry.get("pos", "")
    senses = entry.get("senses", [])
    record = records.setdefault(key(word, src), {"s": []})
    explicit_parts = record.setdefault("_explicit", set())
    if pos not in explicit_parts:
        record["s"][:] = [s for s in record["s"] if not (s.get("p") == pos and s.get("o") == "table")]
    explicit_parts.add(pos)
    for index, source in enumerate(senses):
        tags = source.get("tags", [])
        refs = source.get("form_of", []) or source.get("alt_of", []) or entry.get("form_of", []) or entry.get("alt_of", [])
        glosses = clean_glosses(source.get("glosses", []))
        if refs:
            for ref in refs:
                lemma = ref.get("word")
                if not source_word(lemma) or key(lemma, src) == key(word, src):
                    # Multiword expansions (e.g. initialisms) are definitions,
                    # even though this word dictionary cannot follow their keys.
                    if dst == "en" and glosses:
                        node = {"p": pos, "g": glosses, "o": "direct", "r": [position, index]}
                        if tags:
                            node["t"] = tags
                        if source.get("id"):
                            node["id"] = source["id"]
                        add_sense(records, word, node, src, explicit=True)
                    continue
                node = {"p": pos, "l": key(lemma, src), "o": "form", "r": [position, index]}
                if glosses:
                    node["f"] = "; ".join(glosses)
                if tags:
                    node["t"] = tags
                extra = ref.get("extra")
                if dst == "en" and extra and any('“' + extra + '”' in g or '"' + extra + '"' in g for g in glosses):
                    node["g"] = [extra]
                if dst == "en":
                    for gloss in glosses:
                        for prefix in ("clipping of ", "abbreviation of ", "short for "):
                            opening = prefix + lemma + ", "
                            if gloss.startswith(opening):
                                node["g"] = [gloss[len(opening):]]
                if source.get("id"):
                    node["id"] = source["id"]
                add_sense(records, word, node, src, explicit=True)
            continue
        values = glosses if dst == "en" else translations(source, dst)
        if values and "no-gloss" not in tags:
            node = {"p": pos, "g": clean_glosses(values), "o": "direct", "r": [position, index]}
            if tags:
                node["t"] = tags
            if source.get("id"):
                node["id"] = source["id"]
            add_sense(records, word, node, src, explicit=True)
    # Some source entries keep sense-labelled translations outside senses.
    if dst != "en":
        groups = {}
        for tr in entry.get("translations", []):
            label = tr.get("sense", "").strip()
            if label:
                groups.setdefault(label, []).append(tr)
        for index, (label, values) in enumerate(groups.items()):
            translated = translations({"translations": values}, dst)
            if translated:
                add_sense(records, word, {"p": pos, "g": translated, "o": "direct",
                    "d": label, "r": [position, index]}, src, explicit=True)
    # Keep an explicit POS even when this target has no direct translation.
    record = records.setdefault(key(word, src), {"s": []})
    order = record.setdefault("_pos", {})
    order.setdefault(pos, position)
    if not any(s.get("p") == pos for s in record["s"]):
        record["s"].append({"p": pos, "o": "missing", "r": [position, 0]})
    if not any(s.get("form_of") for s in senses):
        for form in entry.get("forms", []):
            spelling = form.get("form")
            if not source_word(spelling) or key(spelling, src) == key(word, src):
                continue
            tags = form.get("tags", [])
            add_sense(records, spelling, {"p": pos, "l": key(word, src), "o": "table",
                "t": tags, "r": [position, 0]}, src)


def build_pair(src, dst, directory):
    records = {}
    definition_words = {}
    for position, entry in enumerate(entries(download(src, directory))):
        if source_word(entry.get("word")):
            source_senses(records, entry, src, dst, position)
            if dst != "en":
                for sense in entry.get("senses", []):
                    if not usable(sense):
                        continue
                    for gloss in clean_glosses(sense.get("glosses", [])):
                        # Only exact headwords, not guessed synonyms or words
                        # extracted from explanatory prose, establish a bridge.
                        gloss = gloss.removeprefix("to ")
                        definition_words.setdefault((gloss, entry.get("pos", "")), set()).add(key(entry["word"], src))
    print(f"{src}:{dst}: retained {len(records):,} spellings and their source senses", flush=True)
    # Same-sense alignment fills target-language gaps, never overwrites a
    # definition, changes POS, or invents a source word absent from the dump.
    direct = {(word, s.get("p", "")) for word, record in records.items()
              for s in record["s"] if s.get("o") == "direct" and s.get("g")}
    print(f"{src}:{dst}: aligning missing translations within English senses…", flush=True)
    for position, entry in enumerate(pivot_entries(directory)):
        english = entry.get("word")
        if not isinstance(english, str) or not 0 < len(english) <= 200:
            continue
        pos = entry.get("pos", "")
        primary_bridge_used = False
        for index, group in enumerate(translation_groups(entry)):
            if not usable(group):
                continue
            values = [english] if dst == "en" else translations(group, dst)
            if not values:
                continue
            spellings = [(spelling, False) for spelling in translations(group, src)]
            # Unqualified source glosses identify the English lemma's primary
            # translatable sense. Other senses require an explicit source-word
            # translation in that precise sense; never merge the whole entry.
            if not primary_bridge_used and dst != "en":
                spellings += [(word, True) for word in sorted(definition_words.get((english, pos), ()))]
                primary_bridge_used = True
            for spelling, via_definition in spellings:
                normalized = key(spelling, src)
                record = records.get(normalized)
                if not record or (normalized, pos) in direct:
                    continue
                if not any(s.get("p") == pos for s in record["s"]):
                    continue
                # Explicit source forms must resolve their own lemma before
                # looking at a pivot headword that may be an unrelated sense.
                if any(s.get("p") == pos and s.get("l") for s in record["s"]):
                    continue
                node = {"p": pos, "g": clean_glosses(values), "o": "aligned", "q": english,
                        "r": [record.get("_pos", {}).get(pos, position), index]}
                if via_definition:
                    node["a"] = "exact source English definition"
                if group.get("glosses"):
                    node["d"] = "; ".join(group["glosses"])
                if group.get("tags"):
                    node["t"] = group["tags"]
                if group.get("id"):
                    node["id"] = group["id"]
                add_sense(records, spelling, node, src)
    del direct, definition_words
    # Retain reviewed defaults as labelled extra senses, without deleting source
    # alternatives (e.g. the regional adjective meaning of ubicado).
    for pair, correction in CORRECTIONS.items():
        source, target, word = pair.split(":", 2)
        if (source, target) != (src, dst):
            continue
        node = {"p": correction["pos"], "g": [correction["en"], *correction.get("meanings", [])],
                "o": "reviewed", "r": [-1, 0]}
        if correction.get("inf"):
            node["i"] = correction["inf"]
        add_sense(records, word, node, src)
    # Resolve reachability by (spelling, POS), not by spelling alone. References
    # stay compact in the file and are resolved on lookup with cycle protection.
    reachable = {(word, s.get("p", "")) for word, record in records.items()
                 for s in record["s"] if s.get("g")}
    for iteration in range(12):
        fresh = {(word, s.get("p", "")) for word, record in records.items()
                 for s in record["s"] if s.get("l") and
                 (s["l"], s.get("p", "")) in reachable} - reachable
        if not fresh:
            break
        reachable.update(fresh)
    output = {}
    for word, record in records.items():
        senses = [s for s in record["s"] if s.get("g") or
                  s.get("l") and (s["l"], s.get("p", "")) in reachable]
        senses.sort(key=lambda s: (s.get("o") != "reviewed",
                    record.get("_pos", {}).get(s.get("p", ""), s["r"][0]),
                    bool(DISFAVORED & set(s.get("t", []))), s["r"]))
        for sense in senses:
            sense.pop("r", None)
        if senses:
            output[word] = {"s": senses}
    return output


def build(pairs, directory, output_dir=ROOT):
    started = time.time()
    counts = {}
    # One pair at a time bounds memory while retaining separate POS/senses.
    for src, dst in pairs:
        out = build_pair(src, dst, directory)
        if not out:
            raise RuntimeError(f"No translations for {src}->{dst}; previous dictionary retained")
        path = output_dir / f"lexicon-{src}-{dst}.json"
        atomic_json(path, out)
        counts[f"{src}:{dst}"] = len(out)
        print(f"Wrote {path.name}: {len(out):,} words, {path.stat().st_size / 1e6:.1f} MB", flush=True)
        del out
        gc.collect()
    atomic_json(output_dir / "lexicon-build-info.json", {
        "format": 3, "created": time.time(), "seconds": time.time() - started,
        "pairs": counts,
        "sources": {path.name: {"bytes": path.stat().st_size, "mtime": path.stat().st_mtime}
                    for path in directory.glob("*.jsonl")},
        "method": "separate source POS and senses; same-POS lemma references; labelled same-sense pivot translations",
    })


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lang", choices=("es", "de"), default="es")
    parser.add_argument("--to", choices=("en", "es", "de", "zh"), default="en")
    parser.add_argument("--all", action="store_true", help="Build all four supported language pairs")
    parser.add_argument("--source-dir", type=Path, default=ROOT / ".cache/lexicon-source")
    parser.add_argument("--output-dir", type=Path, default=ROOT, help="Stage rebuilt files here before deployment")
    args = parser.parse_args()
    pairs = PAIRS if args.all else ((args.lang, args.to),)
    if any(pair not in PAIRS for pair in pairs):
        parser.error("Supported pairs: es:en, es:de, de:es, es:zh (or --all)")
    build(pairs, args.source_dir, args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
