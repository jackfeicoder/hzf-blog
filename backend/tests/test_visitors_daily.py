"""Daily deduplication against disposable databases only."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from starlette.requests import Request
from database import Base
import models
from routers import visitors


class VisitorDailyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.engine = create_engine('sqlite:///' + str(Path(self.temp.name) / 'visits.db'),
                                    connect_args={'check_same_thread': False, 'timeout': 10})
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine, autoflush=False)
        self.now = datetime(2026, 10, 15, 15, 59, 0)

    def tearDown(self):
        self.engine.dispose()
        self.temp.cleanup()

    def request(self, ip='192.0.2.1'):
        return Request({'type': 'http', 'method': 'GET', 'path': '/',
                        'headers': [(b'x-forwarded-for', ip.encode())],
                        'server': ('test', 80), 'scheme': 'http'})

    def record(self, ip='192.0.2.1', path='/post/1', user=None):
        with self.sessions() as db:
            visitors.record_visit(self.request(ip), db, user, path)

    def test_timezone_boundary(self):
        self.assertEqual(visitors.visit_day_start(self.now), datetime(2026, 10, 14, 16))
        self.assertEqual(visitors.visit_day_start(self.now + timedelta(minutes=1)), datetime(2026, 10, 15, 16))

    def test_same_ip_ignores_path_login_and_repeats_next_day(self):
        with patch.object(visitors, 'datetime') as clock:
            clock.utcnow.return_value = self.now
            self.record()
            self.record(path='/post/2')
            self.record(path='/visitors')
            self.record(ip='192.0.2.2')
            with self.sessions() as db:
                self.assertEqual(db.query(models.VisitLog).count(), 2)
            clock.utcnow.return_value = self.now + timedelta(minutes=2)
            self.record()
        with self.sessions() as db:
            self.assertEqual(db.query(models.VisitLog).count(), 3)
            self.assertEqual(db.query(models.VisitDay).count(), 3)

    def test_concurrent_requests_claim_one_row(self):
        with patch.object(visitors, 'datetime') as clock:
            clock.utcnow.return_value = self.now
            with ThreadPoolExecutor(max_workers=8) as pool:
                list(pool.map(lambda i: self.record(path=f'/post/{i}'), range(16)))
        with self.sessions() as db:
            self.assertEqual(db.query(models.VisitLog).count(), 1)
            self.assertEqual(db.query(models.VisitDay).count(), 1)

    def test_existing_today_log_is_preserved_without_new_duplicate(self):
        with self.sessions() as db:
            db.add(models.VisitLog(ip='192.0.2.1', path='/old', created_at=self.now - timedelta(hours=1)))
            db.commit()
        with patch.object(visitors, 'datetime') as clock:
            clock.utcnow.return_value = self.now
            self.record()
            self.record(path='/another')
        with self.sessions() as db:
            self.assertEqual(db.query(models.VisitLog).one().path, '/old')

    def test_duplicate_visit_does_not_rollback_article_view_changes(self):
        with patch.object(visitors, 'datetime') as clock:
            clock.utcnow.return_value = self.now
            self.record()
            with self.sessions() as db:
                user = models.User(username='reader', password_hash='unused')
                db.add(user)
                db.flush()
                post = models.Post(user_id=user.id, title='test', content='test', views=4)
                db.add(post)
                db.commit()
                post.views += 1
                visitors.record_visit(self.request(), db, user, '/post/1')
                db.commit()
            with self.sessions() as db:
                self.assertEqual(db.query(models.Post).one().views, 5)
                self.assertEqual(db.query(models.VisitLog).count(), 1)

    def test_seven_day_cleanup_retained(self):
        with self.sessions() as db:
            db.add(models.VisitLog(ip='192.0.2.9', created_at=self.now - timedelta(days=8)))
            db.add(models.VisitDay(ip='192.0.2.9', day_start=visitors.visit_day_start(self.now - timedelta(days=8))))
            db.commit()
        with patch.object(visitors, 'datetime') as clock:
            clock.utcnow.return_value = self.now
            self.record()
        with self.sessions() as db:
            self.assertEqual(db.query(models.VisitLog).one().ip, '192.0.2.1')
            self.assertEqual(db.query(models.VisitDay).one().ip, '192.0.2.1')

    def test_failed_commit_does_not_leave_an_orphan_daily_claim(self):
        with patch.object(visitors, 'datetime') as clock:
            clock.utcnow.return_value = self.now
            with self.sessions() as db:
                with patch.object(db, 'commit', side_effect=RuntimeError('fixture')):
                    visitors.record_visit(self.request(), db)
            with self.sessions() as db:
                self.assertEqual(db.query(models.VisitDay).count(), 0)
                self.assertEqual(db.query(models.VisitLog).count(), 0)
            self.record()
        with self.sessions() as db:
            self.assertEqual(db.query(models.VisitLog).count(), 1)
