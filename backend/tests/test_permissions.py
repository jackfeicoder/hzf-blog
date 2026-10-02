"""Disposable DB permission tests, including foreign-key-on deletion cleanup."""
import tempfile
import unittest
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

import auth
import models
from database import Base, get_db
from routers import admin, auth_router, comments, posts, study
from study_models import StudyDay, StudyProgress, StudyRound
from music_models import MusicList, MusicEntry


class PermissionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.hashes = {name: auth.hash_password(f"{name}-test-pass") for name in ("alice", "bob", "jackfei", "other-admin")}

    def setUp(self):
        with auth._delete_lock:
            auth._delete_attempts.clear()
        self.temp = tempfile.TemporaryDirectory()
        self.engine = create_engine(f"sqlite:///{Path(self.temp.name) / 'permissions.db'}", connect_args={"check_same_thread": False})
        @event.listens_for(self.engine, "connect")
        def enforce_fks(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine)
        with self.sessions() as db:
            for name, hashed in self.hashes.items():
                db.add(models.User(username=name, nickname=name, password_hash=hashed, is_admin=name == "other-admin"))
            db.flush()
            self.ids = {u.username: u.id for u in db.query(models.User).all()}
            db.add(models.Category(name="Test")); db.flush()
            db.add(models.Post(id=1, title="Alice article", content="private content", user_id=self.ids["alice"], category_id=1, tags=[models.Tag(name="java")]))
            db.add(models.Post(id=2, title="Bob draft", content="draft content", user_id=self.ids["bob"], published=False))
            db.commit()
        app = FastAPI()
        for module in (posts, comments, admin, auth_router, study):
            app.include_router(module.router)
        def override():
            with self.sessions() as db:
                yield db
        app.dependency_overrides[get_db] = override
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close(); self.engine.dispose(); self.temp.cleanup()

    def headers(self, name):
        return {"Authorization": f"Bearer {auth.create_access_token(name)}"}

    def delete(self, name, post_id=1, password=None):
        return self.client.request("DELETE", f"/api/posts/{post_id}", headers=self.headers(name),
                                   json={"password": password or f"{name}-test-pass"})

    def test_owner_password_required_and_wrong_password_keeps_data(self):
        self.assertEqual(self.client.delete('/api/posts/1', headers=self.headers('alice')).status_code, 422)
        self.assertEqual(self.delete('alice', password='wrong').status_code, 403)
        self.assertEqual(self.client.get('/api/posts/1?inc_view=false').status_code, 200)
        self.assertEqual(self.delete('alice').status_code, 200)
        self.assertEqual(self.client.get('/api/posts/1?inc_view=false').status_code, 404)

    def test_other_users_even_legacy_admin_cannot_delete_or_edit(self):
        for name in ('bob', 'other-admin'):
            self.assertEqual(self.delete(name).status_code, 403)
            self.assertEqual(self.client.put('/api/posts/1', headers=self.headers(name), json={'title': 'Hijack', 'content': 'new'}).status_code, 403)
        self.assertEqual(self.client.request('DELETE', '/api/posts/1', json={'password': 'alice-test-pass'}).status_code, 401)

    def test_superadmin_uses_own_password_not_article_owners(self):
        self.assertEqual(self.delete('jackfei', password='alice-test-pass').status_code, 403)
        self.assertEqual(self.client.get('/api/posts/2?inc_view=false', headers=self.headers('jackfei')).status_code, 200)
        edited = self.client.put('/api/posts/1', headers=self.headers('jackfei'), json={'title': 'Managed', 'content': 'new'})
        self.assertEqual(edited.status_code, 200, edited.text)
        self.assertEqual(self.delete('jackfei').status_code, 200)

    def test_confirmation_throttled_and_success_clears_failures(self):
        for _ in range(5):
            self.assertEqual(self.delete('alice', password='wrong').status_code, 403)
        blocked = self.delete('alice')
        self.assertEqual(blocked.status_code, 429)
        self.assertIn('retry-after', blocked.headers)
        with auth._delete_lock:
            auth._delete_attempts[self.ids['alice']] = (auth.time.monotonic() - 301, 5)
        self.assertEqual(self.delete('alice').status_code, 200)
        self.assertNotIn(self.ids['alice'], auth._delete_attempts)

    def test_deletion_cleans_links_and_preserves_notification(self):
        with self.sessions() as db:
            db.add(models.Comment(post_id=1, user_id=self.ids['bob'], content='comment'))
            db.add(models.Like(post_id=1, user_id=self.ids['bob']))
            db.add(models.Favorite(post_id=1, user_id=self.ids['bob']))
            db.add(models.Notification(post_id=1, user_id=self.ids['alice'], sender_id=self.ids['bob'], type='like'))
            db.commit()
        self.assertEqual(self.delete('alice').status_code, 200)
        with self.sessions() as db:
            for model in (models.Comment, models.Like, models.Favorite):
                self.assertEqual(db.query(model).count(), 0)
            self.assertEqual(db.execute(models.post_tags.select()).all(), [])
            self.assertIsNone(db.query(models.Notification).one().post_id)
            self.assertEqual(db.query(models.Tag).count(), 1)

    def test_all_admin_routes_block_normal_and_other_admin(self):
        for name in ('alice', 'other-admin'):
            for path in ('/posts', '/users', '/categories', '/comments', f"/users/{self.ids['bob']}/study/today"):
                self.assertEqual(self.client.get('/api/admin' + path, headers=self.headers(name)).status_code, 403)
            self.assertEqual(self.client.post('/api/admin/users', headers=self.headers(name), json={'username': 'new', 'password': 'test-password'}).status_code, 403)
        response = self.client.get('/api/admin/posts', headers=self.headers('jackfei'))
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['total'], 2)
        self.assertEqual(response.headers['cache-control'], 'private, no-store')
        self.assertNotIn('content', response.json()['items'][0])
        self.assertNotIn('Bob draft', self.client.get('/api/posts').text)
        users = self.client.get('/api/admin/users', headers=self.headers('jackfei'))
        self.assertNotIn('password_hash', users.text)
        self.assertNotIn('$2b$', users.text)

    def test_user_and_category_crud_and_superadmin_protection(self):
        headers = self.headers('jackfei')
        new = self.client.post('/api/admin/users', headers=headers, json={'username': 'created', 'nickname': 'Created', 'password': 'created-test-pass'})
        self.assertEqual(new.status_code, 201, new.text)
        user_id = new.json()['id']
        self.assertEqual(self.client.put(f'/api/admin/users/{user_id}', headers=headers, json={'nickname': 'Changed'}).json()['nickname'], 'Changed')
        self.assertEqual(self.client.put(f'/api/admin/users/{user_id}', headers=headers, json={'username': 'jackfei', 'is_admin': True}).status_code, 422)
        self.assertEqual(self.client.request('DELETE', f"/api/admin/users/{self.ids['jackfei']}", headers=headers, json={'password': 'jackfei-test-pass'}).status_code, 409)
        self.assertEqual(self.client.request('DELETE', f'/api/admin/users/{user_id}', headers=headers, json={'password': 'jackfei-test-pass'}).status_code, 200)
        self.assertEqual(self.client.post('/api/admin/categories', headers=headers, json={'name': 'New'}).status_code, 201)
        self.assertEqual(self.client.put('/api/admin/categories/1', headers=headers, json={'name': 'Renamed'}).status_code, 200)
        self.assertEqual(self.client.delete('/api/admin/categories/1', headers=headers).status_code, 200)
        with self.sessions() as db:
            self.assertIsNone(db.get(models.Post, 1).category_id)

    def test_admin_study_edit_and_reset_are_isolated(self):
        headers = self.headers('jackfei')
        target = self.ids['alice']
        with self.sessions() as db:
            library = MusicList(user_id=target, kind='favorites', name='我喜欢')
            db.add(library); db.flush()
            db.add(MusicEntry(list_id=library.id, song_key='wy:123', song='{}')); db.commit()
        root = f'/api/admin/users/{target}/study'
        day = self.client.get(root + '/today', headers=headers).json()
        task = day['tasks'][0]
        updated = self.client.put(root + '/tasks/' + task['key'], headers=headers, json={'done': True, 'weak': True, 'note': 'admin correction'})
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertEqual(updated.json()['done'], 1)
        self.assertEqual(self.client.get('/api/study/today', headers=self.headers('bob')).json()['done'], 0)
        self.assertEqual(self.client.request('DELETE', root, headers=headers, json={'password': 'wrong'}).status_code, 403)
        self.assertEqual(self.client.request('DELETE', root, headers=headers, json={'password': 'jackfei-test-pass'}).status_code, 200)
        with self.sessions() as db:
            self.assertEqual(db.query(StudyDay).filter_by(user_id=target).count(), 0)
            self.assertEqual(db.query(StudyRound).filter_by(user_id=target).count(), 0)
            self.assertEqual(db.query(StudyDay).filter_by(user_id=self.ids['bob']).count(), 1)
            self.assertEqual(db.query(MusicList).filter_by(user_id=target).count(), 1)
            self.assertEqual(db.query(MusicEntry).count(), 1)

    def test_user_deletion_repairs_relations_counters_and_foreign_keys(self):
        # Alice owns article 1 and also interacts with Bob's article 2.
        target = self.ids['alice']; bob = self.ids['bob']
        self.client.get(f'/api/admin/users/{target}/study/today', headers=self.headers('jackfei'))
        with self.sessions() as db:
            library = MusicList(user_id=target, kind='favorites', name='我喜欢'); db.add(library); db.flush()
            db.add(MusicEntry(list_id=library.id, song_key='wy:123', song='{}'))
            db.add(models.Like(user_id=target, post_id=2)); db.add(models.Favorite(user_id=target, post_id=2))
            comment = models.Comment(user_id=target, post_id=2, content='parent'); db.add(comment); db.flush()
            db.add(models.Comment(user_id=bob, post_id=2, parent_id=comment.id, content='reply'))
            db.add(models.Follow(follower_id=target, followed_id=bob))
            db.add(models.Notification(user_id=bob, sender_id=target, post_id=2, type='comment'))
            db.add(models.VisitLog(user_id=target, ip='127.0.0.1'))
            db.get(models.Post, 2).like_count = 1; db.get(models.Post, 2).favorite_count = 1; db.get(models.Post, 2).comment_count = 2
            db.commit()
        response = self.client.request('DELETE', f'/api/admin/users/{target}', headers=self.headers('jackfei'), json={'password': 'jackfei-test-pass'})
        self.assertEqual(response.status_code, 200, response.text)
        with self.sessions() as db:
            self.assertIsNone(db.get(models.User, target)); self.assertIsNone(db.get(models.Post, 1))
            post = db.get(models.Post, 2)
            self.assertEqual((post.like_count, post.favorite_count, post.comment_count), (0, 0, 0))
            self.assertIsNone(db.query(models.VisitLog).one().user_id)
            self.assertEqual(db.query(StudyProgress).count(), 0)
            self.assertEqual(db.query(models.Notification).count(), 0)
            self.assertEqual(db.query(MusicList).filter_by(user_id=target).count(), 0)
            self.assertEqual(db.query(MusicEntry).count(), 0)

    def test_comments_private_drafts_and_admin_moderation(self):
        with self.sessions() as db:
            db.add(models.Comment(post_id=2, user_id=self.ids['bob'], content='private comment'))
            db.commit()
        self.assertEqual(self.client.get('/api/posts/2/comments').status_code, 404)
        self.assertEqual(self.client.get('/api/posts/2/comments', headers=self.headers('alice')).status_code, 404)
        self.assertEqual(self.client.post('/api/posts/2/comments', headers=self.headers('alice'), json={'content': 'intrusion'}).status_code, 404)
        self.assertEqual(self.client.get('/api/posts/2/comments', headers=self.headers('bob')).status_code, 200)
        headers = self.headers('jackfei')
        listing = self.client.get('/api/admin/comments', headers=headers)
        comment_id = listing.json()['items'][0]['id']
        self.assertEqual(self.client.put(f'/api/admin/comments/{comment_id}', headers=self.headers('alice'), json={'content': 'changed'}).status_code, 403)
        self.assertEqual(self.client.put(f'/api/admin/comments/{comment_id}', headers=headers, json={'content': 'managed'}).json()['content'], 'managed')
        self.assertEqual(self.client.delete(f'/api/comments/{comment_id}', headers=headers).status_code, 200)

    def test_jackfei_can_manage_bank_without_legacy_admin_flag(self):
        response = self.client.post('/api/study/bank', headers=self.headers('jackfei'), json={'kind': 'java', 'title': 'New question'})
        self.assertEqual(response.status_code, 200, response.text)

    def test_deleted_account_token_does_not_access_recreated_username(self):
        login = self.client.post('/api/auth/login', json={'username': 'bob', 'password': 'bob-test-pass'})
        self.assertEqual(login.status_code, 200)
        old_headers = {'Authorization': 'Bearer ' + login.json()['access_token']}
        self.assertEqual(self.client.get('/api/auth/me', headers=old_headers).status_code, 200)
        response = self.client.request('DELETE', f"/api/admin/users/{self.ids['bob']}", headers=self.headers('jackfei'), json={'password': 'jackfei-test-pass'})
        self.assertEqual(response.status_code, 200)
        response = self.client.post('/api/admin/users', headers=self.headers('jackfei'), json={'username': 'bob', 'password': 'new-bob-pass'})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(self.client.get('/api/auth/me', headers=old_headers).status_code, 401)
        self.assertEqual(self.client.post('/api/auth/login', json={'username': 'bob', 'password': 'new-bob-pass'}).status_code, 200)

    def test_legacy_tokens_work_only_for_original_account(self):
        from datetime import datetime, timedelta, timezone
        from jose import jwt
        with self.sessions() as db:
            user = db.get(models.User, self.ids['alice'])
            created = user.created_at.replace(tzinfo=timezone.utc).timestamp()
        valid = jwt.encode({'sub': 'alice', 'exp': int(created) + auth.TOKEN_EXPIRE_MINUTES * 60}, auth.SECRET_KEY, algorithm=auth.ALGORITHM)
        self.assertEqual(self.client.get('/api/auth/me', headers={'Authorization': 'Bearer ' + valid}).status_code, 200)
        with self.sessions() as db:
            db.get(models.User, self.ids['alice']).created_at = datetime.utcnow() + timedelta(seconds=5)
            db.commit()
        self.assertEqual(self.client.get('/api/auth/me', headers={'Authorization': 'Bearer ' + valid}).status_code, 401)
