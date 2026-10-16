"""Provider/stream/security regression checks without live network or DB."""
import asyncio
import json
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from auth import get_current_user_optional
import chat_limits
import sensenova_catalog as catalog
from routers import chat

REAL_CLIENT = httpx.AsyncClient


class ChatAdaptationTests(unittest.TestCase):
    def setUp(self):
        self.old_catalog = dict(catalog._state)
        catalog._state.update(models=list(catalog.FALLBACK_MODELS), source='official', next_refresh=time.monotonic()+300)
        with chat_limits._lock:
            chat_limits._users.clear(); chat_limits._global.clear(); chat_limits._active.clear()
        self.user = SimpleNamespace(id=77)
        app = FastAPI()
        app.include_router(chat.router)
        app.dependency_overrides[get_current_user_optional] = lambda: self.user
        self.client = TestClient(app)
        self.key_patch = patch.object(chat, 'DEFAULT_FREE_KEY', 'fixture-site-key')
        self.key_patch.start()
        self.calls = []
        self.status = 200
        self.error = ''
        self.factory = patch.object(chat.httpx, 'AsyncClient', side_effect=lambda **kw:
            REAL_CLIENT(transport=httpx.MockTransport(self.upstream), **kw))
        self.factory.start()

    def tearDown(self):
        self.client.close(); self.factory.stop(); self.key_patch.stop()
        catalog._state.clear(); catalog._state.update(self.old_catalog)

    def upstream(self, request):
        payload = json.loads(request.content)
        self.calls.append((request, payload))
        if self.status != 200:
            return httpx.Response(self.status, text=self.error)
        if payload['stream']:
            return httpx.Response(200, text='data:{"choices":[{"delta":{"content":"连接"}}]}\n\ndata: {"choices":[{"delta":{"content":"成功"}}]}\n\ndata:[DONE]\n\n')
        return httpx.Response(200, json={'model': payload['model'], 'choices': [{'message': {'content': '连接成功'}}]})

    def send(self, stream=False, **changes):
        body = dict(provider='sensenova', messages=[{'role': 'user', 'content': 'hello'}])
        body.update(changes)
        return self.client.post('/api/chat/stream' if stream else '/api/chat', json=body)

    def test_default_and_retired_id_migrate_for_both_routes(self):
        for stream in (False, True):
            for model in ('', 'Nova-5-Pro', 'sensenova-6.7-flash-lite'):
                response = self.send(stream, model=model)
                self.assertEqual(response.status_code, 200, response.text)
                self.assertIn('成功', response.text)
                self.assertEqual(self.calls[-1][1]['model'], catalog.DEFAULT_MODEL)
                self.assertEqual(self.calls[-1][1]['reasoning_effort'], 'none')
        self.assertFalse(chat_limits._active)

    def test_shared_key_requires_user_and_official_origin(self):
        self.user = None
        self.assertEqual(self.send().status_code, 401)
        self.user = SimpleNamespace(id=77)
        for base in ('https://example.test', 'http://127.0.0.1', 'https://token.sensenova.cn@evil.test'):
            self.assertEqual(self.send(base_url=base).status_code, 400)
        self.assertFalse(self.calls)

    def test_user_key_is_never_replaced_and_custom_cannot_use_site_key(self):
        self.user = None
        response = self.send(api_key=' fixture-personal-key ')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.calls[-1][0].headers['Authorization'], 'Bearer fixture-personal-key')
        self.assertEqual(self.send(provider='custom', base_url='https://example.test').status_code, 400)

    def test_kimi_parameters_and_site_output_budget(self):
        response = self.send(model='kimi-k3', max_tokens=8192, reasoning_effort='high')
        self.assertEqual(response.status_code, 200)
        payload = self.calls[-1][1]
        self.assertEqual(payload['max_completion_tokens'], 4096)
        self.assertNotIn('max_tokens', payload)
        self.assertNotIn('temperature', payload)
        self.assertEqual(payload['reasoning_effort'], 'high')

    def test_shared_model_and_input_restrictions(self):
        self.assertEqual(self.send(model='sensenova-u1.5-lite').status_code, 400)
        self.assertEqual(self.send(model='deepseek-v4.1-flash').status_code, 400)
        self.assertEqual(self.send(messages=[{'role': 'user', 'content': 'x'*40001}]).status_code, 400)
        self.assertFalse(self.calls)

    def test_error_classification_redaction_and_stream_cleanup(self):
        for status in (401, 403, 429, 500):
            self.status = status
            self.error = 'upstream fixture-site-key sk-fixtureShouldBeRedacted'
            for stream in (False, True):
                response = self.send(stream)
                self.assertNotIn('fixture-site-key', response.text)
                self.assertNotIn('sk-fixtureShouldBeRedacted', response.text)
                self.assertIn(str(status), response.text)
                self.assertFalse(chat_limits._active)
                if not stream:
                    self.assertEqual(response.status_code, 502 if status == 500 else status)

    def test_per_user_quota_both_routes_and_no_upstream_after_limit(self):
        for _ in range(10):
            self.assertEqual(self.send().status_code, 200)
        self.assertEqual(self.send(True).status_code, 429)
        self.assertEqual(len(self.calls), 10)

    def test_public_metadata_contains_no_key_and_latest_default(self):
        response = self.client.get('/api/chat/providers')
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('fixture-site-key', response.text)
        info = response.json()['providers'][0]
        self.assertTrue(info['requires_login'])
        self.assertEqual(info['default_model'], catalog.DEFAULT_MODEL)
        self.assertNotIn('sensenova-6.7-flash-lite', info['models'])

    def test_late_cleanup_does_not_release_another_request(self):
        lease = chat_limits.reserve(17)
        with self.assertRaises(Exception): chat_limits.reserve(17)
        chat_limits.release(17, lease)
        next_lease = chat_limits.reserve(17)
        chat_limits.release(17, lease)
        self.assertIn(17, chat_limits._active)
        chat_limits.release(17, next_lease)


