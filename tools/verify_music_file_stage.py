"""One real audio download into disposable staging; never emits signed URLs."""
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import time
import httpx

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from music_files import MusicFiles

ROOT=Path('/www/wwwroot/blog.120115.xyz/backend')


def song_sample():
    with sqlite3.connect('file:'+str(ROOT/'blog.db')+'?mode=ro',uri=True) as db:
        songs=[json.loads(raw) for (raw,) in db.execute('SELECT song FROM music_entries')]
    return next(s for s in songs if s.get('name')=='Letting Go' and s.get('singer')=='蔡健雅' and s.get('source')=='wy')


def address(data):
    with sqlite3.connect('file:'+str(ROOT/'blog.db')+'?mode=ro',uri=True) as db:
        digest=db.execute('SELECT digest FROM music_sources WHERE id=?',(data['source_id'],)).fetchone()[0]
    candidate=data['playback_song']
    key=(data['source_id'],digest,candidate['source']+':'+candidate['id'],data['quality'])
    with sqlite3.connect('file:'+str(ROOT/'.runtime/music-addresses.sqlite3')+'?mode=ro',uri=True) as db:
        return db.execute('SELECT url FROM addresses WHERE cache_key=?',(json.dumps(key),)).fetchone()[0]


def main():
    song=song_sample()
    with tempfile.TemporaryDirectory(prefix='music-file-validation-') as temp:
        cache=MusicFiles(root=Path(temp)/'audio',index=Path(temp)/'index.sqlite3')
        try:
            with httpx.Client(base_url='http://127.0.0.1:8001',trust_env=False,timeout=35) as client:
                token=''
                for attempt in range(2):
                    response=client.post('/api/music/resolve',json={'song':song,'refresh_token':token})
                    assert response.status_code==200, f'Resolve HTTP {response.status_code}'
                    data=response.json(); token=data['url'].rsplit('/',1)[1]
                    start=time.monotonic()
                    try:
                        cache.download(song,data['quality'],address(data))
                        entry=cache.get(song,data['quality'])
                        assert entry and entry['size']>1000000
                        print('STAGED_REAL_AUDIO_OK='+json.dumps(dict(song=song['name'],bytes=entry['size'],duration=round(entry['duration'],2),seconds=round(time.monotonic()-start,2),quality=entry['quality'])),flush=True)
                        return
                    except Exception as error:
                        print('STAGED_RETRY_REASON='+type(error).__name__,flush=True)
                        if attempt: raise
                        client.post('/api/music/feedback',json={'token':token,'event':'error'})
        finally:
            cache.close()


if __name__=='__main__': main()
