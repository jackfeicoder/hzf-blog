import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock, patch

from music_models import MusicSource
from music_routing import RoutingStore, same_recording, choose_quality
from music_playback import url_key
from routers import music
import test_music


class RoutingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.now = 1000000
        self.store = RoutingStore(Path(self.temp.name)/'route.db', lambda: self.now)
        self.song = dict(source='wy', id='123', name='枫', singer='周杰伦', duration=273)
        self.context = dict(song_key='wy:123', title='枫', singer='周杰伦', source_id=2,
                            source_name='Test', digest='digest', song=self.song, quality='128k', requested_quality='128k')

    def tearDown(self):
        self.temp.cleanup()

    def test_only_verified_stream_promotes_persistent_route_without_expiry(self):
        self.store.record(self.context, 'resolved', 'ok')
        self.assertIsNone(self.store.preferred('wy:123', '128k'))
        self.store.record(self.context, 'stream_ready', 'ok')
        other = RoutingStore(self.store.path, lambda: self.now)
        self.assertEqual(other.preferred('wy:123', '128k')['source_id'], 2)
        self.assertIsNone(other.preferred('wy:123', 'flac'))
        self.now += 7*86400 + 1
        self.assertEqual(other.preferred('wy:123', '128k')['source_id'], 2)

    def test_failed_stream_invalidates_preference_but_does_not_change_source_settings(self):
        self.store.record(self.context, 'stream_ready', 'ok')
        self.store.record(self.context, 'stream_error', 'failed', 'truncated_audio')
        self.assertIsNone(self.store.preferred('wy:123', '128k'))
        self.assertEqual(len(self.store.diagnostics()['recent']), 2)

    def test_matching_rejects_covers_versions_clips_and_different_singers(self):
        self.assertTrue(same_recording(self.song, {**self.song, 'source':'kg', 'id':'hash', 'duration':270}))
        for change in ({'name':'枫 (Live)'}, {'singer':'另一位歌手'}, {'duration':30}, {'singer':''}):
            self.assertFalse(same_recording(self.song, {**self.song, **change}))

    def test_quality_falls_down_not_up_to_arbitrary_first_quality(self):
        cap = {'qualitys':['flac','320k','128k']}
        self.assertEqual(choose_quality(cap, 'flac24bit'), 'flac')
        self.assertEqual(choose_quality(cap, '128k'), '128k')
        self.assertEqual(choose_quality({'qualitys':['128k']}, 'flac'), '128k')

    def test_health_is_platform_scoped_and_single_miss_does_not_demote_globally(self):
        rows = [MusicSource(id=i, digest=str(i), position=i, capabilities=json.dumps({'wy':{'qualitys':['128k']}})) for i in (1,2)]
        context = {**self.context, 'source_id':1, 'digest':'1'}
        self.store.record(context, 'resolve_error', 'failed')
        other_song = {**self.song, 'id':'other'}
        self.assertEqual(self.store.ranked(rows, other_song, '128k')[0].id, 1)
        for i in (2,3):
            self.store.record({**context, 'song_key':f'wy:{i}'}, 'resolve_error', 'failed')
        self.assertEqual(self.store.ranked(rows, other_song, '128k')[0].id, 2)
        self.assertEqual(self.store.ranked(rows, {**other_song,'source':'tx'}, '128k')[0].id, 1)

    def test_verified_song_route_gets_one_retry_before_unproven_sources(self):
        rows = [MusicSource(id=i,digest=str(i),position=i,capabilities=json.dumps({'wy':{'qualitys':['128k']}})) for i in (1,2)]
        self.store.record({**self.context,'source_id':2,'digest':'2'},'resolve_error','failed','TimeoutError')
        self.assertEqual(self.store.ranked(rows,self.song,'128k',preferred_id=2)[0].id,2)


