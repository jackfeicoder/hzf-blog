import io
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import time
import unittest
from unittest.mock import AsyncMock, patch
import wave

from music_files import MusicFiles, entry_key
from routers import music
import test_music


def audio_bytes():
    output = io.BytesIO()
    with wave.open(output, 'wb') as audio:
        audio.setnchannels(1); audio.setsampwidth(2); audio.setframerate(8000)
        audio.writeframes(b'\0\0' * 16000)
    return output.getvalue()


class Response:
    status = 200
    def __init__(self, data, length=None, kind='audio/wav'):
        self.body = io.BytesIO(data)
        self.headers = {'Content-Length': str(len(data) if length is None else length), 'Content-Type': kind}
    def getheader(self, key, default=''):
        return self.headers.get(key, default)
    def read1(self, size):
        return self.body.read(size)
    def close(self):
        pass


class FileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.song = dict(source='wy', id='1', name='测试歌曲', singer='歌手', duration=2)
        self.calls = []
        self.now = [1700000000]
        self.data = audio_bytes()
        def opener(url, **kwargs):
            self.calls.append(url)
            return Response(self.data), Response(b''), url
        self.cache = MusicFiles(root=Path(self.temp.name)/'audio', index=Path(self.temp.name)/'files.db',
                                minimum_free=0, clock=lambda: self.now[0], opener=opener)
    def tearDown(self):
        self.cache.close(); self.temp.cleanup()
    def download(self, song=None):
        self.cache.download(song or self.song, '128k', 'https://example.com/audio')
    def test_complete_file_survives_restart_and_duplicate_download_is_skipped(self):
        self.download(); self.download()
        entry = self.cache.get(self.song, '128k')
        self.assertEqual(self.cache.path(entry['id']).read_bytes(), self.data)
        restarted = MusicFiles(root=self.cache.root, index=self.cache.index, minimum_free=0)
        self.assertIsNotNone(restarted.get(self.song, '128k'))
        restarted.close()
        self.assertEqual(len(self.calls), 1)
        self.assertNotIn('https://example.com', json.dumps(self.cache.summary()))
    def test_global_recording_match_rejects_wrong_singer_version_and_unknown_duration(self):
        candidate = {**self.song, 'source':'tx','id':'actual_mid'}
        self.cache.catalogue([self.song, candidate])
        self.download()
        self.assertIsNotNone(self.cache.get(candidate, '128k'))
        self.assertIsNone(self.cache.get({**candidate, 'id':'unverified_id'}, '128k'))
        for update in ({'singer':'其他歌手'}, {'name':'测试歌曲 (Live)'}, {'duration':0}, {'duration':60}):
            self.assertIsNone(self.cache.get({**self.song,'source':'kg','id':'actual_hash', **update}, '128k'))
        self.assertIsNone(self.cache.get(self.song, 'flac'))
    def test_partial_json_and_wrong_duration_never_become_cached_files(self):
        for data, length, kind, song in [(self.data[:100],len(self.data),'audio/wav',self.song),
                (b'{"error":true}',None,'audio/mpeg',self.song),
                (self.data,None,'text/html',self.song),
                (self.data,None,'audio/wav',{**self.song,'duration':200})]:
            with self.subTest(kind=kind, length=length):
                self.cache.opener = lambda url, **kw: (Response(data,length,kind),Response(b''),url)
                with self.assertRaises(Exception): self.download(song)
                self.assertIsNone(self.cache.get(song,'128k'))
                self.assertFalse(list(self.cache.root.glob('*.part')))
                self.assertFalse(list(self.cache.root.glob('*.audio')))
    def test_size_and_free_space_limits_do_not_publish_files(self):
        self.cache.maximum_file = 100
        with self.assertRaises(ValueError): self.download()
        self.cache.maximum_file = 1024**2
        self.cache.minimum_free = 100
        class Disk: free=99
        self.cache.space = lambda _: Disk()
        with self.assertRaises(ValueError): self.download()
        self.assertFalse(list(self.cache.root.glob('*.audio')))
    def test_pinned_files_are_not_evicted_or_deleted_then_lru_evicts(self):
        self.cache.maximum = len(self.data) + 100
        self.download()
        first = self.cache.get(self.song,'128k')
        self.assertFalse(self.cache.remove(first['id']))
        with self.assertRaises(ValueError): self.download({**self.song,'id':'2','name':'另一首'})
        self.assertIsNotNone(self.cache.get(self.song,'128k'))
        self.now[0] += 1000
        self.download({**self.song,'id':'2','name':'另一首'})
        self.assertIsNone(self.cache.get(self.song,'128k'))
        self.assertEqual(self.cache.summary()['count'],1)
        self.assertLessEqual(self.cache.summary()['bytes'],self.cache.maximum)
    def test_same_song_is_queued_once_while_downloading(self):
        started, release = threading.Event(), threading.Event()
        def download(*args): started.set(); release.wait(3)
        with patch.object(self.cache,'download',side_effect=download) as worker:
            self.assertTrue(self.cache.enqueue(self.song,'128k','https://example.com'))
            self.assertTrue(started.wait(1))
            self.assertFalse(self.cache.enqueue(self.song,'128k','https://example.com'))
            release.set(); self.cache.work.join()
            self.assertEqual(worker.call_count,1)
    def test_corrupt_or_missing_file_is_a_cache_miss_and_paths_are_strict(self):
        self.download(); entry = self.cache.get(self.song,'128k')
        self.cache.path(entry['id']).write_bytes(b'broken')
        self.assertIsNone(self.cache.get(self.song,'128k'))
        for identifier in ('../secret', 'x'*64):
            with self.assertRaises(ValueError): self.cache.path(identifier)
    def test_higher_quality_is_not_downloaded_in_background(self):
        self.assertFalse(self.cache.enqueue(self.song,'flac','https://example.com'))
        self.assertEqual(self.calls,[])

    def test_late_invalidations_do_not_remove_new_file_version(self):
        self.download(); entry=self.cache.get(self.song,'128k')
        self.cache.invalidate(entry['id'],'old-checksum')
        self.assertIsNotNone(self.cache.get(self.song,'128k'))
        self.cache.invalidate(entry['id'],entry['checksum'])
        self.assertIsNone(self.cache.get(self.song,'128k'))


