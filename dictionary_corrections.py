"""Reviewed defaults shared by online/offline lookups and study cards.

The English Wiktionary entry lists located/situated first. An older lexicon
build retained only the regional adjective sense "seemly":
https://en.wiktionary.org/wiki/ubicado
"""

CORRECTIONS = {
    f"es:en:{word}": {
        "en": "located", "meanings": ["situated"],
        "pos": "past participle", "inf": "ubicar",
    }
    for word in ("ubicado", "ubicada", "ubicados", "ubicadas")
}

for _target, _primary, _alternatives in (
        ("de", "gelegen", ["befindlich"]), ("zh", "位于", ["坐落于"])):
    for _word in ("ubicado", "ubicada", "ubicados", "ubicadas"):
        CORRECTIONS[f"es:{_target}:{_word}"] = {
            "en": _primary, "meanings": _alternatives,
            "pos": "past participle", "inf": "ubicar",
        }
