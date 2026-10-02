"""Isolated public-directory CRUD and access-control regression checks."""
import tempfile
import unittest
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from auth import create_access_token
from database import Base, get_db
from models import User
from routers import media


class MediaTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.engine = create_engine(f"sqlite:///{Path(self.temp.name) / 'media.db'}", connect_args={"check_same_thread": False})
        Base.metadata.create_all(self.engine)
        self.session = sessionmaker(bind=self.engine)
        with self.session() as db:
            for name in ("jackfei", "alice", "other-admin"):
                db.add(User(username=name, nickname=name, password_hash="unused", is_admin=name != "alice"))
            db.commit()
        app = FastAPI()
        app.include_router(media.router)

        def database_override():
            with self.session() as db:
                yield db

        app.dependency_overrides[get_db] = database_override
        self.client = TestClient(app)
        self.admin = {"Authorization": f"Bearer {create_access_token('jackfei')}"}
        self.payload = {"title": "Example", "url": "https://example.com/watch?a=1", "description": "简介", "position": 2}

    def tearDown(self):
        self.client.close()
        self.engine.dispose()
        self.temp.cleanup()

    def test_public_read_admin_crud_persists_and_orders(self):
        self.assertEqual(self.client.get("/api/media/videos").json(), [])
        created = self.client.post("/api/media/videos", json=self.payload, headers=self.admin)
        self.assertEqual(created.status_code, 201, created.text)
        row = created.json()
        earlier = self.client.post("/api/media/videos", json={**self.payload, "title": "First", "position": 0}, headers=self.admin).json()
        listing = self.client.get("/api/media/videos")
        self.assertEqual([v["id"] for v in listing.json()], [earlier["id"], row["id"]])
        self.assertEqual(listing.headers["cache-control"], "no-store")
        changed = {**self.payload, "title": "Updated", "position": 0}
        self.assertEqual(self.client.put(f"/api/media/videos/{row['id']}", json=changed, headers=self.admin).status_code, 200)
        self.assertEqual(self.client.get("/api/media/videos").json()[0]["title"], "Updated")
        self.assertEqual(self.client.delete(f"/api/media/videos/{row['id']}", headers=self.admin).status_code, 204)
        self.assertEqual(len(self.client.get("/api/media/videos").json()), 1)
        self.assertEqual(self.client.delete(f"/api/media/videos/{row['id']}", headers=self.admin).status_code, 404)

    def test_only_jackfei_can_mutate_even_when_another_user_is_admin(self):
        row = self.client.post("/api/media/videos", json=self.payload, headers=self.admin).json()
        for name, status in ((None, 401), ("alice", 403), ("other-admin", 403)):
            headers = {"Authorization": f"Bearer {create_access_token(name)}"} if name else {}
            for method, path in (("POST", ""), ("PUT", f"/{row['id']}"), ("DELETE", f"/{row['id']}")):
                response = self.client.request(method, f"/api/media/videos{path}", headers=headers, **({"json": self.payload} if method != "DELETE" else {}))
                self.assertEqual(response.status_code, status, response.text)
        self.assertEqual(len(self.client.get("/api/media/videos").json()), 1)

    def test_rejects_unsafe_or_invalid_links_and_blank_titles(self):
        for url in ("javascript:alert(1)", "data:text/html,hi", "//example.com", "https://", "https://user:pass@example.com", "https://example.com:wrong", "https://example.com/a b", "https://example.com\\evil"):
            response = self.client.post("/api/media/videos", json={**self.payload, "url": url}, headers=self.admin)
            self.assertEqual(response.status_code, 422, url)
        for changes in ({"title": "   "}, {"position": -1}, {"is_admin": True}):
            self.assertEqual(self.client.post("/api/media/videos", json={**self.payload, **changes}, headers=self.admin).status_code, 422)
        self.assertEqual(self.client.get("/api/media/videos").json(), [])
