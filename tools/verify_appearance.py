"""Public-only production smoke checks. No environment/credential access."""
import hashlib
import json
from pathlib import Path
import httpx

ROOT = Path('/www/wwwroot/blog.120115.xyz')
with httpx.Client(trust_env=False,timeout=30,headers={'User-Agent':'Mozilla/5.0'}) as client:
    website = {}
    for path in ('/','/music','/api/health','/api/posts?page=1&page_size=1'):
        response = client.get('https://blog.120115.xyz:8443'+path)
        assert response.status_code == 200, (path,response.status_code)
        website[path] = response.status_code
        if path == '/':
            expected = (ROOT / 'frontend/dist/index.html').read_bytes()
            assert response.content == expected, 'Public index is not the new release'
    anonymous = client.get('https://blog.120115.xyz:8443/api/appearance')
    assert anonymous.status_code == 200
    assert 0 <= anonymous.json()['glass_transparency'] <= 80
    assert anonymous.headers['cache-control'] == 'no-store'
    denied = client.put('https://blog.120115.xyz:8443/api/appearance', json={})
    assert denied.status_code == 401
print(json.dumps({'website':website,'anonymous_preferences':200,'anonymous_write':401,
    'verification_mode':'public-only; administrator permissions covered by disposable-DB tests',
    'index_sha256':hashlib.sha256(expected).hexdigest()}))
