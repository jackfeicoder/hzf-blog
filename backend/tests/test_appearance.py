"""Global appearance tests use a disposable database, never production data."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from auth import create_access_token
from database import Base, get_db
from models import User, UserAppearance, SiteAppearance
from routers.appearance import router


class AppearanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.engine = create_engine(f"sqlite:///{Path(self.temp.name) / 'test.db'}", connect_args={"check_same_thread": False})
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine)
        with self.sessions() as db:
            db.add_all([User(username='jackfei', password_hash='hidden', is_admin=True),
                        User(username='alice', password_hash='hidden'),
                        User(username='bob', password_hash='hidden', is_admin=True)])
            db.commit()
        app = FastAPI()
        app.include_router(router)
        def database():
            with self.sessions() as db:
                yield db
        app.dependency_overrides[get_db] = database
        self.client = TestClient(app)
        self.env = patch.dict(os.environ, {'R2_PUBLIC_BASE_URL': 'https://img.example.test'})
        self.env.start()

    def tearDown(self):
        self.client.close()
        self.env.stop()
        self.engine.dispose()
        self.temp.cleanup()

    def headers(self, user='jackfei'):
        return {'Authorization': 'Bearer ' + create_access_token(user)}

    def publish(self, body):
        return self.client.put('/api/appearance', headers=self.headers(), json={**body, 'scope':'site'})

    def test_public_defaults_and_get_no_write(self):
        response = self.client.get('/api/appearance')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['click_effect'], 'ripple')
        self.assertEqual(response.json()['glass_transparency'], 11)
        self.assertEqual(response.headers['cache-control'], 'no-store')
        with self.sessions() as db:
            self.assertEqual(db.query(SiteAppearance).count(), 0)

    def test_only_designated_administrator_can_publish(self):
        self.assertEqual(self.client.put('/api/appearance', json={}).status_code, 401)
        for name in ('alice', 'bob'):
            denied = self.client.put('/api/appearance', headers=self.headers(name), json={'palette':'ocean'})
            self.assertEqual(denied.status_code, 403)
        self.assertEqual(self.client.get('/api/appearance').json()['palette'], 'warm')
        with self.sessions() as db:
            self.assertEqual(db.query(SiteAppearance).count(), 0)

    def test_admin_publish_visible_to_everyone_and_singleton(self):
        body = {'palette':'ocean', 'theme':'dark', 'motion':False, 'glass_transparency':47}
        response = self.publish(body)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.headers['cache-control'], 'private, no-store')
        for headers in ({}, self.headers('alice'), self.headers('bob'), {'Authorization':'Bearer invalid'}):
            self.assertEqual(self.client.get('/api/appearance', headers=headers).json(), response.json())
        self.assertNotIn('user_id', response.json())
        self.assertNotIn('username', response.json())
        self.publish({'glass_transparency':80})
        with self.sessions() as db:
            self.assertEqual(db.query(SiteAppearance).count(), 1)
            self.assertEqual(db.get(SiteAppearance, 1).glass_transparency, 80)

    def test_legacy_admin_style_fallback_preserves_personal_rows(self):
        with self.sessions() as db:
            admin = db.query(User).filter_by(username='jackfei').one()
            alice = db.query(User).filter_by(username='alice').one()
            alice_id = alice.id
            db.add_all([UserAppearance(user_id=admin.id, palette='forest', theme='system'),
                        UserAppearance(user_id=alice.id, palette='violet', theme='dark')])
            db.commit()
        public = self.client.get('/api/appearance').json()
        self.assertEqual(public['palette'], 'forest')
        self.assertEqual(public['theme'], 'light')
        self.assertEqual(self.client.get('/api/appearance', headers=self.headers('alice')).json(), public)
        self.publish({'palette':'ocean'})
        self.assertEqual(self.client.get('/api/appearance').json()['palette'], 'ocean')
        with self.sessions() as db:
            self.assertEqual(db.query(UserAppearance).count(), 2)
            self.assertEqual(db.get(UserAppearance, alice_id).palette, 'violet')

    def test_validation_and_no_owner_or_css_injection(self):
        invalid = ({'user_id':2}, {'id':2}, {'palette':'evil'}, {'background':'custom'},
                   {'theme':'system'}, {'glass_transparency':-1}, {'glass_transparency':81},
                   {'glass_transparency':30.5}, {'glass_transparency':'30'}, {'glass_transparency':True},
                   {'background_url':'javascript:alert(1)'},
                   {'background_url':'https://other.example/images/202610/'+'a'*32+'.webp'},
                   {'background_url':'https://img.example.test/images/202610/'+'a'*32+'.webp?track=1'},
                   {'background_url':'/uploads/images/../../secret.png'})
        for body in invalid:
            with self.subTest(body=body):
                self.assertEqual(self.publish(body).status_code, 422)
        with self.sessions() as db:
            self.assertEqual(db.query(SiteAppearance).count(), 0)

    def test_uploaded_background_and_reset(self):
        for url in ('/uploads/images/202610/'+'a'*32+'.webp', 'https://img.example.test/images/202610/'+'b'*32+'.webp'):
            response = self.publish({'background':'custom','background_url':url,'glass_transparency':0})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(self.client.get('/api/appearance').json()['background_url'], url)
        reset = self.publish({}).json()
        self.assertEqual(reset['background_url'], '')
        self.assertEqual(reset['glass_transparency'], 11)

    def test_legacy_admin_autosave_cannot_overwrite_global_style(self):
        self.publish({'palette':'ocean', 'glass_transparency':35})
        old = self.client.put('/api/appearance', headers=self.headers(), json={'palette':'forest','theme':'dark'})
        self.assertEqual(old.status_code, 422)
        self.assertEqual(self.client.get('/api/appearance').json()['palette'], 'ocean')
