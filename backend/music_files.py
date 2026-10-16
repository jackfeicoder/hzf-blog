"""Bounded global audio files. Private index; only complete, validated files serve."""
from contextlib import contextmanager, closing
import hashlib
import json
import logging
import math
import os
from pathlib import Path
import queue
import re
import secrets
import shutil
import sqlite3
import threading
import time
import unicodedata

from music_http import open_http

GIB = 1024 ** 3
BASE = Path(__file__).resolve().parent


def text_key(value):
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', value or '').casefold())


def singer_key(value):
    return '|'.join(sorted(text_key(s) for s in re.split(r'[/、,&;；]+', value or '') if text_key(s)))


def entry_key(song, quality):
    return hashlib.sha256(json.dumps([song['source'], song['id'], quality]).encode()).hexdigest()


class MusicFiles:
    def __init__(self, root=None, index=None, *, enabled=True, maximum=5*GIB, minimum_free=8*GIB,
                 maximum_file=25*1024**2, opener=None, space=None, clock=time.time):
        self.root = Path(root or BASE / '.music-cache')
        self.index = Path(index or BASE / '.runtime/music-files.sqlite3')
        self.enabled, self.maximum, self.minimum_free, self.maximum_file = enabled, maximum, minimum_free, maximum_file
        self.opener, self.space, self.clock = opener or open_http, space or shutil.disk_usage, clock
        self.lock = threading.RLock()
        self.work = queue.Queue(maxsize=8)
        self.pending = set()
        self.worker = None
        self.stop = threading.Event()
        self.last_status = '就绪'

    @contextmanager
    def connection(self):
        with self.lock:
            self.index.parent.mkdir(parents=True, exist_ok=True)
            self.root.mkdir(parents=True, exist_ok=True, mode=0o750)
            if os.name != 'nt':
                os.chmod(self.index.parent, 0o700)
            with closing(sqlite3.connect(self.index, timeout=2)) as db, db:
                db.row_factory = sqlite3.Row
                db.execute('CREATE TABLE IF NOT EXISTS files (id TEXT PRIMARY KEY, song_key TEXT, title TEXT, singer TEXT, title_key TEXT, singer_key TEXT, duration REAL, song TEXT, quality TEXT, mime TEXT, size INTEGER, checksum TEXT, created REAL, used REAL, pinned REAL DEFAULT 0, verified INTEGER DEFAULT 0)')
                db.execute('CREATE INDEX IF NOT EXISTS file_recording ON files(title_key,singer_key,quality)')
                db.execute('CREATE TABLE IF NOT EXISTS catalog (song_key TEXT PRIMARY KEY, title_key TEXT, singer_key TEXT, duration REAL, seen REAL)')
                if os.name != 'nt':
                    os.chmod(self.index, 0o600)
                yield db

    def catalogue(self, songs):
        """Only server search adapters call this, never /resolve request metadata."""
        if not self.enabled:
            return
        with self.connection() as db:
            for song in songs:
                values = (song['source']+':'+song['id'], text_key(song.get('name')), singer_key(song.get('singer')), song.get('duration') or 0, self.clock())
                db.execute('INSERT OR REPLACE INTO catalog VALUES(?,?,?,?,?)', values)
                db.execute('UPDATE files SET verified=1 WHERE song_key=? AND title_key=? AND singer_key=? AND ABS(duration-?)<=3', values[:4])
            db.execute('DELETE FROM catalog WHERE rowid NOT IN (SELECT rowid FROM catalog ORDER BY seen DESC LIMIT 10000)')

    def trusted(self, db, song):
        return bool(db.execute('SELECT 1 FROM catalog WHERE song_key=? AND title_key=? AND singer_key=?',
                               (song['source']+':'+song['id'], text_key(song.get('name')), singer_key(song.get('singer')))).fetchone())

    def path(self, identifier):
        if not re.fullmatch(r'[a-f0-9]{64}', identifier):
            raise ValueError('Invalid cache identifier')
        return self.root / (identifier + '.audio')

    def _valid(self, db, row, pin=False):
        if row is None:
            return None
        path = self.path(row['id'])
        if path.is_symlink() or not path.is_file() or path.stat().st_size != row['size']:
            db.execute('DELETE FROM files WHERE id=?', (row['id'],))
            return None
        now = self.clock()
        db.execute('UPDATE files SET used=?, pinned=MAX(pinned,?) WHERE id=?',
                   (now, now + max(600, row['duration'] + 120) if pin else 0, row['id']))
        result = dict(row)
        result['song'] = json.loads(result['song'])
        return result

    def get(self, song, quality):
        if not self.enabled:
            return None
        with self.connection() as db:
            row = db.execute('SELECT * FROM files WHERE id=?', (entry_key(song, quality),)).fetchone()
            if row and row['title_key'] == text_key(song.get('name')) and row['singer_key'] == singer_key(song.get('singer')):
                return self._valid(db, row)
            # Unknown durations never merge across platform IDs. Keep version
            # punctuation in titles; Live/remix/cover must not equal original.
            duration = song.get('duration') or 0
            if duration > 0 and song.get('singer') and self.trusted(db, song):
                rows = db.execute('SELECT * FROM files WHERE verified=1 AND title_key=? AND singer_key=? AND quality=? AND ABS(duration-?)<=3 ORDER BY used DESC LIMIT 10',
                                  (text_key(song.get('name')), singer_key(song['singer']), quality, duration)).fetchall()
                for row in rows:
                    value = self._valid(db, row)
                    if value:
                        return value

    def by_id(self, identifier, pin=False):
        if not self.enabled or not re.fullmatch(r'[a-f0-9]{64}', identifier):
            return None
        with self.connection() as db:
            return self._valid(db, db.execute('SELECT * FROM files WHERE id=?', (identifier,)).fetchone(), pin)

    def remove(self, identifier):
        path = self.path(identifier)
        with self.connection() as db:
            row = db.execute('SELECT pinned FROM files WHERE id=?', (identifier,)).fetchone()
            if row and row['pinned'] > self.clock():
                return False
            path.unlink(missing_ok=True)
            db.execute('DELETE FROM files WHERE id=?', (identifier,))
        return True

    def invalidate(self, identifier, checksum):
        """A playback error may evict its own version, not a newer replacement."""
        with self.connection() as db:
            row = db.execute('SELECT checksum FROM files WHERE id=?', (identifier,)).fetchone()
            if row and row['checksum'] == checksum:
                self.path(identifier).unlink(missing_ok=True)
                db.execute('DELETE FROM files WHERE id=?', (identifier,))

    def enqueue(self, song, quality, url):
        if not self.enabled or self.stop.is_set() or quality not in ('128k', '320k'):
            return False
        key = entry_key(song, quality)
        with self.lock:
            if key in self.pending or self.work.full():
                return False
            self.pending.add(key)
            self.work.put_nowait((dict(song), quality, url, key))
            if self.worker is None:
                self.worker = threading.Thread(target=self._worker, name='music-file-cache', daemon=True)
                self.worker.start()
        return True

    def _worker(self):
        while not self.stop.is_set():
            try:
                song, quality, url, key = self.work.get(timeout=.3)
            except queue.Empty:
                continue
            try:
                self.download(song, quality, url)
            except Exception as error:
                self.last_status = '缓存暂缓，后续播放可重试'
                logging.getLogger('uvicorn.error').info('music_file_cache_failed %s', type(error).__name__)
            finally:
                with self.lock:
                    self.pending.discard(key)
                self.work.task_done()

    def _make_room(self, amount):
        if self.space(self.root).free < self.minimum_free + amount:
            raise ValueError('Disk reserve reached')
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            total = db.execute('SELECT COALESCE(SUM(size),0) FROM files').fetchone()[0]
            candidates = db.execute('SELECT id,size FROM files WHERE pinned<=? ORDER BY used', (self.clock(),)).fetchall()
            if total + amount - sum(r['size'] for r in candidates) > self.maximum:
                raise ValueError('Cache quota reached')
            for row in candidates:
                if total + amount <= self.maximum:
                    break
                self.path(row['id']).unlink(missing_ok=True)
                db.execute('DELETE FROM files WHERE id=?', (row['id'],))
                total -= row['size']
            if total + amount > self.maximum:
                raise ValueError('Cache quota reached')

    def download(self, song, quality, url):
        if self.get(song, quality):
            return
        # One writer for all backend processes; no duplicate downloads or quota
        # races across workers. A busy worker is retried on a later playback.
        self.root.mkdir(parents=True, exist_ok=True, mode=0o750)
        with open(self.root / '.writer.lock', 'a+b') as writer:
            if os.name != 'nt':
                import fcntl
                try:
                    fcntl.flock(writer, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    return
            if self.get(song, quality):
                return
            for orphan in self.root.glob('*.part'):
                if orphan.stat().st_mtime < self.clock() - 300:
                    orphan.unlink(missing_ok=True)
            with self.connection() as db:
                known = {r[0] for r in db.execute('SELECT id FROM files')}
            for orphan in self.root.glob('*.audio'):
                if orphan.stem not in known and orphan.stat().st_mtime < self.clock() - 300:
                    orphan.unlink(missing_ok=True)
            self._make_room(0)
            identifier = entry_key(song, quality)
            part = self.root / (identifier + '.' + secrets.token_hex(8) + '.part')
            r = c = None
            try:
                started = time.monotonic()
                r, c, _ = self.opener(url, timeout=8)
                kind = r.getheader('Content-Type', '').split(';')[0].lower()
                length = int(r.getheader('Content-Length', '0'))
                if r.status != 200 or not (kind.startswith('audio/') or kind in ('application/octet-stream', 'video/mp4')) or not 0 < length <= self.maximum_file:
                    raise ValueError('Incomplete or unsupported audio response')
                self._make_room(length)
                checksum, received = hashlib.sha256(), 0
                with open(part, 'xb') as output:
                    if os.name != 'nt':
                        os.chmod(part, 0o640)
                        os.chown(part, -1, self.root.stat().st_gid)
                    while True:
                        if self.stop.is_set() or time.monotonic() - started > 120:
                            raise TimeoutError('Download budget reached')
                        chunk = r.read1(65536)
                        if not chunk:
                            break
                        received += len(chunk)
                        if received > length or received > self.maximum_file or self.space(self.root).free < self.minimum_free:
                            raise ValueError('Download size or disk reserve exceeded')
                        output.write(chunk)
                        checksum.update(chunk)
                    output.flush()
                    os.fsync(output.fileno())
                if received != length:
                    raise ValueError('Truncated audio')
                import mutagen
                audio = mutagen.File(part)
                duration = float(audio.info.length) if audio is not None else 0
                expected = song.get('duration') or 0
                if not math.isfinite(duration) or not 1 <= duration <= 1800 or (not expected and duration < 60) or (expected and abs(duration - expected) > max(5, expected * .03)):
                    raise ValueError('Invalid audio duration')
                mime = next((m for m in audio.mime if m.startswith('audio/')), '')
                if not mime:
                    raise ValueError('Unsupported media')
                now = self.clock()
                with self.connection() as db:
                    os.replace(part, self.path(identifier))
                    db.execute('INSERT OR REPLACE INTO files VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                               (identifier, song['source']+':'+song['id'], song['name'], song.get('singer', ''), text_key(song['name']),
                                singer_key(song.get('singer')), duration, json.dumps(song, ensure_ascii=False), quality, mime,
                                received, checksum.hexdigest(), now, now, now + 600, int(self.trusted(db, song))))
                self.last_status = '最近缓存成功'
            finally:
                if r is not None:
                    r.close()
                if c is not None:
                    c.close()
                part.unlink(missing_ok=True)

    def summary(self):
        with self.connection() as db:
            total, count = db.execute('SELECT COALESCE(SUM(size),0),COUNT(*) FROM files').fetchone()
            rows = [dict(r) for r in db.execute('SELECT id,title,singer,quality,size,used,pinned FROM files ORDER BY used DESC LIMIT 50')]
        return dict(enabled=self.enabled, bytes=total, count=count, maximum=self.maximum, minimum_free=self.minimum_free,
                    free=self.space(self.root).free, pending=len(self.pending), status=self.last_status, items=rows)

    def close(self):
        self.stop.set()
        if self.worker:
            self.worker.join(timeout=2)
