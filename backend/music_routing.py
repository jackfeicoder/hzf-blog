"""Persistent success routes and bounded diagnostics; no URLs, scripts or user IDs.

Only server-verified audio promotes a route. A song miss does not blacklist an
entire provider. Manual enable/priority configuration remains in the main DB.
"""
from contextlib import contextmanager, closing
import json
import os
from pathlib import Path
import sqlite3
import threading
import time
import unicodedata
import re


def normalized(value):
    return ''.join(c for c in unicodedata.normalize('NFKC', value or '').casefold() if c.isalnum())


def same_recording(original, candidate):
    if not normalized(original.get('name')) or normalized(original['name']) != normalized(candidate.get('name')):
        return False
    def singers(value):
        return {normalized(part) for part in re.split(r'[/、,&;；]+', value or '') if normalized(part)}
    if not singers(original.get('singer')) or singers(original.get('singer')) != singers(candidate.get('singer')):
        return False
    a, b = original.get('duration') or 0, candidate.get('duration') or 0
    # Cross-platform lyrics/audio must match a known recording, not a clip/cover.
    if a and b and abs(float(a) - float(b)) > max(8, float(a) * .03):
        return False
    if not a and b and float(b) < 60:
        return False
    return True


def route_key(source_id, song, quality):
    return f"{source_id}:{song['source']}:{song['id']}:{quality}"


def choose_quality(capability, requested):
    levels = ['128k', '320k', 'flac', 'flac24bit']
    supported = [q for q in levels if q in capability.get('qualitys', [])]
    if not supported:
        return requested  # Compatibility with older source manifests.
    if requested in supported:
        return requested
    lower = [q for q in supported if levels.index(q) <= levels.index(requested)]
    return lower[-1] if lower else supported[0]


class RoutingStore:
    def __init__(self, path=None, clock=time.time):
        self.path = Path(path) if path else Path(__file__).with_name('.runtime') / 'music-routing.sqlite3'
        self.clock = clock
        self.lock = threading.RLock()

    @contextmanager
    def connection(self):
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if os.name != 'nt':
                os.chmod(self.path.parent, 0o700)
            with closing(sqlite3.connect(self.path, timeout=2)) as db, db:
                db.row_factory = sqlite3.Row
                db.execute('CREATE TABLE IF NOT EXISTS routes (song_key TEXT, quality TEXT, source_id INTEGER, digest TEXT, song TEXT, updated REAL, PRIMARY KEY(song_key,quality))')
                db.execute('CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, at REAL, song_key TEXT, title TEXT, singer TEXT, source_id INTEGER, source_name TEXT, digest TEXT, platform TEXT, quality TEXT, stage TEXT, status TEXT, reason TEXT, elapsed_ms INTEGER)')
                db.execute('CREATE INDEX IF NOT EXISTS event_time ON events(at)')
                if os.name != 'nt':
                    os.chmod(self.path, 0o600)
                yield db

    def preferred(self, song_key, quality):
        with self.connection() as db:
            row = db.execute('SELECT * FROM routes WHERE song_key=? AND quality=?',
                             (song_key, quality)).fetchone()
        return dict(row) if row else None

    def record(self, context, stage, status, reason='', elapsed_ms=0):
        now = self.clock()
        with self.connection() as db:
            db.execute('INSERT INTO events(at,song_key,title,singer,source_id,source_name,digest,platform,quality,stage,status,reason,elapsed_ms) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                       (now, context['song_key'], context.get('title', '')[:200], context.get('singer', '')[:300],
                        context['source_id'], context.get('source_name', '')[:80], context.get('digest', ''),
                        context['song']['source'], context['quality'], stage, status, reason[:80], int(elapsed_ms)))
            if stage == 'stream_ready' and status == 'ok':
                db.execute('INSERT OR REPLACE INTO routes VALUES(?,?,?,?,?,?)',
                           (context['song_key'], context['requested_quality'], context['source_id'], context['digest'], json.dumps(context['song'], ensure_ascii=False), now))
            if status == 'failed' and stage in ('stream_error', 'playback_error'):
                db.execute('DELETE FROM routes WHERE song_key=? AND quality=? AND source_id=?',
                           (context['song_key'], context['requested_quality'], context['source_id']))
            db.execute('DELETE FROM events WHERE id NOT IN (SELECT id FROM events ORDER BY id DESC LIMIT 1000) OR at<?', (now - 7*86400,))

    def ranked(self, rows, song, quality, preferred_id=None, original_key=None):
        now = self.clock()
        key = original_key or song['source'] + ':' + song['id']
        with self.connection() as db:
            events = [dict(r) for r in db.execute('SELECT * FROM events WHERE at>? AND platform=?', (now - 86400, song['source']))]
        def score(row):
            relevant = [e for e in events if e['source_id'] == row.id and e['digest'] == row.digest and e['quality'] == choose_quality(json.loads(row.capabilities).get(song['source'], {}), quality)]
            bad_pair = any(e['song_key'] == key and e['status'] == 'failed' and e['at'] > now - 90 for e in relevant)
            successes = sum(e['stage'] == 'stream_ready' and e['status'] == 'ok' for e in relevant)
            failures = [e for e in relevant if e['status'] == 'failed' and e['stage'] in ('resolve_error', 'stream_error')]
            distinct = {e['song_key'] for e in failures}
            # At least three different song misses before demoting globally.
            health = (successes + 1) / (successes + len(failures) + 2) if successes or len(distinct) >= 3 else .5
            # Verified song memory gets one real retry before speculative sources;
            # failed streams already evict it and live cooling suppresses repeats.
            return (0 if row.id == preferred_id else 1, bad_pair, -health, row.position, row.id)
        return sorted(rows, key=score)

    def diagnostics(self):
        with self.connection() as db:
            recent = [dict(r) for r in db.execute('SELECT at,title,singer,source_id,source_name,platform,quality,stage,status,reason,elapsed_ms FROM events ORDER BY id DESC LIMIT 100')]
            health = [dict(r) for r in db.execute("SELECT source_id,source_name,platform,quality,SUM(stage='stream_ready' AND status='ok') AS verified,SUM(status='failed' AND stage IN ('resolve_error','stream_error')) AS failures FROM events WHERE at>? GROUP BY source_id,platform,quality", (self.clock()-86400,))]
        return {'recent': recent, 'health': health, 'memory_days': 7, 'failure_cooldown_seconds': 90}
