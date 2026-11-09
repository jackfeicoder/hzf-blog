"""Invitation access, atomic consumption and visitor identity grouping."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import auth
import models
from database import Base, get_db
from routers import auth_router, visitors


class InvitationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.password_hash = auth.hash_password('existing-password')

    def setUp(self):
        auth._security_attempts.clear()
        self.temp = tempfile.TemporaryDirectory()
        self.engine = create_engine('sqlite:///' + str(Path(self.temp.name) / 'test.db'),
                                    connect_args={'check_same_thread': False, 'timeout': 15})
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine)
        with self.sessions() as db:
            for name in ('jackfei', 'reader', 'legacy-admin'):
                db.add(models.User(username=name, nickname=name, password_hash=self.password_hash,
                                   is_admin=name == 'legacy-admin'))
            db.commit()
            self.ids = {u.username: u.id for u in db.query(models.User)}
        app = FastAPI()
        app.include_router(auth_router.router)
        app.include_router(visitors.router)
        def override():
            with self.sessions() as db:
                yield db
        app.dependency_overrides[get_db] = override
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        self.engine.dispose()
        self.temp.cleanup()

    def headers(self, name='jackfei'):
        return {'Authorization': 'Bearer ' + auth.create_access_token(name)}

    def create(self):
        result = self.client.post('/api/auth/invitations', headers=self.headers())
        self.assertEqual(result.status_code, 201, result.text)
        self.assertIn('no-store', result.headers['cache-control'])
        return result.json()

    def register(self, code, username='new-reader'):
        return self.client.post('/api/auth/register', json={
            'username': username, 'password': 'new-password', 'invite_code': code,
        })

    def test_only_superadmin_can_create_list_revoke(self):
        invite = self.create()
        for name in (None, 'reader', 'legacy-admin'):
            headers = self.headers(name) if name else {}
            expected = 403 if name else 401
            self.assertEqual(self.client.get('/api/auth/invitations', headers=headers).status_code, expected)
            self.assertEqual(self.client.post('/api/auth/invitations', headers=headers).status_code, expected)
            self.assertEqual(self.client.delete(f"/api/auth/invitations/{invite['id']}", headers=headers).status_code, expected)

    def test_random_unique_six_character_codes_and_pagination(self):
        codes = [self.create()['code'] for _ in range(5)]
        self.assertEqual(len(set(codes)), 5)
        for code in codes:
            self.assertRegex(code, r'^[A-Z2-9]{6}$')
        self.assertEqual(self.client.get('/api/auth/invitations', headers=self.headers()).json()['total'], 5)
        self.assertEqual(self.client.get('/api/auth/invitations?page=2', headers=self.headers()).json()['items'], [])

    def test_required_invalid_and_revoked_invitation(self):
        missing = self.client.post('/api/auth/register', json={'username': 'new-reader', 'password': 'new-password'})
        self.assertEqual(missing.status_code, 422)
        self.assertEqual(self.register('ABC123').status_code, 400)
        invite = self.create()
        self.assertEqual(self.client.delete(f"/api/auth/invitations/{invite['id']}", headers=self.headers()).status_code, 204)
        self.assertEqual(self.register(invite['code']).status_code, 400)
        with self.sessions() as db:
            self.assertEqual(db.query(models.User).count(), 3)

    def test_single_use_case_insensitive_and_existing_login_unchanged(self):
        invite = self.create()
        result = self.register(invite['code'].lower())
        self.assertEqual(result.status_code, 200, result.text)
        me = self.client.get('/api/auth/me', headers={'Authorization': 'Bearer ' + result.json()['access_token']})
        self.assertEqual(me.json()['username'], 'new-reader')
        self.assertEqual(self.register(invite['code'], 'second-reader').status_code, 400)
        used = self.client.get('/api/auth/invitations', headers=self.headers()).json()['items'][0]
        self.assertEqual((used['status'], used['used_by']), ('used', 'new-reader'))
        self.assertEqual(self.client.post('/api/auth/login', json={'username': 'reader', 'password': 'existing-password'}).status_code, 200)

    def test_existing_username_and_failed_commit_do_not_consume_code(self):
        invite = self.create()
        self.assertEqual(self.register(invite['code'], 'reader').status_code, 400)
        with patch.object(auth_router, 'hash_password', side_effect=RuntimeError('fixture')):
            with self.assertRaises(RuntimeError):
                self.register(invite['code'])
        self.assertEqual(self.register(invite['code']).status_code, 200)

    def test_concurrent_registration_consumes_code_once(self):
        invite = self.create()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda name: self.register(invite['code'], name).status_code, ['reader-one', 'reader-two']))
        self.assertEqual(results.count(200), 1, results)
        with self.sessions() as db:
            self.assertEqual(db.query(models.User).count(), 4)

    def test_failed_guesses_are_throttled(self):
        for _ in range(10):
            self.assertEqual(self.register('ABC123').status_code, 400)
        self.assertEqual(self.register('ABC123').status_code, 429)

    def test_latest_ten_distinct_visitors(self):
        now = datetime.utcnow()
        with self.sessions() as db:
            # One logged-in account on many addresses occupies one row.
            for n in range(15):
                db.add(models.VisitLog(user_id=self.ids['reader'], ip=f'192.0.2.{n}', path=f'/reader/{n}', created_at=now + timedelta(seconds=n)))
            # Different accounts on the same IP remain distinct.
            db.add(models.VisitLog(user_id=self.ids['legacy-admin'], ip='192.0.2.14', path='/other', created_at=now + timedelta(seconds=16)))
            for n in range(12):
                for repeat in range(2):
                    db.add(models.VisitLog(ip=f'198.51.100.{n}', path=f'/guest/{n}/{repeat}', created_at=now - timedelta(seconds=n * 2 + repeat)))
            db.commit()
        with patch.object(visitors, 'record_visit'):
            result = self.client.get('/api/visitors', headers=self.headers())
        self.assertEqual(result.status_code, 200, result.text)
        rows = result.json()['items']
        self.assertEqual(len(rows), 10)
        self.assertEqual(rows[0]['path'], '/other')
        self.assertEqual(rows[1]['path'], '/reader/14')
        identities = [('user', r['user']['id']) if r['user'] else ('ip', r['ip']) for r in rows]
        self.assertEqual(len(set(identities)), 10)
        self.assertTrue(all(r['path'].endswith('/0') for r in rows if r['is_guest']))
        self.assertIn('no-store', result.headers['cache-control'])
        self.assertEqual(self.client.get('/api/visitors', headers=self.headers('reader')).status_code, 403)
