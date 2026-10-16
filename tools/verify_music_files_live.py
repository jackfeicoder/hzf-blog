"""Warm one real track; compare exact local Range bytes through Nginx."""
import json
from pathlib import Path
import sqlite3
import time
import httpx

ROOT=Path('/www/wwwroot/blog.120115.xyz/backend')


def main():
    with sqlite3.connect('file:'+str(ROOT/'blog.db')+'?mode=ro',uri=True) as db:
        songs=[json.loads(raw) for (raw,) in db.execute('SELECT song FROM music_entries')]
    song=next(s for s in songs if s.get('name')=='Letting Go' and s.get('singer')=='蔡健雅' and s.get('source')=='wy')
    with httpx.Client(base_url='http://127.0.0.1:8001',trust_env=False,timeout=35) as api:
        assert api.get('/api/music/file-cache').status_code==401
        first=api.post('/api/music/resolve',json={'song':song})
        assert first.status_code==200, f'First resolve {first.status_code}'
        with api.stream('GET',first.json()['url'],headers={'Range':'bytes=0-8191'}) as stream:
            assert stream.status_code in (200,206)
            next(stream.iter_bytes(512))
        entry=None
        deadline=time.monotonic()+55
        index=ROOT/'.runtime/music-files.sqlite3'
        while time.monotonic()<deadline:
            if index.exists():
                with sqlite3.connect('file:'+str(index)+'?mode=ro',uri=True) as db:
                    db.row_factory=sqlite3.Row
                    entry=db.execute('SELECT * FROM files WHERE song_key=?',('wy:'+song['id'],)).fetchone()
                if entry: break
            time.sleep(.5)
        assert entry, 'Background file cache not completed; inspect sanitized worker log'
        start=time.monotonic()
        hit=api.post('/api/music/resolve',json={'song':song})
        resolve_ms=round((time.monotonic()-start)*1000,2)
        assert hit.status_code==200 and hit.json().get('file_cache_hit')
        with httpx.Client(base_url='http://127.0.0.1',headers={'Host':'blog.120115.xyz'},trust_env=False,timeout=8) as nginx:
            assert nginx.get('/_music_cache/'+entry['id']+'.audio').status_code==404
            for start in (0,1000000):
                begin=time.monotonic()
                response=nginx.get(hit.json()['url'],headers={'Range':f'bytes={start}-{start+8191}'})
                elapsed=round((time.monotonic()-begin)*1000,2)
                assert response.status_code==206, f'Range HTTP {response.status_code}'
                assert response.headers.get('x-music-cache')=='HIT'
                with open(ROOT/'.music-cache'/(entry['id']+'.audio'),'rb') as audio:
                    audio.seek(start)
                    assert response.content==audio.read(8192)
                print('LOCAL_RANGE_OK='+json.dumps(dict(offset=start,bytes=len(response.content),milliseconds=elapsed,content_range=response.headers.get('content-range'))),flush=True)
        print('LIVE_FILE_CACHE_OK='+json.dumps(dict(song=song['name'],file_bytes=entry['size'],quality=entry['quality'],resolve_ms=resolve_ms)),flush=True)


if __name__=='__main__': main()