class ResolverTests(unittest.TestCase):
    setUp = test_music.MusicTests.setUp
    tearDown = test_music.MusicTests.tearDown
    headers = test_music.MusicTests.headers

    def sources(self, count=2):
        with self.session() as db:
            for i in range(1, count+1):
                db.add(MusicSource(id=i, name=f'source-{i}', script='script', digest=str(i)*64,
                    enabled=True, position=i, capabilities=json.dumps({'wy':{'actions':['musicUrl'], 'qualitys':['128k']}})))
            db.commit()

    def resolve(self, **extra):
        return self.client.post('/api/music/resolve', json={'song':self.song, 'allow_platform_fallback':False, **extra})

    def audio(self, fail=False):
        response = Mock(status=200)
        response.getheader.side_effect = lambda key, default='': {'Content-Type':'audio/mpeg','Content-Length':'515'}.get(key, default)
        response.read1.side_effect = [b'ID3'+b'a'*509, b'bbb', b'']
        if fail:
            return patch.object(music, 'open_http', side_effect=ValueError('URL hidden'))
        return patch.object(music, 'open_http', return_value=(response, Mock(), 'https://example.com/audio'))

    def test_fifth_source_is_reached_and_resolution_alone_not_promoted(self):
        self.sources(5)
        runner = AsyncMock(side_effect=[ValueError()]*4+[{'result':'https://example.com/audio'}])
        with patch.object(music,'run_source',runner), patch.object(music,'check_audio',return_value='https://example.com/audio'):
            response = self.resolve()
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['source_id'],5)
        self.assertIsNone(music.ROUTING.preferred('wy:123','128k'))
        self.assertEqual(len(response.json()['attempted']),5)

    def test_verified_song_memory_and_failed_stream_evicts_url(self):
        self.sources()
        context = dict(song_key='wy:123',title='测试歌曲',singer='测试歌手',source_id=2,source_name='source-2',digest='2'*64,song=self.song,quality='128k',requested_quality='128k')
        token = music.ticket('https://example.com/audio',2,'source-2',context)
        with self.audio():
            self.assertEqual(self.client.get(token['url']).status_code,200)
        runner=AsyncMock(return_value={'result':'https://example.com/audio'})
        with patch.object(music,'run_source',runner),patch.object(music,'check_audio',return_value='https://example.com/audio'):
            response=self.resolve()
        self.assertEqual(response.json()['source_id'],2)
        self.assertIsNotNone(music.AUDIO_CACHE.get(url_key(2,'2'*64,'wy:123','128k')))
        with self.audio(fail=True):
            self.assertEqual(self.client.get(response.json()['url']).status_code,502)
        self.assertIsNone(music.AUDIO_CACHE.get(url_key(2,'2'*64,'wy:123','128k')))
        self.assertIsNone(music.ROUTING.preferred('wy:123','128k'))

    def test_disabled_remembered_source_never_used_and_admin_diagnostics_private(self):
        self.sources()
        context=dict(song_key='wy:123',title='测试歌曲',singer='测试歌手',source_id=2,source_name='source-2',digest='2'*64,song=self.song,quality='128k',requested_quality='128k')
        music.ROUTING.record(context,'stream_ready','ok')
        with self.session() as db:
            db.get(MusicSource,2).enabled=False; db.commit()
        with patch.object(music,'run_source',AsyncMock(return_value={'result':'https://example.com/audio'})),patch.object(music,'check_audio',return_value='https://example.com/audio'):
            self.assertEqual(self.resolve().json()['source_id'],1)
        for who,status in ((None,401),('alice',403),('other-admin',403)):
            self.assertEqual(self.client.get('/api/music/diagnostics',headers=self.headers(who) if who else {}).status_code,status)
        allowed=self.client.get('/api/music/diagnostics',headers=self.headers('jackfei'))
        self.assertEqual(allowed.status_code,200)
        self.assertEqual(allowed.headers['cache-control'],'private, no-store')
        self.assertNotIn('https://',allowed.text)

    def test_feedback_cannot_promote_unverified_audio_and_is_idempotent(self):
        self.sources()
        context=dict(song_key='wy:123',title='测试歌曲',singer='测试歌手',source_id=2,source_name='source-2',digest='2'*64,song=self.song,quality='128k',requested_quality='128k')
        result=music.ticket('https://example.com/audio',2,'source-2',context)
        token=result['url'].rsplit('/',1)[1]
        self.client.post('/api/music/feedback',json={'token':token,'event':'playing'})
        self.assertIsNone(music.ROUTING.preferred('wy:123','128k'))
        with self.audio(): self.client.get(result['url'])
        for _ in range(2): self.client.post('/api/music/feedback',json={'token':token,'event':'playing'})
        self.assertEqual(sum(row['stage']=='playing' for row in music.ROUTING.diagnostics()['recent']),1)

    def test_lyrics_failure_independent_from_audio_and_empty_cache_short_lived(self):
        with patch.object(music,'upstream',AsyncMock(return_value={'lyric':''})):
            result=self.client.get('/api/music/lyrics?source=tx&id=123')
        self.assertEqual(result.json()['lyric'],'')
        self.assertLess(music.CACHE[('lyrics','tx','123')][0]-music.time.monotonic(),16)
        with patch.object(music,'lyrics',AsyncMock(side_effect=[{'lyric':'','translation':''},{'lyric':'[00:01]匹配歌词','translation':''}])),patch.object(music,'recording_matches',AsyncMock(return_value=[{**self.song,'source':'kg','id':'hash'}])):
            response=self.client.post('/api/music/lyrics/resolve',json={'song':self.song})
        self.assertEqual(response.json()['source'],'kg')
        self.assertIn('匹配歌词',response.json()['lyric'])

    def test_cross_platform_remaps_real_id_and_uses_quality_and_preserves_original(self):
        with self.session() as db:
            db.add(MusicSource(id=1,name='matching',script='script',digest='1'*64,enabled=True,position=1,
                              capabilities=json.dumps({'wy':{'actions':['musicUrl'],'qualitys':['128k']},'kg':{'actions':['musicUrl'],'qualitys':['128k']}})))
            db.commit()
        candidate={**self.song,'source':'kg','id':'actual_hash','lyric_id':'actual_hash'}
        runner=AsyncMock(side_effect=[ValueError(),{'result':'https://example.com/audio'}])
        with patch.object(music,'recording_matches',AsyncMock(return_value=[candidate])),patch.object(music,'run_source',runner),patch.object(music,'check_audio',return_value='https://example.com/audio'):
            response=self.client.post('/api/music/resolve',json={'song':self.song,'quality':'flac'})
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['playback_song']['id'],'actual_hash')
        self.assertEqual(response.json()['quality'],'128k')
        self.assertEqual(runner.call_args.args[3],'kg')
        self.assertEqual(runner.call_args.args[4]['musicInfo']['hash'],'actual_hash')
        self.assertEqual(runner.call_args.args[4]['type'],'128k')

    def test_refresh_token_forces_fresh_url_and_truncated_stream_forgets_route(self):
        self.sources()
        context=dict(song_key='wy:123',title='测试歌曲',singer='测试歌手',source_id=2,source_name='source-2',digest='2'*64,song=self.song,quality='128k',requested_quality='128k')
        token=music.ticket('https://example.com/audio',2,'source-2',context)['url'].rsplit('/',1)[1]
        music.AUDIO_CACHE.put(url_key(2,'2'*64,'wy:123','128k'),'https://stale.example/audio')
        runner=AsyncMock(return_value={'result':'https://new.example/audio'})
        with patch.object(music,'run_source',runner),patch.object(music,'check_audio',return_value='https://new.example/audio'):
            response=self.resolve(refresh_token=token)
        self.assertEqual(response.json()['source_id'],2)
        self.assertEqual(runner.await_count,1)
        r=Mock(status=200)
        r.getheader.side_effect=lambda key,default='':{'Content-Type':'audio/mpeg','Content-Length':'10000'}.get(key,default)
        r.read1.side_effect=[b'ID3'+b'a'*509,b'']
        with patch.object(music,'open_http',return_value=(r,Mock(),'https://new.example/audio')):
            self.client.get(response.json()['url'])
        self.assertIsNone(music.AUDIO_CACHE.get(url_key(2,'2'*64,'wy:123','128k')))
        self.assertIsNone(music.ROUTING.preferred('wy:123','128k'))
        self.assertEqual(music.ROUTING.diagnostics()['recent'][0]['reason'],'truncated_audio')
