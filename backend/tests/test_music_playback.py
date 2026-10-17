import asyncio
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from music_playback import AudioCache, SourceCooling, SingleFlight, url_key
from routers import music
import test_music


class CacheTests(unittest.TestCase):
    def test_persistent_cache_survives_restart_time_and_ram_eviction(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'private' / 'addresses.sqlite3'
            now = [0]
            cache = AudioCache(path=path, clock=lambda: now[0], maximum=1)
            key = url_key(1, 'digest', 'wy:1', '128k')
            url = 'https://example.com/audio?expires=1699999999'
            cache.put(key, url)
            cache.put('other', 'https://example.com/other')
            self.assertNotIn(key, cache.entries)
            now[0] += 365 * 86400
            restarted = AudioCache(path=path)
            self.assertEqual(restarted.get(key), url)
            self.assertIsNone(restarted.get(url_key(1, 'changed', 'wy:1', '128k')))
            restarted.discard(key, 'https://example.com/old')
            self.assertEqual(restarted.get(key), url)
            restarted.discard(key, url)
            self.assertIsNone(AudioCache(path=path).get(key))
            restarted.put(key, 'https://example.com/replacement')
            self.assertEqual(cache.get(key), 'https://example.com/replacement')
            restarted.clear()
            self.assertIsNone(cache.get(key))

    def test_late_failure_does_not_delete_replacement(self):
        for persistent in (False, True):
            with tempfile.TemporaryDirectory() as directory:
                cache = AudioCache(path=Path(directory) / 'addresses.sqlite3' if persistent else None)
                cache.put('key', 'https://example.com/old')
                cache.put('key', 'https://example.com/new')
                cache.discard('key', 'https://example.com/old')
                self.assertEqual(cache.get('key'), 'https://example.com/new')

    def test_cache_survives_old_ninety_second_window_and_is_digest_scoped_bounded(self):
        now = [0]
        cache = AudioCache(clock=lambda: now[0], maximum=2)
        key = url_key(1, 'digest', 'wy:1', '128k')
        cache.put(key, 'https://example.com/audio')
        now[0] = 300
        self.assertIsNotNone(cache.get(key))
        self.assertIsNone(cache.get(url_key(1, 'changed', 'wy:1', '128k')))
        cache.put('two', 'https://example.com/2'); cache.put('three', 'https://example.com/3')
        self.assertIsNone(cache.get(key)); self.assertEqual(len(cache.entries), 2)
        now[0] = 2200
        self.assertEqual(cache.get('three'), 'https://example.com/3')

    def test_cooling_requires_several_failures_and_is_platform_digest_scoped(self):
        now = [0]; cooling = SourceCooling(clock=lambda: now[0]); key = (1, 'digest', 'kg', '128k')
        cooling.failed(key, 'kg:1')
        self.assertTrue(cooling.blocked(key, 'kg:1'))
        self.assertFalse(cooling.blocked(key, 'kg:2'))
        cooling.failed(key, 'kg:1'); cooling.failed(key, 'kg:2')
        self.assertTrue(cooling.blocked(key, 'kg:3'))
        self.assertFalse(cooling.blocked((1, 'digest', 'wy', '128k'), 'kg:3'))
        self.assertFalse(cooling.blocked((1, 'changed', 'kg', '128k'), 'kg:3'))
        now[0] = 181
        self.assertFalse(cooling.blocked(key, 'kg:3'))
        cooling.succeeded(key, 'kg:1')
        self.assertFalse(cooling.blocked(key, 'kg:1'))

    @unittest.skipUnless(shutil.which('node'), 'Node unavailable on host; container smoke test covers runtime')
    def test_console_compatibility_does_not_break_script_or_leak_logs(self):
        runtime = Path(__file__).resolve().parents[1] / 'music_runtime.cjs'
        script = """lx.send('inited', {sources:{wy:{actions:['musicUrl'],qualitys:['128k']}}});
lx.on('request', async () => { console.group('private'); console.groupCollapsed('private'); console.table({secret:'hidden'}); console.groupEnd(); return 'https://example.com/audio'; });"""
        result = subprocess.run([shutil.which('node'), str(runtime)], input=json.dumps(dict(script=script,name='test',action='musicUrl',source='wy',info={'type':'128k'})), capture_output=True, text=True, timeout=8)
        data = json.loads(result.stdout)
        self.assertEqual(data['type'], 'done'); self.assertNotIn('hidden', result.stdout)


class FlightTests(unittest.IsolatedAsyncioTestCase):
    async def test_duplicate_work_is_shared_and_cancelled_waiter_does_not_cancel_other(self):
        flights = SingleFlight(); gate = asyncio.Event(); calls = []
        async def resolve():
            calls.append(1); await gate.wait(); return 'audio'
        first = asyncio.create_task(flights.run('song', resolve))
        second = asyncio.create_task(flights.run('song', resolve))
        await asyncio.sleep(0); await asyncio.sleep(0)
        first.cancel()
        with self.assertRaises(asyncio.CancelledError): await first
        gate.set()
        self.assertEqual(await second, 'audio'); self.assertEqual(len(calls), 1)
        await asyncio.sleep(0); self.assertFalse(flights.pending)

    async def test_failed_flight_can_be_retried(self):
        flights = SingleFlight()
        async def fail(): raise ValueError('test')
        with self.assertRaises(ValueError): await flights.run('song', fail)
        self.assertEqual(await flights.run('song', AsyncMock(return_value='fresh')), 'fresh')


class ResolveCacheTests(unittest.TestCase):
    setUp = test_music.MusicTests.setUp
    tearDown = test_music.MusicTests.tearDown

    def source(self):
        from music_models import MusicSource
        with self.session() as db:
            db.add(MusicSource(id=1, name='test', script='test', digest='d'*64, enabled=True, position=0,
                               capabilities=json.dumps({'wy': {'actions': ['musicUrl'], 'qualitys': ['128k']}})))
            db.commit()

    def test_warm_resolve_reuses_address_without_running_script_or_audio_probe(self):
        self.source(); now = [0]; cache = AudioCache(clock=lambda: now[0])
        runner = AsyncMock(return_value={'result':'https://example.com/audio'})
        with patch.object(music, 'AUDIO_CACHE', cache), patch.object(music, 'run_source', runner), patch.object(music, 'check_audio', return_value='https://example.com/audio') as check:
            first = self.client.post('/api/music/resolve', json={'song':self.song})
            now[0] = 365 * 86400
            second = self.client.post('/api/music/resolve', json={'song':self.song})
        self.assertEqual(first.status_code, 200); self.assertEqual(second.status_code, 200)
        self.assertFalse(first.json()['cache_hit']); self.assertTrue(second.json()['cache_hit'])
        self.assertNotEqual(first.json()['url'], second.json()['url']) # Fresh opaque ticket per caller.
        self.assertEqual(runner.await_count, 1); self.assertEqual(check.call_count, 1)

    def test_restart_reuses_address_and_failed_ticket_refreshes_persistent_value(self):
        self.source()
        path = Path(self.temp.name) / 'addresses.sqlite3'
        runner = AsyncMock(side_effect=[{'result': 'https://example.com/old'}, {'result': 'https://example.com/new'}])
        with patch.object(music, 'run_source', runner), patch.object(music, 'check_audio', side_effect=lambda value: value):
            first = self.client.post('/api/music/resolve', json={'song': self.song}).json()
            old_context = music.TICKETS[first['url'].rsplit('/', 1)[1]][2]
            with patch.object(music, 'AUDIO_CACHE', AudioCache(path=path)):
                second = self.client.post('/api/music/resolve', json={'song': self.song}).json()
                self.assertTrue(second['cache_hit'])
                self.assertEqual(runner.await_count, 1)
                token = second['url'].rsplit('/', 1)[1]
                music.failed_stream(music.TICKETS[token][2], 'fixture_expired')
                key = url_key(1, 'd'*64, 'wy:123', '128k')
                self.assertIsNone(AudioCache(path=path).get(key))
                refreshed = self.client.post('/api/music/resolve', json={'song': self.song, 'refresh_token': token})
                self.assertEqual(refreshed.status_code, 200)
                self.assertFalse(refreshed.json()['cache_hit'])
                self.assertEqual(runner.await_count, 2)
                music.failed_stream(old_context, 'fixture_late_error')
                self.assertEqual(AudioCache(path=path).get(key), 'https://example.com/new')
                self.assertNotIn('https://example.com', refreshed.text)

    def test_all_cooled_sources_return_retry_hint_without_more_script_calls(self):
        self.source()
        from music_playback import health_key
        music.SOURCE_COOLING.failed(health_key(1, 'd'*64, 'wy', '128k'), 'wy:123')
        music.SOURCE_COOLING.failed(health_key(1, 'd'*64, 'wy', '128k'), 'wy:other')
        music.SOURCE_COOLING.failed(health_key(1, 'd'*64, 'wy', '128k'), 'wy:other')
        runner = AsyncMock()
        with patch.object(music, 'run_source', runner):
            response = self.client.post('/api/music/resolve', json={'song':self.song, 'allow_platform_fallback':False})
        self.assertEqual(response.status_code, 503); self.assertTrue(response.json()['detail']['cooldown'])
        self.assertEqual(runner.await_count, 0)

    def test_cached_source_is_used_before_manual_first_source_without_spawning_backup(self):
        self.source()
        from music_models import MusicSource
        with self.session() as db:
            db.add(MusicSource(id=2,name='cached',script='test',digest='e'*64,enabled=True,position=2,
                              capabilities=json.dumps({'wy':{'actions':['musicUrl'],'qualitys':['128k']}})))
            db.commit()
        music.AUDIO_CACHE.put(url_key(2,'e'*64,'wy:123','128k'),'https://example.com/audio')
        runner = AsyncMock(); alternatives = AsyncMock()
        with patch.object(music,'run_source',runner), patch.object(music,'recording_matches',alternatives):
            response = self.client.post('/api/music/resolve',json={'song':self.song})
        self.assertEqual(response.status_code,200); self.assertEqual(response.json()['source_id'],2)
        self.assertEqual(runner.await_count,0); self.assertEqual(alternatives.await_count,0)

    def test_song_only_cooling_is_incomplete_and_never_authorizes_skip(self):
        self.source()
        from music_playback import health_key
        music.SOURCE_COOLING.failed(health_key(1,'d'*64,'wy','128k'),'wy:123')
        with patch.object(music,'run_source',AsyncMock()) as runner:
            response=self.client.post('/api/music/resolve',json={'song':self.song,'allow_platform_fallback':False})
        self.assertEqual(response.status_code,503); self.assertTrue(response.json()['detail']['cooldown'])
        self.assertTrue(response.json()['detail']['continue'])
        self.assertFalse(response.json()['detail']['exhausted'])
        self.assertEqual(response.json()['detail']['attempted'], [])
        self.assertEqual(runner.await_count,0)

    def test_alternate_platform_can_win_while_primary_is_still_waiting(self):
        self.source()
        from music_models import MusicSource
        with self.session() as db:
            row = db.get(MusicSource,1)
            row.capabilities = json.dumps({source:{'actions':['musicUrl'],'qualitys':['128k']} for source in ('wy','kg')})
            db.commit()
        async def runner(script,name,action,source,info):
            if source == 'wy': await asyncio.sleep(30)
            return {'result':'https://example.com/audio'}
        with patch.object(music,'run_source',side_effect=runner), patch.object(music,'check_audio',return_value='https://example.com/audio'), patch.object(music,'recording_matches',AsyncMock(return_value=[{**self.song,'source':'kg','id':'real_hash'}])):
            import time
            started=time.monotonic()
            response=self.client.post('/api/music/resolve',json={'song':self.song})
            elapsed=time.monotonic()-started
        self.assertEqual(response.status_code,200); self.assertEqual(response.json()['playback_song']['source'],'kg')
        self.assertLess(elapsed,5)
