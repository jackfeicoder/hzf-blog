"""Loopback-only music UI fixture with disposable account, routing and audio."""
import json
from pathlib import Path
from fastapi import HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from auth import create_access_token
from music_models import MusicSource
from music_routing import RoutingStore
from music_files import MusicFiles
from models import User
from music_models import MusicEntry, MusicList
from routers import music, appearance
from preview_study import app, sessions, workspace

music.ROUTING = RoutingStore(Path(workspace.name)/'routing.sqlite3')
music.FILE_CACHE = MusicFiles(root=Path(workspace.name)/'audio', index=Path(workspace.name)/'files.sqlite3')
app.include_router(appearance.router)
original_upstream = music.upstream


async def layout_upstream(url, options=None):
    from urllib.parse import parse_qs, urlsplit
    if parse_qs(urlsplit(url).query).get('types') == ['lyric']:
        return {'lyric': '\n'.join(f'[00:{i * 2:02d}]布局验收第 {i + 1} 行 · 调小字号显示更多行' for i in range(30)), 'tlyric': ''}
    return await original_upstream(url, options)


music.upstream = layout_upstream
app.router.routes = [route for route in app.router.routes if getattr(route, 'path', None) != '/api/music/resolve']


@app.post('/api/music/resolve')
async def layout_resolve(body: music.Resolve):
    import os
    if body.song.id in os.getenv('MUSIC_PREVIEW_FAIL_IDS', '').split(','):
        raise HTTPException(502, '本地验收：本歌曲所有音源均失败')
    return {'url': '/api/music/fixture-audio', 'source_id': 1, 'source_name': '本地验收音源', 'expires_in': 1800}


# Recent FastAPI versions retain lazy included routers; fixture must precede them.
layout_route = app.router.routes[-1]
assert layout_route.path == '/api/music/resolve'
app.router.routes.remove(layout_route)
app.router.routes.insert(0, layout_route)


dist = Path(__file__).resolve().parents[2]/'frontend/dist'
app.mount('/assets', StaticFiles(directory=dist/'assets'), name='assets')
with sessions() as db:
    db.add(MusicSource(id=1,name='本地验收音源',script='unused fixture',digest='f'*64,enabled=True,position=0,
                      capabilities=json.dumps({'wy':{'actions':['musicUrl'],'qualitys':['128k']}})))
    db.commit()
    favorites=db.query(MusicList).filter_by(kind='favorites').one()
    for i in range(4,80):
        name='用来检查长歌曲名称和省略提示的测试歌曲' if i==4 else f'布局测试歌曲 {i:02d}'
        song=dict(source='wy',id=str(i),name=name,singer='本地测试歌手 / 第二位测试歌手',album='布局验收',pic_id='',lyric_id=str(i),duration=60)
        db.add(MusicEntry(list_id=favorites.id,song_key=f'wy:{i}',song=json.dumps(song)))
    db.commit()
context=dict(song_key='wy:1',title='晴天 · 测试音频',singer='本地测试音频',source_id=1,source_name='本地验收音源',digest='f'*64,
             song=dict(source='wy',id='1'),quality='128k',requested_quality='128k')
music.ROUTING.record(context,'resolve_error','failed','TimeoutError',1200)
music.ROUTING.record(context,'stream_ready','ok',elapsed_ms=300)


@app.get('/{path:path}')
def frontend(path: str, fixture: str='admin'):
    if path.startswith('api/'):
        raise HTTPException(404)
    if fixture == 'mobile':
        return HTMLResponse('<html><body style="margin:0;background:#eee"><iframe title="手机布局验收" src="/music?fixture=admin" style="border:0;width:390px;height:844px"></iframe></body></html>')
    with sessions() as db:
        name = 'jackfei' if fixture == 'admin' else 'study-demo'
        account = db.query(User).filter_by(username=name).one()
        token = create_access_token(name, account)
    statements = 'localStorage.setItem("blog_token",'+json.dumps(token)+');history.replaceState(null,"",'+json.dumps('/'+path)+');document.addEventListener("seeking",e=>{if(e.target.tagName==="AUDIO")document.body.dataset.seekCount=String(Number(document.body.dataset.seekCount||0)+1)},true);'
    return HTMLResponse((dist/'index.html').read_text(encoding='utf-8').replace('<head>','<head><script>'+statements+'</script>'))
