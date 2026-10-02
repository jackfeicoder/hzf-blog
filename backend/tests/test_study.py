"""Run: python -m unittest discover -s tests -v (from backend)."""
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from auth import create_access_token
from database import Base, get_db
from models import Post, User
from routers import study
from study_models import StudyDay, StudyItem, StudyRound


class StudyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.engine = create_engine(f"sqlite:///{Path(self.temp.name) / 'study.db'}", connect_args={"check_same_thread": False})
        Base.metadata.create_all(self.engine)
        self.session = sessionmaker(bind=self.engine, autoflush=False)
        with self.session() as db:
            for name in ["admin", "alice", "bob"]:
                db.add(User(username=name, password_hash="unused", nickname=name, is_admin=name == "admin"))
            db.flush()
            db.add(Post(title="Java八股", content="# Java\n## 集合\n1. HashMap 如何扩容？\n参考答案\n2. ArrayList 如何扩容？\n第二答案", user_id=1, published=True))
            for kind, count in [("java", 8), ("hot100", 4), ("project", 3)]:
                for n in range(count):
                    db.add(StudyItem(kind=kind, title=f"{kind}-{n}", answer=f"answer-{n}", position=n, source_url="/post/1"))
            db.commit()
        self.app = FastAPI()
        self.app.include_router(study.router)

        def database_override():
            with self.session() as db:
                yield db

        self.app.dependency_overrides[get_db] = database_override
        self.client = TestClient(self.app)
        self.date = patch.object(study, "today", return_value="2026-09-30")
        self.clock = self.date.start()
        self.headers = {"Authorization": f"Bearer {create_access_token('alice')}"}
        self.admin = {"Authorization": f"Bearer {create_access_token('admin')}"}
        self.bob = {"Authorization": f"Bearer {create_access_token('bob')}"}

    def tearDown(self):
        self.date.stop()
        self.client.close()
        self.engine.dispose()
        self.temp.cleanup()

    def day(self, headers=None):
        response = self.client.get("/api/study/today", headers=headers or self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def update(self, task, **changes):
        response = self.client.put(f"/api/study/today/tasks/{task['key']}", headers=self.headers, json={"done": task["done"], "weak": task["weak"], "note": task["note"], **changes})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_auth_and_admin_access(self):
        self.assertEqual(self.client.get("/api/study/today").status_code, 401)
        self.assertEqual(self.client.get("/api/study/bank", headers=self.headers).status_code, 403)
        self.assertEqual(self.client.get("/api/study/bank", headers=self.admin).status_code, 200)

    def test_daily_limits_and_no_cache(self):
        day = self.day()
        self.assertEqual(day["total"], 8)
        self.assertEqual([sum(t["kind"] == k for t in day["tasks"]) for k in study.LIMITS], [5, 2, 1])
        self.assertEqual(self.day(), day)
        response = self.client.get("/api/study/today", headers=self.headers)
        self.assertEqual(response.headers["cache-control"], "private, no-store")

    def test_account_isolation_and_undo(self):
        task = self.day()["tasks"][0]
        self.update(task, done=True, note="private", weak=True)
        bob = self.day(self.bob)
        self.assertEqual(bob["done"], 0)
        self.assertFalse(any(t["note"] == "private" for t in bob["tasks"]))
        response = self.client.put(f"/api/study/today/tasks/{task['key']}", headers=self.bob, json={"done": True})
        self.assertEqual(response.status_code, 404)
        saved = self.day()["tasks"][0]
        self.assertTrue(saved["done"])
        self.assertEqual(self.update(saved, done=False)["done"], 0)

    def test_unfinished_tasks_carry_forward_without_skipping_days(self):
        day = self.day()
        self.update(day["tasks"][0], done=True)
        self.clock.return_value = "2026-10-04"
        next_day = self.day()
        java = [t for t in next_day["tasks"] if t["kind"] == "java"]
        self.assertEqual([t["title"] for t in java], [f"java-{n}" for n in range(1, 6)])
        self.assertEqual(next_day["done"], 0)

    def test_bank_edits_preserve_today_and_history(self):
        old = self.day()
        item = self.client.get("/api/study/bank", headers=self.admin).json()[0]
        response = self.client.put(f"/api/study/bank/{item['id']}", headers=self.admin, json={**item, "title": "new title", "answer": "new answer"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.day(), old)
        self.clock.return_value = "2026-10-01"
        self.assertTrue(any(t["title"] == "new title" for t in self.day()["tasks"]))
        history = self.client.get("/api/study/history?month=2026-09", headers=self.headers).json()
        self.assertEqual(history[0], old)
        self.assertEqual(self.client.get("/api/study/history?month=2026-09", headers=self.bob).json(), [])

    def test_added_items_join_open_round_next_day(self):
        old = self.day()
        response = self.client.post("/api/study/bank", headers=self.admin, json={"kind": "java", "title": "new question", "position": 0})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.day(), old)
        self.clock.return_value = "2026-10-01"
        self.assertTrue(any(t["title"] == "new question" for t in self.day()["tasks"]))

    def finish_hot100(self):
        first = self.day()
        for t in first["tasks"]:
            if t["kind"] == "hot100":
                self.update(t, done=True, weak=t["title"] == "hot100-0")
        self.clock.return_value = "2026-10-01"
        for t in self.day()["tasks"]:
            if t["kind"] == "hot100":
                self.update(t, done=True)

    def test_complete_round_review_and_archive(self):
        self.finish_hot100()
        progress = self.client.get("/api/study/progress", headers=self.headers).json()
        hot = next(r for r in progress if r["kind"] == "hot100")
        self.assertTrue(hot["finished"])
        self.assertEqual(hot["done"], 4)
        today = self.day()
        response = self.client.post("/api/study/rounds/hot100/next", headers=self.headers, json={"mode": "all"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.day(), today)
        old_task = next(t for t in today["tasks"] if t["kind"] == "hot100")
        response = self.client.put(f"/api/study/today/tasks/{old_task['key']}", headers=self.headers, json={"done": False})
        self.assertEqual(response.status_code, 409)
        self.clock.return_value = "2026-10-02"
        hot_tasks = [t for t in self.day()["tasks"] if t["kind"] == "hot100"]
        self.assertEqual(len(hot_tasks), 2)
        self.assertEqual(hot_tasks[0]["round"], 2)
        self.assertFalse(hot_tasks[0]["done"])

    def test_weak_review_counts_only_selected(self):
        self.finish_hot100()
        response = self.client.post("/api/study/rounds/hot100/next", headers=self.headers, json={"mode": "weak"})
        self.assertEqual(response.status_code, 200)
        self.clock.return_value = "2026-10-02"
        hot = [t for t in self.day()["tasks"] if t["kind"] == "hot100"]
        self.assertEqual([t["title"] for t in hot], ["hot100-0"])
        self.update(hot[0], done=True)
        progress = self.client.get("/api/study/progress", headers=self.headers).json()
        latest = next(r for r in progress if r["kind"] == "hot100")
        self.assertEqual((latest["done"], latest["total"], latest["finished"]), (1, 1, True))

    def test_incomplete_round_rejected(self):
        self.day()
        response = self.client.post("/api/study/rounds/java/next", headers=self.headers, json={"mode": "all"})
        self.assertEqual(response.status_code, 409)

    def test_article_preview_and_idempotent_import(self):
        response = self.client.post("/api/study/bank/preview", headers=self.admin, json={"kind": "java", "post_id": 1})
        candidates = response.json()["items"]
        self.assertEqual(len(candidates), 2)
        self.assertIn("参考答案", candidates[0]["answer"])
        for expected in [2, 0]:
            response = self.client.post("/api/study/bank/import", headers=self.admin, json={"items": candidates})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["added"], expected)

    def test_fenced_numbers_are_not_questions(self):
        items = study.parse_article("# 集合\n1. 真正的问题\n```\n2. 示例数字\n```\n回答", "java", 1)
        self.assertEqual(len(items), 1)
        self.assertIn("2. 示例数字", items[0]["answer"])

    def test_deactivate_preserves_frozen_task(self):
        day = self.day()
        with self.session() as db:
            db.query(StudyItem).filter_by(kind="java", title="java-0").update({"active": False})
            db.commit()
        self.assertEqual(self.day(), day)
        self.update(day["tasks"][0], done=True)
        self.clock.return_value = "2026-10-01"
        self.assertFalse(any(t["title"] == "java-0" for t in self.day()["tasks"]))

    def test_empty_bank_has_reading_checkboxes(self):
        with self.session() as db:
            db.query(StudyItem).filter_by(kind="hot100").delete()
            db.commit()
        hot = [t for t in self.day()["tasks"] if t["kind"] == "hot100"]
        self.assertEqual(len(hot), 2)
        self.assertEqual(hot[0]["source_url"], "/post/5")
        self.update(hot[0], done=True)

    def test_input_validation(self):
        for body in [{"kind": "java", "title": " "}, {"kind": "java", "title": "question", "source_url": "javascript:alert(1)"}]:
            self.assertEqual(self.client.post("/api/study/bank", headers=self.admin, json=body).status_code, 422)
        self.assertEqual(self.client.get("/api/study/history?month=2026-13", headers=self.headers).status_code, 400)

    def test_parallel_today_creates_one_snapshot(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            responses = list(pool.map(lambda _: self.client.get("/api/study/today", headers=self.headers), range(4)))
        self.assertTrue(all(r.status_code == 200 for r in responses), [r.text for r in responses])
        self.assertTrue(all(r.json() == responses[0].json() for r in responses))
        with self.session() as db:
            self.assertEqual(db.query(StudyDay).count(), 1)
            self.assertEqual(db.query(StudyRound).count(), 3)

    def test_parallel_updates_do_not_lose_checkmarks(self):
        tasks = self.day()["tasks"][:2]

        def save(task):
            return self.client.put(f"/api/study/today/tasks/{task['key']}", headers=self.headers, json={"done": True})

        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(save, tasks))
        for task, response in zip(tasks, responses):
            self.assertIn(response.status_code, [200, 409], response.text)
            if response.status_code == 409:
                self.assertEqual(save(task).status_code, 200)
        self.assertEqual(self.day()["done"], 2)


if __name__ == "__main__":
    unittest.main()
