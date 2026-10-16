"""Live cache-restart smoke test; prints no IPs, signed URLs or credentials."""
import json
from pathlib import Path
import sqlite3
import subprocess
import time
import httpx

ROOT = Path('/www/wwwroot/blog.120115.xyz/backend')


def resolve(client, song):
    start = time.monotonic()
    response = client.post('/api/music/resolve', json={'song': song})
    assert response.status_code == 200, f'Resolve status {response.status_code}'
    data = response.json()
    info = {'cache_hit': data['cache_hit'], 'resolve_ms': round((time.monotonic()-start)*1000)}
    with client.stream('GET', data['url'], headers={'Range': 'bytes=0-65535'}) as stream:
        assert stream.status_code in (200, 206)
        chunk = next(stream.iter_bytes(512))
        assert chunk and not chunk.lstrip().startswith((b'{', b'<'))
        info['audio_status'] = stream.status_code
    return info


def main():
    with sqlite3.connect('file:' + str(ROOT/'blog.db') + '?mode=ro', uri=True) as db:
        songs = [json.loads(raw) for (raw,) in db.execute('SELECT song FROM music_entries')]
        columns = db.execute('PRAGMA table_info(visit_days)').fetchall()
        assert {row[1] for row in columns if row[5]} == {'ip', 'day_start'}
    song = next(s for s in songs if s.get('name') == 'Letting Go' and s.get('singer') == '蔡健雅' and s.get('source') == 'wy')
    with httpx.Client(base_url='http://127.0.0.1:8001', trust_env=False, timeout=35) as client:
        assert client.get('/api/visitors').status_code == 401
        first = resolve(client, song)
        print('BEFORE_RESTART=' + json.dumps(first), flush=True)
        store = ROOT/'.runtime/music-addresses.sqlite3'
        assert store.exists() and store.stat().st_mode & 0o777 == 0o600
        with sqlite3.connect('file:' + str(store) + '?mode=ro', uri=True) as db:
            assert db.execute('SELECT COUNT(*) FROM addresses').fetchone()[0] > 0
        subprocess.run(['systemctl', 'restart', 'hzf-blog.service'], check=True)
        for _ in range(30):
            try:
                if client.get('/api/health').json()['status'] == 'ok':
                    break
            except (httpx.HTTPError, ValueError):
                pass
            time.sleep(.5)
        second = resolve(client, song)
        assert second['cache_hit'], 'Restart lost successful URL'
        print('AFTER_RESTART=' + json.dumps(second), flush=True)
        print('PERSISTENT_CACHE_AND_VISITOR_SCHEMA_OK', flush=True)


if __name__ == '__main__':
    main()
