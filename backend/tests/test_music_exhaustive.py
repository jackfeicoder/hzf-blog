import asyncio
import json
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs, urlsplit

from music_candidates import candidates, branch_script
from music_models import MusicSource
from music_search import platform_search
from music_worker import SourceRetryable
from routers import music
import test_music


class PlanTests(unittest.TestCase):
    def test_every_supported_quality_and_aggregate_branch_is_unique(self):
        script = 'const SOURCE_HANDLERS = {xinghai:{},suyinSearch:{},suyinQQ:{}}; function getUrlWithFallback(){} function getPlatformSongId(){}'
        rows = [SimpleNamespace(id=1,script=script,capabilities=json.dumps({'kw':{'qualitys':['128k','320k','flac']}})),
                SimpleNamespace(id=2,script='ordinary',capabilities=json.dumps({'kw':{'qualitys':['128k']}}))]
        result = [(r.id,q,b) for r,q,b in candidates(rows,'kw','128k')]
        self.assertEqual(result[:2], [(1,'128k',''),(2,'128k','')])
        self.assertEqual(len(result), 10); self.assertEqual(len(set(result)),10)
        self.assertNotIn((1,'128k','suyinQQ'),result)
        self.assertIn((1,'flac','suyinSearch'),result)
        adapted = branch_script(script,'suyinSearch')
        self.assertTrue(adapted.startswith(script)); self.assertIn('SOURCE_HANDLERS["suyinSearch"].fn',adapted)

    def test_kw_search_requests_original_catalogue_without_hardcoded_song_or_user_id(self):
        upstream = AsyncMock(return_value={'abslist':[dict(MUSICRID='MUSIC_118987',SONGNAME='枫',ARTIST='周杰伦',DURATION='275')]})
        result = asyncio.run(platform_search(upstream,'kw','枫 周杰伦',1))
        query = parse_qs(urlsplit(upstream.call_args.args[0]).query)
        self.assertEqual(query['show_copyright_off'],['1']); self.assertNotIn('uid',query)
        self.assertEqual(result[0]['id'],'118987')


class ExhaustiveTests(unittest.TestCase):
    setUp = test_music.MusicTests.setUp
    tearDown = test_music.MusicTests.tearDown

    def sources(self, qualities=('128k',), script='script'):
        with self.session() as db:
            for i in (1,2):
                db.add(MusicSource(id=i,name=str(i),script=script,digest=str(i)*64,enabled=True,position=i,
                    capabilities=json.dumps({p:{'actions':['musicUrl'],'qualitys':list(qualities)} for p in ('wy','tx','kw','kg','mg')})))
            db.commit()

    def test_fifth_platform_and_second_source_are_reached_before_exhaustion(self):
        self.sources()
        matches = [{**self.song,'source':p,'id':p+'-real'} for p in ('kg','tx','kw','mg')]
        seen = []
        async def run(script,name,action,platform,info):
            seen.append((platform,name))
            if platform=='mg' and name=='2': return {'result':'https://example.com/audio'}
            raise ValueError('no URL')
        with patch.object(music,'run_source',side_effect=run), patch.object(music,'recording_matches',AsyncMock(return_value=matches)), \
             patch.object(music,'check_audio',return_value='https://example.com/audio'):
            response = self.client.post('/api/music/resolve',json={'song':self.song})
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['playback_song']['source'],'mg')
        self.assertIn(('kw','1'),seen); self.assertIn(('mg','2'),seen)

    def test_recording_discovery_checks_all_four_backup_platforms(self):
        async def search(request,response,q,source,page):
            return {'items':[{**self.song,'source':source,'id':source+'-real'}]}
        with patch.object(music,'search',side_effect=search) as called:
            result = asyncio.run(music.recording_matches(music.Song(**self.song),None,['kg','tx','kw','mg']))
        self.assertEqual({r['source'] for r in result},{'kg','tx','kw','mg'})
        self.assertEqual(called.call_count,4); self.assertEqual(result.pending,())

    def test_all_source_quality_routes_fail_before_explicit_exhaustion(self):
        self.sources(('128k','320k'))
        runner = AsyncMock(side_effect=ValueError('no address'))
        with patch.object(music,'run_source',runner):
            response = self.client.post('/api/music/resolve',json={'song':self.song,'allow_platform_fallback':False})
        detail = response.json()['detail']
        self.assertEqual(runner.await_count,4); self.assertTrue(detail['exhausted'])
        self.assertFalse(detail['continue']); self.assertEqual(len(detail['attempted']),4)

    def test_budget_rate_limit_and_metadata_failure_never_mean_exhaustion(self):
        self.sources()
        with patch.object(music,'RESOLVE_SECONDS',0.1), patch.object(music,'run_source',AsyncMock()) as run:
            response = self.client.post('/api/music/resolve',json={'song':self.song,'allow_platform_fallback':False})
        self.assertEqual(run.await_count,0)
        self.assertFalse(response.json()['detail']['exhausted']); self.assertTrue(response.json()['detail']['continue'])
        with patch.object(music,'run_source',AsyncMock(side_effect=SourceRetryable(30))):
            response = self.client.post('/api/music/resolve',json={'song':self.song,'allow_platform_fallback':False})
        self.assertFalse(response.json()['detail']['exhausted'])
        self.assertEqual(response.json()['detail']['attempted'],[])
        music.SOURCE_COOLING.clear()
        with patch.object(music,'run_source',AsyncMock(side_effect=ValueError())), \
             patch.object(music,'recording_matches',AsyncMock(return_value=music.RecordingMatches([],['kw']))):
            response = self.client.post('/api/music/resolve',json={'song':self.song})
        self.assertFalse(response.json()['detail']['exhausted'])

    def test_invalid_outer_url_does_not_hide_a_working_inner_branch(self):
        script='const SOURCE_HANDLERS = {xinghai:{}}; function getUrlWithFallback(){} function getPlatformSongId(){}'
        self.sources(script=script)
        async def run(text,name,action,platform,info):
            return {'result':'https://example.com/good' if 'lx.on(' in text else 'https://example.com/bad'}
        def check(url):
            if url.endswith('/bad'): raise ValueError('404 placeholder')
            return url
        with patch.object(music,'run_source',side_effect=run), patch.object(music,'check_audio',side_effect=check):
            response = self.client.post('/api/music/resolve',json={'song':self.song,'allow_platform_fallback':False})
        self.assertEqual(response.status_code,200,response.text)
        self.assertTrue(response.json()['route_id'].endswith(':xinghai'))

    def test_timed_out_route_does_not_starve_unvisited_source_next_batch(self):
        self.sources()
        seen = []
        async def run(script, name, action, platform, info):
            seen.append(name)
            if name == '1': raise TimeoutError()
            return {'result':'https://example.com/good'}
        with patch.object(music,'run_source',side_effect=run), patch.object(music,'check_audio',return_value='https://example.com/good'):
            response = self.client.post('/api/music/resolve',json={'song':self.song,'allow_platform_fallback':False,'deferred':['1:wy:123:128k']})
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(seen,['2'])
