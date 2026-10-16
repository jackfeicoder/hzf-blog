"""Small anonymous playback/cache smoke check; no credentials/URLs emitted."""
import json
from pathlib import Path
import sqlite3
import time
import httpx

ROOT = Path('/www/wwwroot/blog.120115.xyz/backend')


def main():
    with sqlite3.connect('file:' + str(ROOT/'blog.db') + '?mode=ro',uri=True) as db:
        songs=[json.loads(raw) for (raw,) in db.execute('SELECT song FROM music_entries')]
    song=next(s for s in songs if s.get('name')=='Letting Go' and s.get('singer')=='蔡健雅' and s.get('source')=='wy')
    with httpx.Client(base_url='http://127.0.0.1:8001',trust_env=False,timeout=35) as client:
        assert client.get('/api/health').json()['status']=='ok'
        before=time.monotonic()
        first=client.post('/api/music/resolve',json={'song':song})
        result={'song':'Letting Go','resolve_status':first.status_code,'resolve_seconds':round(time.monotonic()-before,3)}
        if first.status_code==200:
            data=first.json();before=time.monotonic()
            with client.stream('GET',data['url'],headers={'Range':'bytes=0-65535'}) as stream:
                total=0
                for chunk in stream.iter_bytes():
                    total+=len(chunk)
                    if total>=65536: break
                result.update(audio_status=stream.status_code,bytes_read=total,audio_seconds=round(time.monotonic()-before,3))
            before=time.monotonic()
            warm=client.post('/api/music/resolve',json={'song':song})
            result.update(warm_status=warm.status_code,warm_cache_hit=warm.json().get('cache_hit'),warm_seconds=round(time.monotonic()-before,3),source_id=data['source_id'])
        print(json.dumps(result,ensure_ascii=False),flush=True)


if __name__=='__main__': main()
