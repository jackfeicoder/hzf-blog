import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from music_lyrics import LyricCache, resolved_key
from routers import music
import test_music

LYRIC = {'lyric': '[00:01.00]第一句\n[00:05.20]第二句', 'translation': '[00:01.00]Translation'}


class LyricCacheTests(unittest.TestCase):
    def test_restart_time_and_memory_eviction_preserve_disk_lyrics_and_translation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'private' / 'lyrics.sqlite3'
            cache = LyricCache(path, maximum=1)
            cache.put(('lyrics', 'wy', '1'), LYRIC)
            cache.put(('lyrics', 'wy', '2'), {**LYRIC, 'lyric': '[00:01]另一首'})
            self.assertEqual(len(cache.entries), 1)
            with patch('music_lyrics.time.time', return_value=9999999999):
                restarted = LyricCache(path)
                self.assertEqual(restarted.get(('lyrics', 'wy', '1')), LYRIC)
            if os.name != 'nt':
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertLess(path.stat().st_size, 50000)

    def test_empty_invalid_or_oversized_result_never_replaces_good_lyrics(self):
        cache = LyricCache()
        cache.put('song', LYRIC)
        for value in ({}, {'lyric': ''}, {'lyric': '暂时没有歌词'}, {'lyric': 42},
                      {'lyric': '[00:01]' + 'a' * 100000}):
            self.assertFalse(cache.put('song', value))
            self.assertEqual(cache.get('song'), LYRIC)

    def test_platform_and_recording_keys_are_isolated_and_returned_values_are_copies(self):
        cache = LyricCache()
        cache.put(('lyrics', 'wy', '1'), LYRIC)
        self.assertIsNone(cache.get(('lyrics', 'tx', '1')))
        result = cache.get(('lyrics', 'wy', '1')); result['lyric'] = ''
        self.assertEqual(cache.get(('lyrics', 'wy', '1')), LYRIC)
        song = music.Song(source='wy', id='1', name='枫', singer='周杰伦')
        self.assertNotEqual(resolved_key(song), resolved_key(song.model_copy(update={'name': '枫 (Live)'})))

    def test_disk_failure_falls_back_to_memory_and_malformed_rows_are_misses(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'lyrics.sqlite3'
            cache = LyricCache(path)
            with patch.object(cache, 'connection', side_effect=OSError('disk unavailable')):
                self.assertFalse(cache.put('song', LYRIC))
                self.assertEqual(cache.get('song'), LYRIC)
                self.assertIsNone(cache.get('other'))
            cache.put('bad', LYRIC)
            with cache.connection() as db:
                db.execute('UPDATE lyrics SET payload=?', ('not json',))
            self.assertIsNone(LyricCache(path).get('bad'))


class LyricEndpointTests(unittest.TestCase):
    setUp = test_music.MusicTests.setUp
    tearDown = test_music.MusicTests.tearDown

    def restart(self):
        music.CACHE.clear()
        music.LYRIC_CACHE = LyricCache(music.LYRIC_CACHE.path)

    def test_direct_endpoint_reuses_disk_after_restart_without_upstream(self):
        upstream = AsyncMock(return_value={'lyric': LYRIC['lyric'], 'tlyric': LYRIC['translation']})
        with patch.object(music, 'upstream', upstream):
            self.assertEqual(self.client.get('/api/music/lyrics?source=tx&id=123').json(), LYRIC)
        self.restart()
        with patch.object(music, 'upstream', AsyncMock(side_effect=AssertionError('network should not run'))):
            self.assertEqual(self.client.get('/api/music/lyrics?source=tx&id=123').json(), LYRIC)
        self.assertEqual(upstream.await_count, 1)

    def test_verified_cross_platform_result_is_durable_without_repeating_search(self):
        alternative = {**self.song, 'source': 'kg', 'id': 'hash'}
        with patch.object(music, 'lyrics', AsyncMock(side_effect=[{'lyric': ''}, LYRIC])), \
             patch.object(music, 'recording_matches', AsyncMock(return_value=[alternative])):
            first = self.client.post('/api/music/lyrics/resolve', json={'song': self.song})
        self.assertEqual(first.json()['source'], 'kg')
        self.restart()
        with patch.object(music, 'lyrics', AsyncMock(side_effect=AssertionError('unexpected lyric fetch'))), \
             patch.object(music, 'recording_matches', AsyncMock(side_effect=AssertionError('unexpected search'))):
            second = self.client.post('/api/music/lyrics/resolve', json={'song': self.song})
        self.assertEqual(first.json(), second.json())
        self.assertEqual(second.headers['cache-control'], 'private, no-store')

    def test_client_playback_candidate_cannot_persist_a_global_recording_alias(self):
        candidate = {**self.song, 'source': 'kg', 'id': 'untrusted_hash'}
        with patch.object(music, 'lyrics', AsyncMock(return_value=LYRIC)):
            response = self.client.post('/api/music/lyrics/resolve', json={'song': self.song, 'playback_song': candidate})
        self.assertEqual(response.json()['source'], 'kg')
        self.assertIsNone(music.LYRIC_CACHE.get(resolved_key(music.Song(**self.song))))

    def test_failed_or_empty_fetch_is_not_durable_and_can_succeed_later(self):
        with patch.object(music, 'upstream', AsyncMock(side_effect=ValueError('unavailable'))):
            self.assertEqual(self.client.get('/api/music/lyrics?source=tx&id=123').json()['lyric'], '')
        with patch.object(music, 'upstream', AsyncMock(return_value={'lyric': ''})):
            self.client.get('/api/music/lyrics?source=tx&id=123')
        self.assertIsNone(music.LYRIC_CACHE.get(('lyrics', 'tx', '123')))
        self.restart()
        with patch.object(music, 'upstream', AsyncMock(return_value={'lyric': LYRIC['lyric']})):
            self.assertEqual(self.client.get('/api/music/lyrics?source=tx&id=123').json()['lyric'], LYRIC['lyric'])
