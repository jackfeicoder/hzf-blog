"""One existing favorite: verify durable lyrics and warm response, no private output."""
import json
from pathlib import Path
import sqlite3
import sys
import time
import httpx

ROOT = Path('/www/wwwroot/blog.120115.xyz/backend')


def main():
    sys.path.insert(0, str(ROOT))
    from music_lyrics import LyricCache, resolved_key
    from routers.music import Song
    with sqlite3.connect('file:' + str(ROOT / 'blog.db') + '?mode=ro', uri=True) as db:
        songs = [json.loads(row[0]) for row in db.execute('SELECT song FROM music_entries')]
    song = next(s for s in songs if s.get('name') == 'Letting Go' and s.get('source') == 'wy')
    durations = []
    with httpx.Client(base_url='http://127.0.0.1:8001', trust_env=False, timeout=20) as api:
        for _ in range(2):
            begin = time.monotonic()
            response = api.post('/api/music/lyrics/resolve', json={'song': song})
            durations.append(round((time.monotonic() - begin) * 1000, 2))
            assert response.status_code == 200 and response.json().get('lyric'), 'Lyric fetch failed; inspect without printing content'
            assert response.headers['cache-control'] == 'private, no-store'
            data = response.json()
    path = ROOT / '.runtime/music-lyrics.sqlite3'
    # Separate instance/process lookup proves the successful response reached disk.
    saved = LyricCache(path).get(resolved_key(Song(**song)))
    assert saved == data, 'Resolved lyrics not persisted'
    assert path.stat().st_mode & 0o777 == 0o600
    print('LIVE_LYRICS_OK=' + json.dumps(dict(song=song['name'], lyric_chars=len(data['lyric']),
        translation_chars=len(data.get('translation', '')), first_ms=durations[0], cached_ms=durations[1],
        database_bytes=path.stat().st_size, durable=True)), flush=True)


if __name__ == '__main__':
    main()
