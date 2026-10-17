"""Real source verification in staged code, read-only production source catalogue.

No source replacement, live preferences, playlist mutation, or saved media URLs.
"""
import argparse
import asyncio
from io import BytesIO
import json
import os
from pathlib import Path
import sys
import tempfile
import time


def emit(**data): print(json.dumps(data, ensure_ascii=False), flush=True)


async def main(stage, live=False):
    os.environ['MUSIC_SANDBOX'] = 'docker'
    os.environ['MUSIC_FILE_CACHE'] = '0'
    sys.path.insert(0, str(stage / 'backend'))
    import httpx
    from fastapi import FastAPI
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from database import get_db
    from routers import music
    from music_routing import RoutingStore
    from music_playback import AudioCache
    from music_lyrics import LyricCache
    from music_files import MusicFiles
    from music_http import open_http
    from mutagen.mp3 import MP3
    root = Path('/www/wwwroot/blog.120115.xyz')
    with tempfile.TemporaryDirectory(prefix='hzf-music-proof-') as temp:
        temp = Path(temp)
        music.ROUTING = RoutingStore(temp / 'routing.sqlite3')
        music.AUDIO_CACHE = AudioCache(path=temp / 'addresses.sqlite3')
        music.LYRIC_CACHE = LyricCache(temp / 'lyrics.sqlite3')
        music.FILE_CACHE = MusicFiles(root=temp / 'audio', index=temp / 'files.sqlite3', enabled=False)
        engine = create_engine('sqlite:///file:' + str(root / 'backend/blog.db') + '?mode=ro&uri=true', connect_args={'check_same_thread':False})
        session = sessionmaker(bind=engine)
        app = FastAPI(); app.include_router(music.router)
        def readonly():
            with session() as db: yield db
        app.dependency_overrides[get_db] = readonly
        options = dict(base_url='http://127.0.0.1:8001', timeout=40, trust_env=False)
        if not live: options['transport'] = httpx.ASGITransport(app=app)
        else:
            # Loopback only: include Nginx so X-Accel-Redirect serves real bytes.
            # The public hostname/certificate is checked separately at the edge.
            options.update(base_url='https://127.0.0.1:8443', verify=False,
                           headers={'Host':'blog.120115.xyz'})
        async with httpx.AsyncClient(**options) as client:
            response = await client.get('/api/music/search', params={'source':'kw','q':'枫 周杰伦'})
            assert response.status_code == 200, 'KW metadata request failed'
            matches = [s for s in response.json()['items'] if s['name']=='枫' and s['singer']=='周杰伦']
            assert matches, 'Original recording absent from normal search'
            emit(event='normal_search_found', platform='kw', ids=[s['id'] for s in matches])
            # Use the original KG recording to exercise automatic backup-platform
            # discovery. This test fixture ID is not part of application code.
            song = dict(source='kg', id='0D7E8C11C961A17EB8779FEB0CA772E3', name='枫', singer='周杰伦', album='十一月的萧邦', duration=275)
            attempted, deferred = [], []
            for batch in range(1, 25):
                begin = time.monotonic()
                response = await client.post('/api/music/resolve', json=dict(song=song, quality='128k',
                    attempted=attempted, deferred=deferred, allow_platform_fallback=True))
                data = response.json()
                if response.status_code == 200:
                    token = data['url'].rsplit('/',1)[-1]
                    if live:
                        # Range read through the actual Nginx route; no signed URL output.
                        async with client.stream('GET', data['url'], headers={'Range':'bytes=0-65535'}) as audio:
                            blob = b''
                            async for chunk in audio.aiter_bytes():
                                blob += chunk
                                if len(blob)>=65536: break
                            status = audio.status_code
                    else:
                        url = music.TICKETS[token][1]
                        def read():
                            r,c,_ = open_http(url, headers={'Range':'bytes=0-65535'})
                            try: return r.status,r.read(65536)
                            finally: r.close(); c.close()
                        status,blob = await asyncio.to_thread(read)
                    info = MP3(BytesIO(blob)).info
                    assert status in (200,206) and len(blob)>1024 and 260<=info.length<=290
                    emit(event='automatic_fallback_playable', batch=batch, source_id=data['source_id'],
                         platform=data['playback_song']['source'], recording_id=data['playback_song']['id'],
                         quality=data['quality'], http=status, bytes=len(blob), seconds=round(info.length,3),
                         route=data.get('route_id'), failed_routes=len(data.get('attempted',[])))
                    break
                detail = data.get('detail')
                assert isinstance(detail,dict) and detail.get('continue') and not detail.get('exhausted'), 'Resolve stopped before valid recording: '+str(response.status_code)
                attempted, deferred = detail['attempted'],detail.get('deferred',[])
                wait = min(300,detail.get('retry_after',0))
                emit(event='pending_batch', batch=batch, elapsed=round(time.monotonic()-begin,2), failed_routes=len(attempted), deferred_routes=len(deferred), retry_after=wait)
                await asyncio.sleep(wait)
            else: raise RuntimeError('Diagnostic time budget ended; not a claim of exhaustion')
        music.FILE_CACHE.close(); engine.dispose()


if __name__ == '__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('stage',type=Path); parser.add_argument('--live',action='store_true')
    args=parser.parse_args(); asyncio.run(main(args.stage.resolve(),args.live))
