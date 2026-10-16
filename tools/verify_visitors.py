"""Read-only production smoke checks; no account credentials or visitor data."""
import hashlib
import json
from pathlib import Path
import httpx

ROOT = Path('/www/wwwroot/blog.120115.xyz')
BASE = 'https://blog.120115.xyz:8443'
with httpx.Client(trust_env=False, timeout=30, follow_redirects=True) as client:
    health = client.get(BASE + '/api/health')
    assert health.status_code == 200 and health.json()['status'] == 'ok'
    for path in ('/api/visitors', '/api/visitors/'):
        for headers in ({}, {'Authorization': 'Bearer invalid'}):
            response = client.get(BASE + path, headers=headers)
            assert response.status_code == 401, (path, bool(headers), response.status_code, str(response.url), response.headers.get('server'), response.text[:200] if 'items' not in response.text else 'DATA PRESENT')
            assert 'items' not in response.text and 'total_visits' not in response.text
    page = client.get(BASE + '/visitors')
    assert page.status_code == 200
    assert page.content == (ROOT / 'frontend/dist/index.html').read_bytes()
    print(json.dumps({'health': 200, 'anonymous_visitor_api': 401,
                      'invalid_token': 401, 'latest_frontend': True,
                      'index_sha256': hashlib.sha256(page.content).hexdigest()}))
