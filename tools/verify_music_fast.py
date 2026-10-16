"""Staged real-upstream smoke check using disposable DB; never emits media URLs."""
import asyncio
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import time

LIVE = Path('/www/wwwroot/blog.120115.xyz/backend')


def emit(**data):
    print(json.dumps(data, ensure_ascii=False), flush=True)


def verify(stage):
    with tempfile.TemporaryDirectory(prefix='hzf-music-fast-check-') as temporary:
        os.environ['DATABASE_URL'] = 'sqlite:///' + temporary + '/test.db'
        os.environ['MUSIC_SANDBOX'] = 'docker'
        sys.path.insert(0, str(stage / 'backend'))
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from database import Base, get_db
        from music_models import MusicSource
        from music_routing import RoutingStore
        from routers import music
        import music_worker
        engine = create_engine(os.environ['DATABASE_URL'], connect_args={'check_same_thread':False})
        Base.metadata.create_all(engine)
        sessions = sessionmaker(bind=engine)
        with sqlite3.connect('file:' + str(LIVE / 'blog.db') + '?mode=ro', uri=True) as db:
            rows = db.execute('SELECT id,name,script,digest,enabled,position,status,capabilities FROM music_sources').fetchall()
            samples = {}
            for (raw,) in db.execute('SELECT song FROM music_entries'):
                song = json.loads(raw)
                if (song.get('name'), song.get('singer')) in (('Letting Go','蔡健雅'), ('爱错','王力宏')):
                    samples[song['name']] = song
        with sessions() as db:
            for row in rows:
                db.add(MusicSource(**dict(zip(('id','name','script','digest','enabled','position','status','capabilities'),row))))
            db.commit()
        music.ROUTING = RoutingStore(Path(temporary) / 'routing.db')
        # Simulate a restart faithfully: successful route evidence survives,
        # while signed URL cache starts empty. Only copy metadata, never URLs.
        routing_path = LIVE / '.runtime/music-routing.sqlite3'
        if routing_path.is_file():
            with sqlite3.connect('file:' + str(routing_path) + '?mode=ro', uri=True) as db:
                remembered = db.execute('SELECT song_key,quality,source_id,digest,song,updated FROM routes').fetchall()
            with music.ROUTING.connection() as db:
                db.executemany('INSERT OR REPLACE INTO routes VALUES(?,?,?,?,?,?)', remembered)
        def session():
            with sessions() as db: yield db
        app = FastAPI(); app.include_router(music.router); app.dependency_overrides[get_db] = session
        console_script = "lx.send('inited',{sources:{wy:{actions:['musicUrl'],qualitys:['128k']}}});lx.on('request',async()=>{console.group('hidden');console.groupCollapsed('hidden');console.groupEnd();return 'ok';});"
        compatible = asyncio.run(music_worker.run_source(console_script,'compatibility','musicUrl','wy',{'type':'128k'}))
        assert compatible['result'] == 'ok'
        emit(event='ISOLATED_CONSOLE_COMPAT_OK')
        with TestClient(app) as client:
            for title in ('Letting Go', '爱错'):
                if title not in samples: continue
                started = time.monotonic()
                response = client.post('/api/music/resolve', json={'song':samples[title]})
                result = dict(event='STAGED_PLAYBACK', title=title, cold_status=response.status_code, cold_seconds=round(time.monotonic()-started,3))
                if response.status_code == 200:
                    data = response.json()
                    token = data['url'].rsplit('/',1)[1]
                    _, url, context = music.TICKETS[token]
                    before = time.monotonic()
                    r, c, _ = music.open_http(url, headers={'Range':'bytes=0-65535'}, timeout=8)
                    try:
                        first = r.read1(512)
                        valid = r.status in (200,206) and bool(first) and not first.lstrip().startswith((b'{',b'<',b'['))
                        if valid:
                            context['ready'] = True
                            music.observation(context,'stream_ready','ok')
                        result.update(audio_valid=valid, audio_http=r.status, audio_first_seconds=round(time.monotonic()-before,3), platform=data['playback_song']['source'], source_id=data['source_id'], attempted=len(data['attempted']))
                    finally: r.close(); c.close()
                    before = time.monotonic()
                    warm = client.post('/api/music/resolve', json={'song':samples[title]})
                    result.update(warm_status=warm.status_code, warm_seconds=round(time.monotonic()-before,3), warm_cache_hit=warm.json().get('cache_hit'))
                emit(**result)
        engine.dispose()
        emit(event='CHECK_FINISHED', live_database_modified=False)


if __name__ == '__main__':
    verify(Path(sys.argv[1]).resolve(strict=True))
