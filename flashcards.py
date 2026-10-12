"""Persistent, private study decks and spaced repetition; no LLM calls."""
import contextlib
import hashlib
import json
import math
import os
from pathlib import Path
import random
import re
import sqlite3
import threading
import time
import unicodedata

DB_FILE = Path(os.environ.get('YTWATCHER_FLASHCARDS_DB',
                              str(Path(__file__).with_name('.flashcards.sqlite3'))))
_init_lock = threading.Lock()
_initialized = False
_KEY_RE = re.compile(r'[a-f0-9]{32}')
_LANG_RE = re.compile(r'[a-z]{2,3}(?:-[a-z0-9]{1,8})?')


def check_deck(deck):
    if not isinstance(deck, str) or not _KEY_RE.fullmatch(deck):
        raise PermissionError('Open Flashcards to create or sync your deck.')
    return deck


@contextlib.contextmanager
def _connection():
    global _initialized
    with _init_lock:
        if not _initialized or not DB_FILE.is_file():
            DB_FILE.parent.mkdir(parents=True, exist_ok=True)
            try:
                fd = os.open(DB_FILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                os.close(fd)
            except FileExistsError:
                pass
            with contextlib.closing(sqlite3.connect(DB_FILE, timeout=15)) as db:
                db.execute('PRAGMA journal_mode=WAL')
                db.executescript('''
                    CREATE TABLE IF NOT EXISTS cards (
                        id TEXT PRIMARY KEY, deck TEXT NOT NULL, kind TEXT NOT NULL,
                        source TEXT NOT NULL, translation TEXT NOT NULL,
                        src TEXT NOT NULL, dst TEXT NOT NULL, normalized TEXT NOT NULL,
                        pos TEXT NOT NULL, inf TEXT NOT NULL, meanings TEXT NOT NULL,
                        context TEXT NOT NULL, video_title TEXT NOT NULL, video_href TEXT NOT NULL,
                        created REAL NOT NULL, last_lookup REAL NOT NULL, lookups INTEGER NOT NULL,
                        due REAL NOT NULL, interval REAL NOT NULL DEFAULT 0,
                        ease REAL NOT NULL DEFAULT 2.5, streak INTEGER NOT NULL DEFAULT 0,
                        reviews INTEGER NOT NULL DEFAULT 0, lapses INTEGER NOT NULL DEFAULT 0,
                        last_review REAL,
                        UNIQUE(deck, kind, src, dst, normalized)
                    );
                    CREATE INDEX IF NOT EXISTS cards_deck_due ON cards(deck, due);
                    CREATE TABLE IF NOT EXISTS events (
                        deck TEXT NOT NULL, id TEXT NOT NULL, card TEXT NOT NULL,
                        kind TEXT NOT NULL, data TEXT NOT NULL, created REAL NOT NULL,
                        PRIMARY KEY(deck, id)
                    );
                    CREATE INDEX IF NOT EXISTS events_deck_card ON events(deck, card);
                ''')
            _initialized = True
    db = sqlite3.connect(DB_FILE, timeout=15)
    db.row_factory = sqlite3.Row
    try:
        with db:
            yield db
    finally:
        db.close()


def _text(data, name, maximum, required=False):
    value = data.get(name, '')
    if not isinstance(value, str) or len(value) > maximum or (required and not value.strip()):
        raise ValueError('Invalid ' + name)
    value.encode('utf-8')
    return unicodedata.normalize('NFC', value.strip())


def _event(data):
    if not isinstance(data, dict):
        raise ValueError('Invalid lookup record')
    event_id = _text(data, 'id', 32, required=True)
    if not _KEY_RE.fullmatch(event_id):
        raise ValueError('Invalid record ID')
    kind = data.get('kind')
    if kind not in ('word', 'sentence'):
        raise ValueError('Invalid card type')
    src, dst = _text(data, 'src', 16, True).lower(), _text(data, 'dst', 16, True).lower()
    if not all(_LANG_RE.fullmatch(code) for code in (src, dst)):
        raise ValueError('Invalid language')
    meanings = data.get('meanings', [])
    if not isinstance(meanings, list) or len(meanings) > 10 or any(
            not isinstance(v, str) or len(v) > 500 for v in meanings):
        raise ValueError('Invalid meanings')
    created = data.get('created', time.time())
    if not isinstance(created, (int, float)) or not math.isfinite(created):
        raise ValueError('Invalid lookup time')
    return dict(id=event_id, kind=kind, src=src, dst=dst,
                source=_text(data, 'source', 100 if kind == 'word' else 2000, True),
                translation=_text(data, 'translation', 10000, True),
                pos=_text(data, 'pos', 100), inf=_text(data, 'inf', 100), meanings=meanings,
                context=_text(data, 'context', 2000), video_title=_text(data, 'video_title', 500),
                video_href=_text(data, 'video_href', 2000), created=max(0, min(created, time.time())))


def record(deck, events):
    check_deck(deck)
    if not isinstance(events, list) or not 1 <= len(events) <= 50:
        raise ValueError('Expected 1–50 lookup records')
    events = [_event(event) for event in events]
    saved = 0
    with _connection() as db:
        db.execute('BEGIN IMMEDIATE')
        for event in events:
            if db.execute('SELECT 1 FROM events WHERE deck=? AND id=?', (deck, event['id'])).fetchone():
                continue
            normalized = ' '.join(event['source'].split()).casefold()
            card_id = hashlib.sha256(json.dumps([deck, event['kind'], event['src'], event['dst'], normalized]).encode()).hexdigest()
            now = time.time()
            db.execute('''INSERT INTO cards
                (id,deck,kind,source,translation,src,dst,normalized,pos,inf,meanings,context,
                 video_title,video_href,created,last_lookup,lookups,due)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?)
                ON CONFLICT(deck,kind,src,dst,normalized) DO UPDATE SET
                    translation=excluded.translation,
                    pos=CASE WHEN excluded.pos!='' THEN excluded.pos ELSE cards.pos END,
                    inf=CASE WHEN excluded.inf!='' THEN excluded.inf ELSE cards.inf END,
                    meanings=excluded.meanings, context=excluded.context,
                    video_title=excluded.video_title, video_href=excluded.video_href,
                    last_lookup=MAX(cards.last_lookup,excluded.last_lookup),
                    lookups=cards.lookups+1, due=MIN(cards.due,excluded.due)
                ''', (card_id, deck, event['kind'], event['source'], event['translation'],
                      event['src'], event['dst'], normalized, event['pos'], event['inf'],
                      json.dumps(event['meanings'], ensure_ascii=False), event['context'],
                      event['video_title'], event['video_href'], event['created'], event['created'], now))
            db.execute('INSERT INTO events VALUES (?,?,?,?,?,?)',
                       (deck, event['id'], card_id, 'lookup', json.dumps(event, ensure_ascii=False), event['created']))
            saved += 1
    return {'saved': saved}


def _card(row):
    result = dict(row)
    result.pop('deck', None)
    result.pop('normalized', None)
    result['meanings'] = json.loads(result['meanings'])
    return result


def _stats(db, deck):
    row = db.execute('''SELECT COUNT(*) AS total,
        COALESCE(SUM(kind='word'),0) AS words, COALESCE(SUM(kind='sentence'),0) AS sentences,
        COALESCE(SUM(due<=?),0) AS due, COALESCE(SUM(reviews=0),0) AS new,
        COALESCE(SUM(interval>=86400 AND streak>0),0) AS learned
        FROM cards WHERE deck=?''', (time.time(), deck)).fetchone()
    return dict(row)


def list_cards(deck):
    check_deck(deck)
    with _connection() as db:
        return {'stats': _stats(db, deck),
                'cards': [_card(row) for row in db.execute('SELECT * FROM cards WHERE deck=? ORDER BY last_lookup DESC', (deck,))]}


def next_card(deck, kind='all', target='all', exclude=None):
    check_deck(deck)
    if kind not in ('all', 'word', 'sentence') or (target != 'all' and not _LANG_RE.fullmatch(target)):
        raise ValueError('Invalid quiz filter')
    if exclude is None:
        exclude = []
    if not isinstance(exclude, list) or len(exclude) > 20 or any(not isinstance(v, str) or len(v) != 64 for v in exclude):
        raise ValueError('Invalid recent cards')
    with _connection() as db:
        rows = db.execute('''SELECT * FROM cards WHERE deck=?
            AND (?='all' OR kind=?) AND (?='all' OR dst=?)''', (deck, kind, kind, target, target)).fetchall()
        stats = _stats(db, deck)
    now = time.time()
    due = [row for row in rows if row['due'] <= now]
    pool = due or rows
    fresh = [row for row in pool if row['id'] not in exclude]
    pool = fresh or pool
    if not pool:
        return {'card': None, 'stats': stats, 'practice': False}
    # Randomize within the due set; forgotten and frequently consulted cards
    # receive extra weight. When nothing is due, allow deliberate extra practice.
    weights = [1 + min(8, row['lapses']) * 2 + min(5, row['lookups'] / (row['reviews'] + 1)) for row in pool]
    card = random.choices(pool, weights=weights, k=1)[0]
    return {'card': _card(card), 'stats': stats, 'practice': not bool(due)}


def review(deck, card_id, rating, event_id):
    check_deck(deck)
    if not isinstance(card_id, str) or not re.fullmatch(r'[a-f0-9]{64}', card_id):
        raise ValueError('Invalid card')
    if rating not in ('again', 'hard', 'good', 'easy'):
        raise ValueError('Invalid rating')
    if not isinstance(event_id, str) or not _KEY_RE.fullmatch(event_id):
        raise ValueError('Invalid review record')
    now = time.time()
    with _connection() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT * FROM cards WHERE deck=? AND id=?', (deck, card_id)).fetchone()
        if row is None:
            raise LookupError('Card not found in your deck')
        if db.execute('SELECT 1 FROM events WHERE deck=? AND id=?', (deck, event_id)).fetchone():
            return {'card': _card(row), 'stats': _stats(db, deck)}
        interval, ease, streak, lapses = row['interval'], row['ease'], row['streak'], row['lapses']
        if rating == 'again':
            interval, ease, streak, lapses = 600, max(1.3, ease - .2), 0, lapses + 1
        elif rating == 'hard':
            interval, ease = max(1200, interval * 1.2), max(1.3, ease - .15)
        elif rating == 'good':
            interval = 86400 if streak == 0 else max(86400, interval * ease)
            streak += 1
        else:
            interval, ease, streak = max(345600, interval * ease * 1.3), min(3.5, ease + .15), streak + 1
        interval = min(interval, 365 * 86400)
        db.execute('''UPDATE cards SET due=?,interval=?,ease=?,streak=?,lapses=?,reviews=reviews+1,
            last_review=? WHERE deck=? AND id=?''', (now + interval, interval, ease, streak, lapses, now, deck, card_id))
        db.execute('INSERT INTO events VALUES (?,?,?,?,?,?)',
                   (deck, event_id, card_id, 'review', json.dumps({'rating': rating}), now))
        card = db.execute('SELECT * FROM cards WHERE deck=? AND id=?', (deck, card_id)).fetchone()
        return {'card': _card(card), 'stats': _stats(db, deck)}
