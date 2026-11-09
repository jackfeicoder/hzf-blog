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
        self.assertEqual(missing.status_code, 400)
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
        self.assertEqual(self.register(invite['code'], 'reader').status_code, 409)
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

    def test_settings_default_private_write_and_strict_validation(self):
        response = self.client.get('/api/auth/registration-settings')
        self.assertEqual(response.json(), {'invite_required': True})
        self.assertIn('no-store', response.headers['cache-control'])
        with self.sessions() as db:
            self.assertEqual(db.query(models.RegistrationSettings).count(), 0)
        for name in (None, 'reader', 'legacy-admin'):
            headers = self.headers(name) if name else {}
            response = self.client.put('/api/auth/registration-settings', headers=headers, json={'invite_required': False})
            self.assertEqual(response.status_code, 403 if name else 401)
        for body in ({'invite_required': 'false'}, {'invite_required': 0}, {'invite_required': False, 'extra': 1}):
            self.assertEqual(self.client.put('/api/auth/registration-settings', headers=self.headers(), json=body).status_code, 422)
        self.assertTrue(self.client.get('/api/auth/registration-settings').json()['invite_required'])

    def test_duplicate_registration_never_logs_in_or_changes_existing_password(self):
        invite = self.create()
        for name in ('reader', ' reader ', 'reader  '):
            result = self.register(invite['code'], name)
            self.assertEqual(result.status_code, 409, result.text)
            self.assertNotIn('access_token', result.json())
        with self.sessions() as db:
            self.assertEqual(db.query(models.User).count(), 3)
            self.assertEqual(db.get(models.User, self.ids['reader']).password_hash, self.password_hash)
        row = self.client.get('/api/auth/invitations', headers=self.headers()).json()['items'][0]
        self.assertEqual(row['status'], 'available')
        self.client.put('/api/auth/registration-settings', headers=self.headers(), json={'invite_required': False})
        self.assertEqual(self.register('', 'reader').status_code, 409)

    def test_concurrent_same_username_with_two_invitations_creates_one_account(self):
        codes = [self.create()['code'], self.create()['code']]
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda code: self.register(code, 'same-reader').status_code, codes))
        self.assertEqual(sorted(results), [200, 409], results)
        with self.sessions() as db:
            self.assertEqual(db.query(models.User).filter_by(username='same-reader').count(), 1)
            self.assertEqual(db.query(models.RegistrationInvite).filter(models.RegistrationInvite.used_at.is_not(None)).count(), 1)

    def test_open_registration_persists_and_preserves_codes_when_reenabled(self):
        invite = self.create()
        saved = self.client.put('/api/auth/registration-settings', headers=self.headers(), json={'invite_required': False})
        self.assertEqual(saved.status_code, 200, saved.text)
        with self.sessions() as db:
            self.assertFalse(db.get(models.RegistrationSettings, 1).invite_required)
        # No in-memory policy: a fresh request/session observes the saved state.
        self.assertFalse(self.client.get('/api/auth/registration-settings').json()['invite_required'])
        result = self.client.post('/api/auth/register', json={'username': 'open-reader', 'password': 'open-password'})
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(self.register(invite['code'], 'another-open-reader').status_code, 200)
        self.assertEqual(self.client.get('/api/auth/invitations', headers=self.headers()).json()['items'][0]['status'], 'available')
        self.client.put('/api/auth/registration-settings', headers=self.headers(), json={'invite_required': True})
        # A page opened before the switch still faces the current backend policy.
        self.assertEqual(self.register('', 'stale-open-reader').status_code, 400)
        self.assertEqual(self.register(invite['code'], 'invited-reader').status_code, 200)
        login = self.client.post('/api/auth/login', json={'username': 'open-reader', 'password': 'open-password'})
        self.assertEqual(login.status_code, 200)

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
