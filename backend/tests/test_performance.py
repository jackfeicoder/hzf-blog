import unittest
from sqlalchemy import event
from routers import posts, users
from models import Favorite, Post
import test_study


class PerformanceTests(unittest.TestCase):
    # Reuse an isolated DB/auth fixture, not the production database.
    def setUp(self):
        test_study.StudyTests.setUp(self)
        self.app.include_router(posts.router)
        self.app.include_router(users.router)
        with self.session() as db:
            db.add(Post(title='Private draft', content='secret body', summary='draft', user_id=2, published=False))
            db.add(Favorite(user_id=2, post_id=1))
            db.commit()

    def tearDown(self):
        test_study.StudyTests.tearDown(self)

    def test_lists_do_not_fetch_body_and_preserve_privacy(self):
        statements = []
        def record(conn, cursor, statement, parameters, context, executemany):
            statements.append(statement)
        event.listen(self.engine, 'before_cursor_execute', record)
        try:
            for path in ['/api/posts?page=1&page_size=10', '/api/rankings/posts?limit=8', '/api/users/alice/favorites']:
                statements.clear()
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200, response.text)
                body_fetches = [s for s in statements if 'posts.content' in s and s.lstrip().upper().startswith('SELECT')]
                self.assertEqual(body_fetches, [])
                self.assertNotIn('secret body', response.text)
                self.assertNotIn('Private draft', response.text)
            response = self.client.get('/api/posts?author=alice', headers=self.headers)
            self.assertIn('Private draft', response.text)
            detail = self.client.get('/api/posts/1?inc_view=false')
            self.assertEqual(detail.status_code, 200)
            self.assertIn('content', detail.json())
        finally:
            event.remove(self.engine, 'before_cursor_execute', record)