class CatalogTests(unittest.IsolatedAsyncioTestCase):
    async def test_filter_refresh_single_flight_and_network_fallback(self):
        before = dict(catalog._state)
        catalog._state.update(models=list(catalog.FALLBACK_MODELS), source='fallback', next_refresh=0)
        calls = []
        rows = [dict(id='kimi-k3', output_modalities=['text'], pricing={'prompt':'0', 'completion':'0'}),
                dict(id='unselected-model', output_modalities=['text'], pricing={'prompt':'0'}),
                dict(id='paid', output_modalities=['text'], pricing={'prompt':'1'}),
                dict(id='picture', output_modalities=['image'], pricing={'prompt':'0'}),
                dict(id='unknown-price', output_modalities=['text']),
                dict(id=catalog.DEFAULT_MODEL, output_modalities=['text'], pricing={'prompt':'0'})]
        async def upstream(request):
            calls.append(request)
            await asyncio.sleep(0)
            return httpx.Response(200, json={'data': rows})
        try:
            with patch.object(catalog, '_lock', asyncio.Lock()), patch.object(catalog.httpx, 'AsyncClient',
                side_effect=lambda **kw: REAL_CLIENT(transport=httpx.MockTransport(upstream), **kw)):
                results = await asyncio.gather(*[catalog.catalog('fixture') for _ in range(4)])
                self.assertEqual(len(calls), 1)
                self.assertTrue(all(r[0] == [catalog.DEFAULT_MODEL, 'kimi-k3'] for r in results))
                catalog._state['next_refresh'] = 0
                with patch.object(catalog.httpx, 'AsyncClient', side_effect=httpx.ConnectError('fixture failure')):
                    models, source = await catalog.catalog('fixture')
                    self.assertEqual(models, [catalog.DEFAULT_MODEL, 'kimi-k3'])
                    self.assertEqual(source, 'cached')
                    self.assertGreater(catalog._state['next_refresh'], time.monotonic())
        finally:
            catalog._state.clear(); catalog._state.update(before)
