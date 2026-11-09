"""Read-only origin checks, with a tiny Range read using an existing capability."""
from pathlib import Path
import hashlib
import json
import sqlite3
import sys
from urllib.request import Request, urlopen
from urllib.error import HTTPError

ROOT = Path('/www/wwwroot/blog.120115.xyz')
VHOST = Path('/www/server/panel/vhost/nginx')
backup = Path(sys.argv[1]).resolve(strict=True)
assert backup.parent == ROOT / '.deploy-backups' and backup.name.startswith('ithzf-')
for name, digest in json.loads((backup / 'manifest.json').read_text()).items():
    assert hashlib.sha256((VHOST / name).read_bytes()).hexdigest() == digest, 'Existing vhost changed: ' + name
print('OLD_VHOSTS_UNCHANGED')
with sqlite3.connect('file:' + str(ROOT / 'backend/blog.db') + '?mode=ro', uri=True) as live:
    with sqlite3.connect('file:' + str(backup / 'blog.db') + '?mode=ro', uri=True) as old:
        for table in ('users', 'posts', 'music_sources', 'music_lists', 'music_entries', 'site_appearance', 'registration_invites', 'registration_settings'):
            assert live.execute('SELECT * FROM ' + table + ' ORDER BY 1').fetchall() == old.execute('SELECT * FROM ' + table + ' ORDER BY 1').fetchall(), 'Data changed; inspect concurrent activity: ' + table
print('EXISTING_DATA_UNCHANGED')
with sqlite3.connect('file:' + str(ROOT / 'backend/.runtime/music-files.sqlite3') + '?mode=ro', uri=True) as db:
    row = db.execute('SELECT token FROM file_tickets LIMIT 1').fetchone()
assert row, 'No existing cached-audio capability to test'
for byte_range in ('bytes=0-4095', 'bytes=65536-69631'):
    request = Request('https://ithzf.xyz/api/music/stream/' + row[0], headers={'Range': byte_range})
    with urlopen(request, timeout=20) as response:
        assert response.status == 206, response.status
        assert len(response.read()) == 4096
        assert response.headers.get('Content-Range', '').startswith('bytes ')
print('CACHED_AUDIO_RANGE_AND_SEEK_OK')
for path, expected in (('/api/health', 200), ('/api/auth/registration-settings', 200), ('/api/auth/welcome-author', 200), ('/api/music/recommended', 401), ('/api/media/videos', 401), ('/_music_cache/test.audio', 404)):
    try:
        response = urlopen('https://ithzf.xyz' + path, timeout=20)
    except HTTPError as error:
        response = error
    with response:
        assert response.status == expected, (path, response.status)
print('ITHZF_DOMAIN_CHECKS_OK')
