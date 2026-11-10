"""Exercise the real production app, not routers missing the global gate."""
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient

import auth
from database import get_db
from main import app
import models
from routers import music
import test_invitations as invitations


class GuestAccessTests(unittest.TestCase):
    headers = invitations.InvitationTests.headers

    @classmethod
    def setUpClass(cls):
        cls.password_hash = auth.hash_password('existing-password')

    def setUp(self):
        invitations.InvitationTests.setUp(self)
        self.client.close()
        def override():
            with self.sessions() as db:
                yield db
        app.dependency_overrides[get_db] = override
        self.client = TestClient(app)
        with self.sessions() as db:
            db.add(models.Post(id=1, user_id=self.ids['reader'], title='Public summary', summary='Preview only', content='MEMBERS_ONLY_FULL_TEXT'))
            db.commit()

    def tearDown(self):
        app.dependency_overrides.clear()
        invitations.InvitationTests.tearDown(self)

    def test_homepage_and_introduction_still_load_without_private_profile(self):
        for path in ('/api/health', '/api/appearance', '/api/categories', '/api/posts', '/api/rankings/posts?limit=8', '/api/rankings/authors?limit=6', '/api/auth/registration-settings', '/api/auth/welcome-author'):
            result = self.client.get(path)
            self.assertEqual(result.status_code, 200, (path, result.text))
            self.assertNotIn('MEMBERS_ONLY_FULL_TEXT', result.text)
        author = self.client.get('/api/auth/welcome-author').json()
        self.assertEqual(author['username'], 'administrator')
        self.assertNotIn('password_hash', author)
        self.assertNotIn('can_manage', author)
        self.assertNotIn('post_count', author)

    def test_private_apis_block_guests_invalid_tokens_and_trailing_slashes(self):
        paths = ('/api/posts/1', '/api/posts/1/comments', '/api/users/reader', '/api/users/reader/favorites',
                 '/api/media/videos', '/api/music/recommended', '/api/music/lyrics?source=wy&id=1',
                 '/api/music/search?source=wy&keywords=test', '/api/chat/providers', '/api/study/bank')
        for path in paths:
            for headers in ({}, {'Authorization': 'Bearer invalid'}):
                result = self.client.get(path, headers=headers)
                self.assertEqual(result.status_code, 401, (path, result.text))
                self.assertIn('no-store', result.headers['cache-control'])
        self.assertEqual(self.client.get('/api/media/videos/').status_code, 401)
        self.assertEqual(self.client.post('/api/music/resolve', json={}).status_code, 401)

    def test_members_keep_normal_access_but_do_not_gain_admin_rights(self):
        for path in ('/api/posts/1?inc_view=false', '/api/users/reader', '/api/media/videos', '/api/music/recommended'):
            self.assertEqual(self.client.get(path, headers=self.headers('reader')).status_code, 200, path)
        self.assertEqual(self.client.get('/api/visitors', headers=self.headers('reader')).status_code, 403)
        self.assertEqual(self.client.post('/api/auth/invitations', headers=self.headers('reader')).status_code, 403)

    def test_login_register_and_signed_audio_are_not_broken_by_page_gate(self):
        login = self.client.post('/api/auth/login', json={'username': 'reader', 'password': 'existing-password'})
        self.assertEqual(login.status_code, 200)
        self.assertEqual(self.client.post('/api/auth/register', json={'username': 'fresh-reader', 'password': 'password'}).status_code, 400)
        with patch.object(music.FILE_CACHE, 'by_ticket', return_value=None):
            self.assertEqual(self.client.get('/api/music/stream/invalid-capability').status_code, 410)

    def test_route_tracking_is_public_but_reading_logs_stays_admin_only(self):
        ip_headers = {'X-Forwarded-For': '192.0.2.80'}
        self.assertEqual(self.client.post('/api/visitors/track', json={'path': '/'}, headers=ip_headers).status_code, 204)
        self.assertEqual(self.client.post('/api/visitors/track', json={'path': '/music'}, headers={**ip_headers, **self.headers('reader')}).status_code, 204)
        with self.sessions() as db:
            row = db.query(models.VisitLog).filter_by(ip='192.0.2.80').one()
            self.assertEqual(row.path, '/music')
            self.assertEqual(row.user_id, self.ids['reader'])
        self.assertEqual(self.client.get('/api/visitors').status_code, 401)
        for path in ('https://example.com', '//example.com', '/api/auth/login', '/music?token=private', '/music#private'):
            self.assertEqual(self.client.post('/api/visitors/track', json={'path': path}).status_code, 422)
