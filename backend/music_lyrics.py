"""Durable successful lyrics only; independent from playback and expiring RAM caches."""
from collections import OrderedDict
from contextlib import closing, contextmanager
import json
import logging
import os
from pathlib import Path
import re
import sqlite3
import threading
import time


def has_lyrics(data):
    return isinstance(data, dict) and isinstance(data.get('lyric'), str) and bool(
        re.search(r'\[\d{1,3}:\d{2}(?:[.:]\d{1,3})?\]', data['lyric']))


def resolved_key(song):
    # Keep recordings/versions distinct, including client-supplied metadata.
    return ('resolved', song.source, song.id, song.lyric_id, song.name, song.singer, song.album, song.duration)


class LyricCache:
    def __init__(self, path=None, maximum=128):
        self.path = Path(path) if path is not None else None
        self.maximum = maximum
        self.entries = OrderedDict()
        self.lock = threading.RLock()

    @contextmanager
    def connection(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if os.name != 'nt':
            os.chmod(self.path.parent, 0o700)
        with closing(sqlite3.connect(self.path, timeout=1)) as db, db:
            if os.name != 'nt':
                os.chmod(self.path, 0o600)
            db.execute('CREATE TABLE IF NOT EXISTS lyrics (cache_key TEXT PRIMARY KEY, payload TEXT NOT NULL, saved REAL NOT NULL)')
            yield db

    def remember(self, key, value):
        self.entries[key] = value
        self.entries.move_to_end(key)
        while len(self.entries) > self.maximum:
            self.entries.popitem(last=False)  # Only RAM is bounded; disk has no TTL/LRU eviction.

    def storage_error(self):
        logging.getLogger('uvicorn.error').warning('music_lyric_store_unavailable')

    def get(self, key):
        key = json.dumps(key, ensure_ascii=False)
        with self.lock:
            if key in self.entries:
                self.entries.move_to_end(key)
                return dict(self.entries[key])
            if self.path is not None:
                try:
                    with self.connection() as db:
                        row = db.execute('SELECT payload FROM lyrics WHERE cache_key=?', (key,)).fetchone()
                    if row:
                        value = json.loads(row[0])
                        if has_lyrics(value):
                            self.remember(key, value)
                            return dict(value)
                except (OSError, sqlite3.Error, ValueError, TypeError):
                    self.storage_error()
        return None

    def put(self, key, value):
        if not has_lyrics(value) or len(value['lyric']) > 100000:
            return False
        # Store only plain lyric data, never playback URLs, scripts or user identity.
        clean = {'lyric': value['lyric'], 'translation': str(value.get('translation') or '')[:100000]}
        for field in ('source', 'song_id'):
            if field in value:
                clean[field] = str(value[field])[:160]
        key = json.dumps(key, ensure_ascii=False)
        with self.lock:
            self.remember(key, clean)
            if self.path is not None:
                try:
                    with self.connection() as db:
                        db.execute('INSERT OR REPLACE INTO lyrics VALUES(?,?,?)',
                                   (key, json.dumps(clean, ensure_ascii=False), time.time()))
                except (OSError, sqlite3.Error):
                    self.storage_error()  # Disk trouble must not interrupt otherwise usable playback.
                    return False
        return True
