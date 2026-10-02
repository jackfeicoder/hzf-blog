import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from auth import create_access_token
from database import Base, get_db
from models import User
from music_models import MusicSource, MusicList, MusicEntry, clear_music
from music_http import target
from routers import music


class MusicTests(unittest.TestCase):
    def setUp(self):
        music.CACHE.clear(); music.LIMITS.clear(); music.TICKETS.clear()
        self.temp = tempfile.TemporaryDirectory()
        self.engine = create_engine(f"sqlite:///{Path(self.temp.name) / 'music.db'}", connect_args={'check_same_thread': False})
        event.listen(self.engine, 'connect', lambda c, _: c.execute('PRAGMA foreign_keys=ON'))
        Base.metadata.create_all(self.engine)
        self.session = sessionmaker(bind=self.engine)
        with self.session() as db:
            for name in ('jackfei', 'alice', 'bob', 'other-admin'):
                db.add(User(username=name, nickname=name, password_hash='unused', is_admin=name in ('jackfei', 'other-admin')))
            db.commit()
        app = FastAPI(); app.include_router(music.router)
        def override():
            with self.session() as db:
                yield db
        app.dependency_overrides[get_db] = override
        self.client = TestClient(app)
        self.song = dict(source='wy', id='123', name='测试歌曲', singer='测试歌手', album='', pic_id='', lyric_id='', duration=0)

    def headers(self, name='alice'):
        return {'Authorization': 'Bearer ' + create_access_token(name)}

    def tearDown(self):
        self.client.close(); self.engine.dispose(); self.temp.cleanup()

    def test_empty_recommendation_read_does_not_create_private_library(self):
        response = self.client.get('/api/music/recommended')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'name': 'jackfei的歌单', 'owner': 'jackfei', 'songs': []})
        self.assertEqual(response.headers['cache-control'], 'no-store')
        with self.session() as db:
            self.assertEqual(db.query(MusicList).count(), 0)
            db.delete(db.query(User).filter_by(username='jackfei').one()); db.commit()
        self.assertEqual(self.client.get('/api/music/recommended').json()['songs'], [])

    def test_public_recommendation_exposes_only_jackfei_favorites_and_updates(self):
        j = self.headers('jackfei')
        lists = self.client.get('/api/music/library', headers=j).json()
        favorites = next(l for l in lists if l['kind'] == 'favorites')['id']
        history = next(l for l in lists if l['kind'] == 'history')['id']
        playlist = self.client.post('/api/music/lists', headers=j, json={'name': '私人歌单'}).json()['id']
        self.client.put(f'/api/music/lists/{favorites}/songs', headers=j, json=self.song)
        for i, lid in enumerate((history, playlist), 10):
            self.client.put(f'/api/music/lists/{lid}/songs', headers=j, json={**self.song, 'id': str(i), 'name': '私有歌曲'})
        for who in ('alice', 'bob', 'other-admin'):
            own = self.client.get('/api/music/library', headers=self.headers(who)).json()[0]['id']
            self.client.put(f'/api/music/lists/{own}/songs', headers=self.headers(who), json={**self.song, 'id': who, 'name': '别人的收藏'})
        for who in (None, 'alice', 'jackfei', 'other-admin'):
            response = self.client.get('/api/music/recommended', headers=self.headers(who) if who else {})
            self.assertEqual(response.json(), {'name': 'jackfei的歌单', 'owner': 'jackfei', 'songs': [self.song]})
            self.assertNotIn('list_id', response.text)
        for who, code in ((None, 401), ('alice', 404), ('other-admin', 404)):
            for method in ('PUT', 'DELETE'):
                response = self.client.request(method, f'/api/music/lists/{favorites}/songs', headers=self.headers(who) if who else {}, **({'json': self.song} if method == 'PUT' else {}))
                self.assertEqual(response.status_code, code)
        self.assertEqual(self.client.delete(f'/api/music/lists/{favorites}/songs?key=wy:123', headers=j).status_code, 200)
        self.assertEqual(self.client.get('/api/music/recommended').json()['songs'], [])

    def test_recommendation_is_readonly_and_deduplicates_stored_entries(self):
        with self.session() as db:
            user = db.query(User).filter_by(username='jackfei').one()
            for _ in range(2):
                row = MusicList(user_id=user.id, name='我喜欢', kind='favorites'); db.add(row); db.flush()
                db.add(MusicEntry(list_id=row.id, song_key='wy:123', song=json.dumps(self.song)))
            db.commit()
        self.assertEqual(self.client.get('/api/music/recommended').json()['songs'], [self.song])
        for method in ('POST', 'PUT', 'DELETE'):
            self.assertEqual(self.client.request(method, '/api/music/recommended', json=self.song).status_code, 405)

    def test_library_owner_isolation_and_fk_cleanup(self):
        a = self.client.get('/api/music/library', headers=self.headers())
        self.assertEqual(a.headers['cache-control'], 'private, no-store')
        favorite = a.json()[0]['id']
        self.assertEqual(self.client.put(f'/api/music/lists/{favorite}/songs', headers=self.headers(), json=self.song).status_code, 200)
        self.assertEqual(self.client.get('/api/music/library', headers=self.headers()).json()[0]['songs'], [self.song])
        self.assertEqual(self.client.get('/api/music/library', headers=self.headers('bob')).json()[0]['songs'], [])
        for method in ('PUT', 'DELETE'):
            r = self.client.request(method, f'/api/music/lists/{favorite}/songs', headers=self.headers('bob'), **({'json': self.song} if method == 'PUT' else {}))
            self.assertEqual(r.status_code, 404)
        self.assertEqual(self.client.get('/api/music/library').status_code, 401)
        with self.session() as db:
            user = db.query(User).filter_by(username='alice').one(); clear_music(db, user.id); db.delete(user); db.commit()

    def test_playlist_crud_system_protection_validation_and_dedup(self):
        h = self.headers()
        self.assertEqual(self.client.post('/api/music/lists', json={'name': ' '}, headers=h).status_code, 422)
        row = self.client.post('/api/music/lists', json={'name': '我的歌单'}, headers=h).json()
        path = f"/api/music/lists/{row['id']}"
        self.assertEqual(self.client.put(path, json={'name': '改名'}, headers=h).status_code, 200)
        for _ in range(2):
            self.assertEqual(self.client.put(path + '/songs', json=self.song, headers=h).status_code, 200)
        listing = self.client.get('/api/music/library', headers=h).json()
        self.assertEqual(next(l for l in listing if l['id'] == row['id'])['songs'], [self.song])
        for l in listing:
            if l['kind'] != 'playlist':
                self.assertEqual(self.client.delete(f"/api/music/lists/{l['id']}", headers=h).status_code, 409)
        self.assertEqual(self.client.delete(path + '/songs?key=wy:123', headers=h).status_code, 200)
        self.assertEqual(self.client.delete(path, headers=h).status_code, 200)
        self.assertEqual(self.client.put(path + '/songs', headers=h, json=self.song).status_code, 404)

    def test_only_superadmin_imports_and_scripts_never_public(self):
        body = {'name': 'test', 'script': 'globalThis.lx; // TOKEN hidden'}
        for who, code in ((None, 401), ('alice', 403), ('other-admin', 403)):
            self.assertEqual(self.client.post('/api/music/sources', json=body, headers=self.headers(who) if who else {}).status_code, code)
        row = self.client.post('/api/music/sources', json=body, headers=self.headers('jackfei')).json()
        self.assertNotIn('script', row)
        self.assertNotIn('TOKEN', self.client.get('/api/music/sources').text)
        self.assertEqual(self.client.put(f"/api/music/sources/{row['id']}", headers=self.headers('jackfei'), json={'enabled': True, 'position': 0}).status_code, 409)
        self.assertEqual(self.client.post('/api/music/sources', json=body, headers=self.headers('jackfei')).status_code, 409)

    def test_resolver_fallback_and_opaque_ticket(self):
        with self.session() as db:
            for i in range(2):
                db.add(MusicSource(name=str(i), script='script', digest=str(i) * 64, enabled=True, position=i, capabilities=json.dumps({'wy': {'actions': ['musicUrl']}})))
            db.commit()
        runner = AsyncMock(side_effect=[ValueError('failure'), {'result': 'https://public.example/audio.mp3'}])
        with patch.object(music, 'run_source', runner), patch.object(music, 'check_audio', return_value='https://public.example/audio.mp3'):
            result = self.client.post('/api/music/resolve', json={'song': self.song})
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()['source_name'], '1')
        self.assertNotIn('public.example', result.text)
        self.assertEqual(result.headers['cache-control'], 'private, no-store')
        self.assertEqual(self.client.get('/api/music/stream/unknown').status_code, 410)
        self.assertEqual(self.client.get(result.json()['url'], headers={'Range': 'bytes=0-1,4-5'}).status_code, 416)

    def test_search_caches_but_private_data_never_does(self):
        upstream = AsyncMock(return_value=[dict(id='1', name='测试', artist=['a'], album='b', pic_id='2', lyric_id='3')])
        with patch.object(music, 'upstream', upstream):
            r = self.client.get('/api/music/search?q=test')
            r2 = self.client.get('/api/music/search?q=test')
        self.assertEqual(r.status_code, 200); self.assertEqual(r.json(), r2.json()); self.assertEqual(upstream.await_count, 1)
        self.assertEqual(self.client.get('/api/music/search?q=test&source=bad').status_code, 422)
        self.assertEqual(self.client.post('/api/music/resolve', json={'song': {**self.song, 'url': 'http://127.0.0.1'}}).status_code, 422)

    def test_http_bridge_private_metadata_and_dns_rebinding(self):
        addresses = ['127.0.0.1', '10.0.0.1', '172.18.80.117', '192.168.1.1', '169.254.169.254', '::1', '::ffff:127.0.0.1']
        for address in addresses:
            with patch('music_http.socket.getaddrinfo', return_value=[(2, 1, 6, '', (address, 443))]):
                with self.assertRaises(ValueError): target('https://example.com')
        with patch('music_http.socket.getaddrinfo', return_value=[(2, 1, 6, '', ('8.8.8.8', 443)), (2, 1, 6, '', ('127.0.0.1', 443))]):
            with self.assertRaises(ValueError): target('https://example.com')
        for url in ('file:///etc/passwd', 'http://x:8001', 'https://u:p@x', 'https://x/a\nb', 'https://x\\y'):
            with self.assertRaises(ValueError): target(url)

    def test_caches_and_tickets_are_bounded(self):
        for i in range(700):
            music.remember(str(i), str(i)); music.ticket('https://example.com/audio', 1, 'source')
        self.assertEqual(len(music.CACHE), 300); self.assertEqual(len(music.TICKETS), 500)

    def test_lyrics_uses_independent_platform_and_caches(self):
        upstream = AsyncMock(return_value={'lrc': {'lyric': '[00:01]Test'}, 'tlyric': {'lyric': '[00:01]译'}})
        with patch.object(music, 'upstream', upstream):
            r = self.client.get('/api/music/lyrics?source=wy&id=123')
            second = self.client.get('/api/music/lyrics?source=wy&id=123')
        self.assertEqual(r.json(), {'lyric': '[00:01]Test', 'translation': '[00:01]译'})
        self.assertEqual(r.json(), second.json()); self.assertEqual(upstream.await_count, 1)

    def test_search_independent_platform_fallback(self):
        upstream = AsyncMock(side_effect=[ValueError(), {'result': {'songs': [{'id': 123, 'name': 'Test', 'artists': [{'name': 'Singer'}], 'album': {'name': 'Album', 'picId': 456}, 'duration': 60000}]}}])
        with patch.object(music, 'upstream', upstream):
            r = self.client.get('/api/music/search?q=test')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['items'][0]['duration'], 60)
        self.assertEqual(r.json()['items'][0]['pic_id'], '456')

    def test_cover_accepts_real_provider_jpg_mime_and_caches(self):
        from unittest.mock import Mock
        response = Mock(status=200)
        response.getheader.return_value = 'image/jpg'
        response.read.return_value = b'\xff\xd8test'
        upstream = AsyncMock(return_value={'songs': [{'album': {'picUrl': 'https://example.com/cover.jpg'}}]})
        with patch.object(music, 'upstream', upstream), patch.object(music, 'open_http', return_value=(response, Mock(), 'https://example.com/cover.jpg')):
            r = self.client.get('/api/music/cover?source=wy&id=456&song_id=123')
            second = self.client.get('/api/music/cover?source=wy&id=456&song_id=123')
        self.assertEqual(r.status_code, 200); self.assertEqual(r.headers['content-type'], 'image/jpeg')
        self.assertEqual(r.content, second.content); self.assertEqual(upstream.await_count, 1)
