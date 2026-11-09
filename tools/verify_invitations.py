"""Read-only post-release checks; never creates accounts or invitation codes."""
import json
from pathlib import Path
import sqlite3
import sys
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path('/www/wwwroot/blog.120115.xyz')


def check(path, expected, body=None):
    request = Request('http://127.0.0.1:8001' + path,
                      data=json.dumps(body).encode() if body is not None else None,
                      headers={'Content-Type': 'application/json'})
    try:
        response = urlopen(request, timeout=10)
    except HTTPError as error:
        response = error
    with response:
        assert response.status == expected, (path, response.status)
        data = json.load(response)
        if path.startswith('/api/auth/'):
            assert 'no-store' in response.headers.get('Cache-Control', '')
        return data


check('/api/health', 200)
check('/api/auth/invitations', 401)
check('/api/visitors', 401)
settings = check('/api/auth/registration-settings', 200)
assert isinstance(settings.get('invite_required'), bool)
if settings['invite_required']:
    validation = check('/api/auth/register', 400, {'username': 'registration-check-only', 'password': 'not-a-real-password'})
    assert '邀请码' in validation['detail']
for path in ('/api/posts/1', '/api/users/administrator', '/api/media/videos', '/api/music/recommended', '/api/chat/providers'):
    check(path, 401)
check('/api/posts?page_size=1', 200)
check('/api/auth/welcome-author', 200)
schema = check('/openapi.json', 200)
assert '/api/auth/registration-settings' in schema['paths']
assert '/api/auth/invitations/{invite_id}' in schema['paths']
if len(sys.argv) > 1:
    with sqlite3.connect('file:' + str(ROOT / 'backend/blog.db') + '?mode=ro', uri=True) as live:
        with sqlite3.connect('file:' + str(Path(sys.argv[1]) / 'blog.db') + '?mode=ro', uri=True) as before:
            for table in ('users', 'music_sources', 'music_lists', 'music_entries', 'site_appearance', 'registration_invites', 'registration_settings'):
                assert live.execute('SELECT * FROM ' + table + ' ORDER BY 1').fetchall() == before.execute('SELECT * FROM ' + table + ' ORDER BY 1').fetchall(), table + ' changed; inspect concurrent user activity'
        assert live.execute("SELECT name FROM sqlite_master WHERE name='registration_invites'").fetchone()
        print('EXISTING_USERS_MUSIC_AND_APPEARANCE_UNCHANGED')
print('INVITATION_PRODUCTION_CHECKS_OK')