class FileRouteTests(unittest.TestCase):
    setUp = test_music.MusicTests.setUp
    tearDown = test_music.MusicTests.tearDown
    headers = test_music.MusicTests.headers

    def prepare(self):
        self.song['duration'] = 2
        data = audio_bytes()
        cache = MusicFiles(root=Path(self.temp.name)/'files',index=Path(self.temp.name)/'index.db',minimum_free=0,
                           opener=lambda url, **kw: (Response(data),Response(b''),url))
        cache.download(self.song,'128k','https://example.com')
        self.addCleanup(cache.close)
        return cache, data

    def test_cached_file_works_without_enabled_source_and_supports_seek_ranges(self):
        cache, data = self.prepare()
        with patch.object(music,'FILE_CACHE',cache), patch.object(music,'run_source',AsyncMock()) as runner:
            first = self.client.post('/api/music/resolve',json={'song':self.song})
            self.assertEqual(first.status_code,200)
            self.assertTrue(first.json()['file_cache_hit'])
            for start, end in ((0,511),(2000,2999)):
                response = self.client.get(first.json()['url'],headers={'Range':f'bytes={start}-{end}'})
                self.assertEqual(response.status_code,206)
                self.assertEqual(response.content,data[start:end+1])
                self.assertEqual(response.headers['content-range'],f'bytes {start}-{end}/{len(data)}')
            self.assertEqual(runner.await_count,0)
            self.assertEqual(self.client.get(first.json()['url'],headers={'Range':'bytes=9999999-'}).status_code,416)

    def test_nginx_internal_response_hides_paths_and_file_feedback_does_not_penalize_source(self):
        cache, _ = self.prepare()
        with patch.object(music,'FILE_CACHE',cache), patch.dict('os.environ',{'MUSIC_CACHE_ACCEL':'1'}):
            resolved = self.client.post('/api/music/resolve',json={'song':self.song}).json()
            response = self.client.get(resolved['url'])
            self.assertTrue(response.headers['x-accel-redirect'].startswith('/_music_cache/'))
            self.assertNotIn(str(cache.root),resolved['url'])
            token = resolved['url'].rsplit('/',1)[1]
            self.client.post('/api/music/feedback',json={'token':token,'event':'stalled'})
            self.assertIsNotNone(cache.get(self.song,'128k'))
            self.assertEqual(music.ROUTING.diagnostics()['recent'],[])

    def test_cache_management_is_admin_only_and_busy_files_are_protected(self):
        cache, _ = self.prepare()
        with patch.object(music,'FILE_CACHE',cache):
            for actor, status in ((None,401),('alice',403),('other-admin',403),('jackfei',200)):
                response = self.client.get('/api/music/file-cache',headers=self.headers(actor) if actor else {})
                self.assertEqual(response.status_code,status)
            identifier = cache.get(self.song,'128k')['id']
            path = '/api/music/file-cache/' + identifier
            self.assertEqual(self.client.delete(path,headers=self.headers('alice')).status_code,403)
            self.assertEqual(self.client.delete(path,headers=self.headers('jackfei')).status_code,409)
            with cache.connection() as db: db.execute('UPDATE files SET pinned=0')
            self.assertEqual(self.client.delete(path,headers=self.headers('jackfei')).status_code,204)
            self.assertIsNone(cache.get(self.song,'128k'))
