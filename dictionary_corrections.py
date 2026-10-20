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

# Spanish weather term, not merely the given name "Dana". Reviewed against
# AEMET: https://www.aemet.es/es/web/conocermas/borrascas
# https://aemetblog.es/2023/06/03/que-es-una-dana-y-como-se-formapor-que-es-mas-adecuado-usar-este-termino-que-gota-fria/
for _target, _meaning, _explanation in (
        ('en', 'cut-off low', 'An isolated upper-level low-pressure system.'),
        ('zh', '高空孤立低压', '高空与主气流分离的低压系统。'),
        ('de', 'abgetrenntes Höhentief', 'Ein isoliertes Tiefdruckgebiet in der Höhe.')):
    CORRECTIONS[f'es:{_target}:dana'] = {
        'en': _meaning, 'meanings': [_explanation, 'DANA: depresión aislada en niveles altos.'],
        'pos': 'noun', 'inf': '',
    }

# Spanish colloquial clipping of película. The source marks it alt-of, which
# older builds skipped. A Google auto-language retry then cached Sesotho "two".
# https://en.wiktionary.org/wiki/peli#Spanish
for _word, _english, _alternatives, _german in (
        ('peli', 'movie', ['film'], 'Film'),
        ('pelis', 'movies', ['films'], 'Filme')):
    for _target, _meaning, _other in (
            ('en', _english, _alternatives), ('de', _german, []), ('zh', '电影', [])):
        CORRECTIONS[f'es:{_target}:{_word}'] = {
            'en': _meaning, 'meanings': _other, 'pos': 'noun', 'inf': '',
            'replaces': ['two'],
        }
