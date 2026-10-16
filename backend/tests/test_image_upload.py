"""Disposable DB/disk and mocked S3 only; never writes a real account."""
import asyncio
import io
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch, Mock

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from auth import create_access_token
from database import Base, get_db
import image_storage as storage
from image_static import ImageStaticFiles
from models import User
from routers import upload


def picture(size=(32, 24), format="PNG"):
    out = io.BytesIO()
    Image.new("RGB", size, "#e55132").save(out, format=format)
    return out.getvalue()


class ImageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.engine = create_engine(f"sqlite:///{root / 'test.db'}", connect_args={"check_same_thread": False})
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine)
        with self.sessions() as db:
            db.add_all([User(username="alice", nickname="Alice", password_hash="hidden-hash"),
                        User(username="bob", nickname="Bob", password_hash="hidden-hash")])
            db.commit()
        self.app = FastAPI()
        self.app.include_router(upload.router)
        @self.app.get("/health")
        async def health():
            return {"ok": True}
        def database():
            with self.sessions() as db:
                yield db
        self.app.dependency_overrides[get_db] = database
        self.disk = root / "uploads"
        self.disk.mkdir()
        self.app.mount("/uploads", ImageStaticFiles(directory=self.disk))
        self.client = TestClient(self.app)
        self.headers = {"Authorization": "Bearer " + create_access_token("alice")}
        self.env = patch.dict(os.environ, {"IMAGE_STORAGE": "local"})
        self.env.start()
        self.paths = patch.object(storage, "UPLOAD_DIR", self.disk)
        self.paths.start()
        storage._attempts.clear()

    def tearDown(self):
        self.client.close()
        self.env.stop()
        self.paths.stop()
        self.engine.dispose()
        self.temp.cleanup()

    def send(self, body=None, path="image", headers=None, filename="fixture.png"):
        return self.client.post(f"/api/upload/{path}", headers=self.headers if headers is None else headers,
                                files={"file": (filename, picture() if body is None else body, "image/png")})

    def test_auth_real_content_size_and_filename_independence(self):
        for kind in ("image", "avatar"):
            self.assertEqual(self.send(path=kind, headers={}).status_code, 401)
        for body, status in [(b"", 400), (b"<svg onload='evil'>", 400),
                             (b"x" * (storage.MAX_FILE_SIZE + 1), 413), (picture()[:40], 400)]:
            self.assertEqual(self.send(body=body).status_code, status)
        valid = self.send(filename="../../not-a-picture.exe")
        self.assertEqual(valid.status_code, 200, valid.text)
        self.assertTrue(valid.json()["url"].endswith(".webp"))
        self.assertNotIn("..", valid.json()["url"])

    def test_static_cache_unique_url_and_avatar_private_response(self):
        first = self.send().json()
        second = self.send().json()
        self.assertNotEqual(first["url"], second["url"])
        public = self.client.get(first["url"])
        self.assertEqual(public.headers["cache-control"], storage.CACHE_CONTROL)
        self.assertEqual(public.headers["x-content-type-options"], "nosniff")
        self.assertEqual(self.client.get(first["url"], headers={"If-None-Match": public.headers["etag"]}).status_code, 304)
        avatar = self.send(path="avatar")
        self.assertEqual(avatar.status_code, 200, avatar.text)
        self.assertEqual(avatar.headers["cache-control"], "private, no-store")
        self.assertNotIn("password_hash", avatar.text)
        self.assertNotIn("hidden-hash", avatar.text)
        with self.sessions() as db:
            self.assertEqual(db.query(User).filter_by(username="alice").one().avatar_url, avatar.json()["url"])
            self.assertFalse(db.query(User).filter_by(username="bob").one().avatar_url)

    def test_resize_and_frame_validation(self):
        body, ext, mime, size = storage.normalize_image(picture((2000, 1000)), "avatars")
        self.assertEqual((size, ext, mime), ((512, 256), "webp", "image/webp"))
        Image.open(io.BytesIO(body)).verify()
        with self.assertRaises(HTTPException):
            storage.normalize_image(picture((4100, 4000)), "images")
        out = io.BytesIO()
        Image.new("RGB", (12, 10), "red").save(out, "GIF", save_all=True,
            append_images=[Image.new("RGB", (12, 10), "blue")], duration=100, loop=0)
        result = storage.normalize_image(out.getvalue(), "images")
        self.assertEqual((result[1], result[2]), ("gif", "image/gif"))
        self.assertEqual(Image.open(io.BytesIO(result[0])).n_frames, 2)

    def test_r2_cache_and_failure_preserves_avatar_without_local_fallback(self):
        env = {"IMAGE_STORAGE": "r2", "R2_ACCOUNT_ID": "a" * 32, "R2_BUCKET": "fixture",
               "R2_ACCESS_KEY_ID": "fixture-id", "R2_SECRET_ACCESS_KEY": "fixture-secret",
               "R2_PUBLIC_BASE_URL": "https://img.example.com"}
        client = Mock()
        with patch.dict(os.environ, env), patch.object(storage, "r2_client", return_value=client):
            result = self.send().json()
            self.assertTrue(result["url"].startswith("https://img.example.com/images/"))
            args = client.put_object.call_args.kwargs
            self.assertEqual(args["CacheControl"], storage.CACHE_CONTROL)
            self.assertEqual(args["ContentType"], "image/webp")
            client.put_object.side_effect = RuntimeError("fixture-secret signed-sensitive-request")
            failed = self.send(path="avatar")
            self.assertEqual(failed.status_code, 502)
            self.assertNotIn("fixture-secret", failed.text)
            self.assertFalse(list(self.disk.rglob("*.webp")))
            with self.sessions() as db:
                self.assertFalse(db.query(User).filter_by(username="alice").one().avatar_url)
            with patch.dict(os.environ, {"R2_PUBLIC_BASE_URL": "http://wrong.example"}):
                self.assertEqual(self.send().status_code, 503)

    def test_throttle_and_parallel_cap(self):
        with self.sessions() as db:
            user_id = db.query(User).filter_by(username="alice").one().id
        storage._attempts[user_id] = (time.monotonic(), 20)
        self.assertEqual(self.send().status_code, 429)
        storage._attempts.clear()
        for _ in range(3):
            storage._upload_slots.acquire()
        try:
            self.assertEqual(self.send().status_code, 503)
        finally:
            for _ in range(3):
                storage._upload_slots.release()

    def test_slow_storage_does_not_block_unrelated_async_request(self):
        async def scenario():
            transport = httpx.ASGITransport(app=self.app)
            async with httpx.AsyncClient(transport=transport, base_url="http://fixture") as client:
                def slow(*args):
                    time.sleep(0.3)
                    return {"url": "https://img.example/fixture.webp", "width": 1, "height": 1, "bytes": 10}
                with patch.object(upload, "store_image", side_effect=slow):
                    task = asyncio.create_task(client.post("/api/upload/image", headers=self.headers,
                        files={"file": ("a.png", picture(), "image/png")}))
                    await asyncio.sleep(0.05)
                    response = await client.get("/health")
                    self.assertEqual(response.status_code, 200)
                    self.assertFalse(task.done(), "Storage blocked the application event loop")
                    self.assertEqual((await task).status_code, 200)
        asyncio.run(scenario())
