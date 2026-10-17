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
