#!/usr/bin/env python3
"""Build a compact offline lexicon from Kaikki (parsed Wiktionary).

One-time step (per language): downloads the word list from kaikki.org
(~1 GB JSONL, streamed) and produces lexicon-<lang>.json next to this
script, e.g.:

  {"comer":    {"g": ["eat"], "p": "verb"},
   "comieron": {"g": ["eat"], "p": "verb", "i": "comer"}, ...}

Keys are lowercased word forms. "g" is a list of English meanings
(usually senses from different source words: "banco" -> bank/bench/...),
"p" a part of speech, "i" the dictionary infinitive — present on
conjugated verb forms, including irregulars ("sintieron" -> "sentir"),
thanks to Wiktionary's conjugation tables. main.py's dictionary_lookup
consumes this as its first (offline) backend.

Usage: python build_lexicon.py [--lang es|de]
"""

import argparse
import json
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from dictionary_corrections import CORRECTIONS

KAIKKI_URL = {
    "es": "https://kaikki.org/dictionary/Spanish/kaikki.org-dictionary-Spanish.jsonl",
    "de": "https://kaikki.org/dictionary/German/kaikki.org-dictionary-German.jsonl",
}
ENGLISH_URL = ("https://kaikki.org/dictionary/English/"
               "kaikki.org-dictionary-English.jsonl")
OUT_FILE = {
    "es": "lexicon-es.json",
    "de": "lexicon-de.json",
}


def english_meanings(entry):
    """Read English definitions already present in English-Wiktionary entries."""
    meanings = []
    for sense in entry.get("senses", []):
        if (sense.get("form_of") or sense.get("alt_of")
                or "form-of" in sense.get("tags", []) or "no-gloss" in sense.get("tags", [])):
            continue
        for gloss in sense.get("glosses", []):
            if isinstance(gloss, str) and gloss and gloss not in meanings:
                meanings.append(gloss)
        for tr in sense.get("translations", []):
            if tr.get("lang_code") == "en" and tr.get("word") and tr["word"] not in meanings:
                meanings.append(tr["word"])
    return meanings[:6]


def build(lang, url, out_path):
    out = {}
    direct_glosses = set()
    n_lines = 0
    t0 = time.time()
    req = urllib.request.Request(url, headers={"User-Agent": "ytwatcher-lexicon/1.0"})
    with urllib.request.urlopen(req, timeout=300) as resp:
        for raw in resp:
            n_lines += 1
            if n_lines % 100000 == 0:
                print(f"{n_lines} lines, {len(out)} entries, "
                      f"{time.time() - t0:.0f}s", flush=True)
            try:
                entry = json.loads(raw)
            except json.JSONDecodeError:
                continue
            word = entry.get("word")
            pos = entry.get("pos", "") or ""
            if not word or " " in word:
                continue
            key = word.lower()
            glosses = english_meanings(entry)
            is_verb = "verb" in pos.lower()
            is_pure_form = "verb form" in pos.lower()
            form_of = entry.get("form_of") or []
            i = None
            if is_verb and form_of:
                i = form_of[0].get("word")
            record = {}
            if glosses:
                record["g"] = glosses
                direct_glosses.add(key)
            if pos and not is_pure_form:
                record["p"] = pos
            if i:
                record["i"] = i
            if record:
                # First wins, but prefer records that carry a gloss.
                if key not in out or (glosses and not out[key].get("g")):
                    out[key] = record
            # Reverse map: every conjugated form -> its infinitive.
            # Existing entries (real lemmas) always win; the second
            # pass below fills in the lemma's English gloss.
            if is_verb and entry.get("forms") and not is_pure_form:
                for form in entry["forms"]:
                    f = (form.get("form") or "").lower()
                    if not f or " " in f or f in out:
                        continue
                    out[f] = {"p": "verb", "i": word}
    # Reverse tables supplement entries without direct definitions. Their
    # ordering does not identify the most common sense of a foreign word.
    print("pass 2: English Wiktionary (translations)...", flush=True)
    req = urllib.request.Request(ENGLISH_URL, headers={"User-Agent": "ytwatcher-lexicon/1.0"})
    with urllib.request.urlopen(req, timeout=300) as resp:
        for raw in resp:
            n_lines += 1
            if n_lines % 200000 == 0:
                print(f"en: {n_lines} lines, {len(out)} entries, "
                      f"{time.time() - t0:.0f}s", flush=True)
            try:
                entry = json.loads(raw)
            except json.JSONDecodeError:
                continue
            word = entry.get("word")
            if not word or " " in word:
                continue
            for sense in entry.get("senses", []):
                for tr in sense.get("translations", []):
                    if tr.get("lang_code") != lang:
                        continue
                    es = tr.get("word") or ""
                    if not es or " " in es:
                        continue
                    key = es.lower()
                    if key in direct_glosses:
                        continue
                    rec = out.get(key)
                    if rec is None:
                        out[key] = {"g": [word]}
                    elif "g" not in rec:
                        rec["g"] = [word]
                    elif word not in rec["g"] and len(rec["g"]) < 6:
                        rec["g"].append(word)
    # Third pass: forms without their own glosses inherit the lemma's
    # meaning list ("comieron" shows "eat", not nothing).
    for key, rec in out.items():
        if not rec.get("g") and rec.get("i"):
            lemma = out.get(rec["i"])
            if lemma and lemma.get("g"):
                rec["g"] = list(lemma["g"])
    for pair, correction in CORRECTIONS.items():
        source, target, word = pair.split(":", 2)
        if source == lang and target == "en":
            out[word] = {"g": [correction["en"], *correction.get("meanings", [])],
                         "p": correction["pos"], "i": correction["inf"]}
    print(f"done: {n_lines} lines -> {len(out)} entries in "
          f"{time.time() - t0:.0f}s", flush=True)
    tmp = Path(tempfile.mkstemp(dir=out_path.parent)[1])
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    tmp.replace(out_path)
    size_mb = out_path.stat().st_size / 1e6
    print(f"wrote {out_path} ({size_mb:.1f} MB)", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lang", choices=sorted(KAIKKI_URL), default="es")
    args = parser.parse_args()
    out_path = Path(__file__).parent / OUT_FILE[args.lang]
    build(args.lang, KAIKKI_URL[args.lang], out_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
