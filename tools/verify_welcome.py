"""Read-only production smoke checks; no account or credential operations."""
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import httpx

ROOT = Path('/www/wwwroot/blog.120115.xyz')
BASE = 'https://blog.120115.xyz:8443'
expected = (ROOT / 'frontend/dist/index.html').read_bytes()
with httpx.Client(trust_env=False, timeout=30,
                  headers={'User-Agent': 'Mozilla/5.0'}) as client:
    pages = {}
    for path in ('/', '/welcome', '/about', '/register', '/music', '/api/health'):
        response = client.get(BASE + path)
        assert response.status_code == 200, (path, response.status_code)
        pages[path] = response.status_code
        if path != '/api/health':
            assert response.content == expected, f'Stale SPA index: {path}'
    profile = client.get(BASE + '/api/users/administrator')
    assert profile.status_code == 200
    author = profile.json()
    assert author['username'] == 'administrator'
    assert author['nickname'] == '管理员'
    assert 'password' not in author and 'hashed_password' not in author
    with sqlite3.connect(f'file:{ROOT}/backend/blog.db?mode=ro', uri=True) as db:
        stored_bio = db.execute('SELECT bio FROM users WHERE username = ?',
                                ('jackfei',)).fetchone()[0]
    assert author['bio'] == stored_bio, 'Biography was modified by public serialization'
    social_urls = ('https://github.com/jackfeicoder', 'https://gitee.com/jackfei2545',
                   'https://blog.csdn.net/qq_62480054')
    assert all(url in author['bio'] for url in social_urls), 'Author links differ from requested links'
    assets = re.findall(r'(?:src|href)="(/assets/[^\"]+)"', expected.decode())
    for asset in assets:
        response = client.get(BASE + asset)
        assert response.status_code == 200, (asset, response.status_code)
    appearance = client.get(BASE + '/api/appearance')
    assert appearance.status_code == 200
print(json.dumps({'pages': pages, 'author_bio_preserved': True,
                  'author_links_correct': True, 'appearance': 200,
                  'entry_assets_checked': len(assets),
                  'index_sha256': hashlib.sha256(expected).hexdigest()}))
