"""Durable private URL reuse, single-flight work, and temporary failure cooling."""
import asyncio
import math
import json
import logging
import os
from contextlib import closing, contextmanager
from pathlib import Path
import sqlite3
from collections import OrderedDict
from functools import wraps
import threading
import time


def locked(method):
    @wraps(method)
    def call(self, *args, **kwargs):
        with self.lock:
            return method(self, *args, **kwargs)
    return call


class AudioCache:
    """Private durable addresses, no TTL; only the RAM fallback is LRU bounded.

    A missing path creates an isolated memory cache (for tests). Production uses
    a private SQLite file, never a public static directory or browser storage.
    """
    def __init__(self, clock=time.time, maximum=500, path=None):
        self.clock, self.maximum = clock, maximum
        self.path = Path(path) if path is not None else None
        self.entries = OrderedDict()
        self.lock = threading.RLock()

    @contextmanager
    def connection(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if os.name != 'nt':
            os.chmod(self.path.parent, 0o700)
        with closing(sqlite3.connect(self.path, timeout=2)) as db, db:
            if os.name != 'nt':
                os.chmod(self.path, 0o600)
            db.execute('CREATE TABLE IF NOT EXISTS addresses (cache_key TEXT PRIMARY KEY, url TEXT NOT NULL, updated REAL NOT NULL)')
            yield db

    def remember(self, key, url):
        self.entries[key] = url
        self.entries.move_to_end(key)
        while len(self.entries) > self.maximum:
            self.entries.popitem(last=False)

    def storage_error(self):
        # Never log signed addresses, tokens, or exception text containing SQL.
        logging.getLogger('uvicorn.error').warning('music_address_store_unavailable')

    @locked
    def get(self, key):
        if self.path is not None:
            try:
                with self.connection() as db:
                    row = db.execute('SELECT url FROM addresses WHERE cache_key=?', (json.dumps(key),)).fetchone()
                if row:
                    self.remember(key, row[0])
                    return row[0]
                self.entries.pop(key, None)
                return None
            except (OSError, sqlite3.Error):
                self.storage_error()
        value = self.entries.get(key)
        if value:
            self.entries.move_to_end(key)
        return value

    @locked
    def put(self, key, url):
        self.remember(key, url)
        if self.path is not None:
            try:
                with self.connection() as db:
                    db.execute('INSERT OR REPLACE INTO addresses VALUES(?,?,?)', (json.dumps(key), url, self.clock()))
            except (OSError, sqlite3.Error):
                self.storage_error()
        return url

    @locked
    def discard(self, key, url=None):
        # A late error for an old ticket must not delete a newer successful URL.
        if url is None or self.entries.get(key) == url:
            self.entries.pop(key, None)
        if self.path is not None:
            try:
                with self.connection() as db:
                    db.execute('DELETE FROM addresses WHERE cache_key=?' + (' AND url=?' if url is not None else ''),
                               (json.dumps(key), url) if url is not None else (json.dumps(key),))
            except (OSError, sqlite3.Error):
                self.storage_error()

    @locked
    def clear(self):
        self.entries.clear()
        if self.path is not None:
            with self.connection() as db:
                db.execute('DELETE FROM addresses')


class SingleFlight:
    def __init__(self):
        self.pending = {}

    async def run(self, key, factory):
        identity = (asyncio.get_running_loop(), key)
        task = self.pending.get(identity)
        if task is None:
            task = asyncio.create_task(factory())
            self.pending[identity] = task
            def finished(done):
                if self.pending.get(identity) is done:
                    self.pending.pop(identity, None)
                if not done.cancelled():
                    done.exception()  # Retrieve errors even if every caller disconnected.
            task.add_done_callback(finished)
        return await asyncio.shield(task)


class SourceCooling:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.sources, self.pairs = OrderedDict(), OrderedDict()
        self.lock = threading.RLock()

    @locked
    def blocked(self, key, song):
        return self.retry_after(key, song) > 0

    @locked
    def retry_after(self, key, song):
        until = max(self.sources.get(key, {}).get('until', 0), self.pairs.get((key, song), 0))
        return max(0, math.ceil(until - self.clock()))

    @locked
    def globally_blocked(self, key):
        return self.sources.get(key, {}).get('until', 0) > self.clock()

    @locked
    def failed(self, key, song):
        now = self.clock()
        state = self.sources.setdefault(key, {'until': 0, 'events': []})
        state['events'] = [(at, value) for at, value in state['events'] if at > now - 180][-31:] + [(now, song)]
        if len(state['events']) >= 3 and len({value for _, value in state['events']}) >= 2 and state['until'] <= now:
            state['until'] = now + 180
        self.sources.move_to_end(key)
        self.pairs[(key, song)] = now + 45
        self.pairs.move_to_end((key, song))
        for mapping in (self.sources, self.pairs):
            while len(mapping) > 2000:
                mapping.popitem(last=False)

    @locked
    def succeeded(self, key, song):
        self.sources.pop(key, None)
        self.pairs.pop((key, song), None)

    @locked
    def clear(self):
        self.sources.clear(); self.pairs.clear()


def url_key(source_id, digest, song_key, quality):
    return source_id, digest, song_key, quality


def health_key(source_id, digest, platform, quality):
    return source_id, digest, platform, quality
