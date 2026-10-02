"""Privacy and credential tests against disposable SQLite only."""
import unittest
from jose import jwt
import auth
import models
from routers import users, notifications, visitors, music, media
import test_permissions


class AccountSecurityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        test_permissions.PermissionTests.setUpClass()
        cls.hashes = test_permissions.PermissionTests.hashes

    def setUp(self):
        with auth._security_lock:
            auth._security_attempts.clear()
        test_permissions.PermissionTests.setUp(self)
        for module in (users, notifications, visitors, music, media):
            self.client.app.include_router(module.router)
        with self.sessions() as db:
            db.add(models.Post(id=3, title='Public administrator article', content='Hello', user_id=self.ids['jackfei']))
            db.add(models.Post(id=4, title='Private administrator draft', content='secret', published=False, user_id=self.ids['jackfei']))
            db.add(models.Comment(post_id=3, user_id=self.ids['jackfei'], reply_to='jackfei', content='hello'))
            db.add(models.Follow(follower_id=self.ids['alice'], followed_id=self.ids['jackfei']))
            db.add(models.Notification(user_id=self.ids['alice'], sender_id=self.ids['jackfei'], type='comment', content='hello', post_id=3))
            db.add(models.VisitLog(user_id=self.ids['jackfei'], ip='127.0.0.1', path='/u/jackfei', user_agent='fixture'))
            db.commit()

    def tearDown(self):
        test_permissions.PermissionTests.tearDown(self)

    def headers(self, name='alice'):
        return test_permissions.PermissionTests.headers(self, name)

    def login(self, name='alice', password='alice-test-pass'):
        return self.client.post('/api/auth/login', json={'username': name, 'password': password})

    def change(self, headers=None, **overrides):
        body = {'current_password': 'alice-test-pass', 'new_password': 'new-test-password-456', 'confirm_password': 'new-test-password-456'}
        body.update(overrides)
        return self.client.put('/api/auth/password', json=body, headers=headers or self.headers())

    def test_public_identity_is_redacted_across_generated_surfaces(self):
        for path in ['/api/posts', '/api/posts/3?inc_view=false', '/api/rankings/posts', '/api/rankings/authors',
                     '/api/users/administrator', '/api/users/jackfei', '/api/users/alice/following',
                     '/api/posts/3/comments', '/api/music/recommended', '/api/visitors', '/api/notifications']:
            r = self.client.get(path, headers=self.headers())
            self.assertEqual(r.status_code, 200, (path, r.text))
            self.assertNotIn('jackfei', r.text, path)
            self.assertNotIn('password_hash', r.text)
        public = self.client.get('/api/users/administrator').json()
        self.assertEqual((public['username'], public['nickname']), ('administrator', '管理员'))
        with self.sessions() as db:
            self.assertEqual(db.get(models.User, self.ids['jackfei']).username, 'jackfei')

    def test_capabilities_stay_private_and_alias_resolves_with_draft_privacy(self):
        for who in ('alice', 'other-admin', 'jackfei'):
            r = self.client.get('/api/auth/me', headers=self.headers(who))
            self.assertEqual(r.json()['can_manage'], who == 'jackfei')
            self.assertEqual(r.headers['cache-control'], 'private, no-store')
        self.assertEqual(self.client.get('/api/auth/me', headers=self.headers('jackfei')).json()['public_username'], 'administrator')
        self.assertNotIn('Private administrator draft', self.client.get('/api/posts?author=administrator').text)
        self.assertIn('Private administrator draft', self.client.get('/api/posts?author=administrator', headers=self.headers('jackfei')).text)
        self.assertEqual(self.client.post('/api/users/administrator/follow', headers=self.headers('bob')).status_code, 200)
        for path in ('/api/admin/users', '/api/music/sources'):
            r = self.client.get(path, headers=self.headers())
            self.assertEqual(r.status_code, 403)
            self.assertNotIn('jackfei', r.text)

    def test_reserved_alias_cannot_be_registered(self):
        for name in ('administrator', 'Administrator', '管理员', 'JackFei'):
            r = self.client.post('/api/auth/register', json={'username': name, 'password': 'secret-test-password'})
            self.assertEqual(r.status_code, 422, r.text)
            self.assertNotIn('secret-test-password', r.text)

    def test_password_requires_login_and_correct_current_password(self):
        self.assertEqual(self.client.put('/api/auth/password', json={}).status_code, 401)
        r = self.change(current_password='wrong-password')
        self.assertEqual(r.status_code, 403)
        self.assertNotIn('wrong-password', r.text)
        self.assertEqual(self.login().status_code, 200)
        with self.sessions() as db:
            self.assertIsNone(db.get(models.PasswordState, self.ids['alice']))

    def test_password_validation_preserves_account(self):
        for value, confirm in [('short', 'short'), ('你好' * 13, '你好' * 13),
                               ('new-test-password', 'mismatch'), ('alice-test-pass', 'alice-test-pass')]:
            r = self.change(new_password=value, confirm_password=confirm)
            self.assertEqual(r.status_code, 400, r.text)
        self.assertEqual(self.login().status_code, 200)

    def test_change_invalidates_new_and_legacy_sessions_not_other_accounts(self):
        tokens = [self.login().json()['access_token'], self.login().json()['access_token'], auth.create_access_token('alice')]
        r = self.change(headers={'Authorization': 'Bearer ' + tokens[0]})
        self.assertEqual(r.status_code, 204, r.text)
        self.assertEqual(r.headers['cache-control'], 'private, no-store')
        for token in tokens:
            headers = {'Authorization': 'Bearer ' + token}
            self.assertEqual(self.client.get('/api/auth/me', headers=headers).status_code, 401)
            self.assertEqual(self.change(headers=headers).status_code, 401)
        self.assertEqual(self.client.get('/api/auth/me', headers=self.headers('bob')).status_code, 200)
        self.assertEqual(self.login().status_code, 401)
        fresh = self.login(password='new-test-password-456')
        self.assertEqual(fresh.status_code, 200, fresh.text)
        self.assertEqual(self.client.get('/api/auth/me', headers={'Authorization': 'Bearer ' + fresh.json()['access_token']}).status_code, 200)
        with self.sessions() as db:
            self.assertTrue(auth.verify_password('new-test-password-456', db.get(models.User, self.ids['alice']).password_hash))
            self.assertIsNotNone(db.get(models.PasswordState, self.ids['alice']))

    def test_repeated_change_and_user_isolation(self):
        self.assertEqual(self.change().status_code, 204)
        fresh = self.login(password='new-test-password-456').json()['access_token']
        r = self.change(headers={'Authorization': 'Bearer ' + fresh}, current_password='new-test-password-456', new_password='third-test-password', confirm_password='third-test-password')
        self.assertEqual(r.status_code, 204, r.text)
        self.assertEqual(self.client.get('/api/auth/me', headers={'Authorization': 'Bearer ' + fresh}).status_code, 401)
        self.assertEqual(self.login(password='third-test-password').status_code, 200)
        self.assertEqual(self.login('bob', 'bob-test-pass').status_code, 200)

    def test_password_and_login_have_separate_throttles(self):
        for _ in range(5):
            self.assertEqual(self.change(current_password='bad').status_code, 403)
        r = self.change()
        self.assertEqual(r.status_code, 429)
        self.assertIn('retry-after', r.headers)
        self.assertEqual(self.login().status_code, 200)
        for _ in range(5):
            self.assertEqual(self.login('bob', 'bad').status_code, 401)
        self.assertEqual(self.login('bob', 'bob-test-pass').status_code, 429)
        self.assertEqual(self.login().status_code, 200)
        with auth._security_lock:
            auth._security_attempts[('login', 'bob')] = (auth.time.monotonic() - 301, 5)
        self.assertEqual(self.login('bob', 'bob-test-pass').status_code, 200)

    def test_arbitrary_account_ids_rejected_and_validation_redacts_passwords(self):
        r = self.change(user_id=self.ids['bob'], username='bob')
        self.assertEqual(r.status_code, 422)
        self.assertNotIn('new-test-password-456', r.text)
        self.assertEqual(self.login('bob', 'bob-test-pass').status_code, 200)
        r = self.client.post('/api/auth/login', json={'username': 'alice', 'password': 'secret-' * 30})
        self.assertEqual(r.status_code, 422)
        self.assertNotIn('secret-', r.text)

    def test_password_state_cleanup_on_account_deletion(self):
        self.assertEqual(self.change().status_code, 204)
        r = self.client.request('DELETE', f"/api/admin/users/{self.ids['alice']}", headers=self.headers('jackfei'), json={'password': 'jackfei-test-pass'})
        self.assertEqual(r.status_code, 200, r.text)
        with self.sessions() as db:
            self.assertIsNone(db.get(models.PasswordState, self.ids['alice']))

    def test_token_tag_is_opaque_and_invalid_tags_are_rejected(self):
        with self.sessions() as db:
            user = db.get(models.User, self.ids['alice'])
            payload = jwt.decode(auth.create_access_token(user.username, user), auth.SECRET_KEY, algorithms=[auth.ALGORITHM])
            self.assertNotIn(user.password_hash, str(payload))
            payload['pwd'] = '错误标签'
            bad = jwt.encode(payload, auth.SECRET_KEY, algorithm=auth.ALGORITHM)
        self.assertEqual(self.client.get('/api/auth/me', headers={'Authorization': 'Bearer ' + bad}).status_code, 401)
