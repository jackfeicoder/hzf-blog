import asyncio
from collections import OrderedDict, deque
from datetime import datetime
import hashlib
import json
import re
import secrets
import time
from typing import Literal
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from auth import get_current_user, require_superadmin
from database import get_db
from music_models import MusicEntry, MusicList, MusicSource
from music_http import fetch, open_http, target
from music_worker import run_source
from models import User

router = APIRouter(prefix='/api/music', tags=['music'])
PLATFORMS = {'wy': 'netease', 'tx': 'tencent', 'kw': 'kuwo', 'kg': 'kugou', 'mg': 'migu'}
GD = 'https://music-api.gdstudio.xyz/api.php'
CACHE = OrderedDict()
TICKETS = OrderedDict()
LIMITS = OrderedDict()
UPSTREAM = asyncio.Semaphore(6)
STREAMS = asyncio.Semaphore(8)


def cached(key):
    item = CACHE.get(key)
    if item and item[0] > time.monotonic():
        CACHE.move_to_end(key)
        return item[1]
    CACHE.pop(key, None)


def remember(key, value, ttl=300):
    CACHE[key] = (time.monotonic() + ttl, value)
    CACHE.move_to_end(key)
    while len(CACHE) > 300:
        CACHE.popitem(last=False)
    # Images have a separate small budget within this shared bounded cache.
    covers = [k for k in CACHE if isinstance(k, tuple) and k[0] == 'cover']
    for k in covers[:-24]:
        CACHE.pop(k, None)
    return value


def limit(request: Request, operation='read', maximum=40):
    key = (request.client.host if request.client else 'unknown', operation)
    now = time.monotonic()
    times = LIMITS.setdefault(key, deque())
    while times and times[0] < now - 60:
        times.popleft()
    if len(times) >= maximum:
        raise HTTPException(429, '操作稍频繁，请稍后再试', headers={'Retry-After': '60'})
    times.append(now)
    LIMITS.move_to_end(key)
    while len(LIMITS) > 3000:
        LIMITS.popitem(last=False)


def private(response: Response):
    response.headers['Cache-Control'] = 'private, no-store'


class Song(BaseModel):
    source: Literal['wy', 'tx', 'kw', 'kg', 'mg']
    id: str = Field(min_length=1, max_length=160, pattern=r'^[a-zA-Z0-9_\-]+$')
    name: str = Field(min_length=1, max_length=200)
    singer: str = Field(default='', max_length=300)
    album: str = Field(default='', max_length=300)
    pic_id: str = Field(default='', max_length=160, pattern=r'^[a-zA-Z0-9_\-]*$')
    lyric_id: str = Field(default='', max_length=160, pattern=r'^[a-zA-Z0-9_\-]*$')
    duration: float = Field(default=0, ge=0, le=86400)
    model_config = {'extra': 'forbid'}

    @property
    def key(self):
        return self.source + ':' + self.id


async def upstream(url, options=None):
    async with UPSTREAM:
        result = await asyncio.to_thread(fetch, url, options)
    if result['statusCode'] != 200:
        raise ValueError('上游暂时不可用')
    return result['body']


@router.get('/search')
async def search(request: Request, response: Response, q: str = Query(min_length=1, max_length=100),
                 source: Literal['wy', 'tx', 'kw', 'kg', 'mg'] = 'wy', page: int = Query(1, ge=1, le=50)):
    limit(request)
    key = ('search', q.strip(), source, page)
    result = cached(key)
    if result is not None:
        return result
    try:
        try:
            data = await upstream(GD + '?' + urlencode(dict(types='search', source=PLATFORMS[source], name=q.strip(), count=20, pages=page)))
        except Exception:
            if source != 'wy':
                raise
            payload = await upstream('https://music.163.com/api/search/get?' + urlencode(dict(s=q.strip(), type=1, limit=20, offset=(page - 1) * 20)))
            data = [dict(id=row['id'], name=row['name'], artist=[a['name'] for a in row.get('artists', [])],
                         album=row.get('album', {}).get('name', ''), lyric_id=row['id'],
                         pic_id=str(row.get('album', {}).get('picId') or ''), duration=row.get('duration', 0) / 1000)
                    for row in payload.get('result', {}).get('songs', [])]
        if not isinstance(data, list):
            raise ValueError('搜索格式异常')
        items = []
        for row in data[:20]:
            try:
                artist = row.get('artist', [])
                song = Song(source=source, id=str(row.get('id', '')), name=row.get('name', ''),
                            singer=' / '.join(artist) if isinstance(artist, list) else str(artist),
                            album=row.get('album', ''), pic_id=str(row.get('pic_id') or ''), lyric_id=str(row.get('lyric_id') or ''), duration=row.get('duration', 0))
                items.append(song.model_dump())
            except (ValueError, TypeError):
                continue
        response.headers['Cache-Control'] = 'public, max-age=60'
        return remember(key, dict(items=items, page=page, has_more=len(data) == 20))
    except Exception:
        raise HTTPException(502, '搜索音源暂时没有响应，请切换平台或稍后重试')


@router.get('/lyrics')
async def lyrics(request: Request, source: Literal['wy', 'tx', 'kw', 'kg', 'mg'], id: str = Query(max_length=160, pattern=r'^[a-zA-Z0-9_\-]+$')):
    limit(request)
    key = ('lyrics', source, id)
    result = cached(key)
    if result is not None:
        return result
    try:
        if source == 'wy' and id.isdigit():
            try:
                raw = await upstream('https://music.163.com/api/song/lyric?' + urlencode(dict(id=id, lv=-1, tv=-1)))
                data = {'lyric': raw.get('lrc', {}).get('lyric', ''), 'tlyric': raw.get('tlyric', {}).get('lyric', '')}
                if not data['lyric']:
                    raise ValueError()
            except Exception:
                data = await upstream(GD + '?' + urlencode(dict(types='lyric', source=PLATFORMS[source], id=id)))
        else:
            data = await upstream(GD + '?' + urlencode(dict(types='lyric', source=PLATFORMS[source], id=id)))
        if not isinstance(data, dict):
            raise ValueError()
        return remember(key, {'lyric': str(data.get('lyric') or '')[:100000], 'translation': str(data.get('tlyric') or '')[:100000]}, 3600)
    except Exception:
        return {'lyric': '', 'translation': ''}


@router.get('/cover')
async def cover(request: Request, source: Literal['wy', 'tx', 'kw', 'kg', 'mg'], id: str = Query(max_length=160, pattern=r'^[a-zA-Z0-9_\-]+$'), song_id: str = Query(default='', max_length=160, pattern=r'^[a-zA-Z0-9_\-]*$')):
    limit(request, 'cover', 60)
    key = ('cover', source, id, song_id)
    result = cached(key)
    if result is not None:
        return Response(result[0], media_type=result[1], headers={'Cache-Control': 'public, max-age=86400'})
    try:
        url = ''
        if source == 'wy' and song_id.isdigit():
            try:
                data = await upstream('https://music.163.com/api/song/detail/?' + urlencode({'ids': json.dumps([int(song_id)])}))
                url = data.get('songs', [{}])[0].get('album', {}).get('picUrl', '')
                if url.startswith('http://'):
                    url = 'https://' + url[7:]
                if url:
                    url += ('&' if '?' in url else '?') + 'param=400y400'
            except Exception:
                pass
        if not url:
            data = await upstream(GD + '?' + urlencode(dict(types='pic', source=PLATFORMS[source], id=id, size=500)))
            url = data.get('url', '') if isinstance(data, dict) else ''
        async with UPSTREAM:
            r, conn, _ = await asyncio.to_thread(open_http, url)
            try:
                kind = r.getheader('Content-Type', '').split(';')[0].lower()
                if kind == 'image/jpg':
                    kind = 'image/jpeg'
                if kind not in ('image/jpeg', 'image/png', 'image/webp', 'image/gif') or r.status != 200:
                    raise ValueError()
                image = await asyncio.to_thread(r.read, 524289)
                if len(image) > 524288:
                    raise ValueError()
            finally:
                r.close(); conn.close()
        remember(key, (image, kind), 3600)
        return Response(image, media_type=kind, headers={'Cache-Control': 'public, max-age=86400'})
    except Exception:
        raise HTTPException(404, '暂无封面')


def source_out(row):
    return dict(id=row.id, name=row.name, enabled=row.enabled, position=row.position, status=row.status,
                digest=row.digest, capabilities=json.loads(row.capabilities))


@router.get('/sources')
def sources(response: Response, db: Session = Depends(get_db)):
    response.headers['Cache-Control'] = 'no-store'
    return [source_out(s) for s in db.query(MusicSource).order_by(MusicSource.position, MusicSource.id).all()]


class SourceImport(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    script: str = Field(min_length=10, max_length=600000)
    model_config = {'extra': 'forbid'}


@router.post('/sources', status_code=201)
def import_source(body: SourceImport, response: Response, db: Session = Depends(get_db), user=Depends(require_superadmin)):
    private(response)
    digest = hashlib.sha256(body.script.encode()).hexdigest()
    if len(body.script.encode()) > 600000:
        raise HTTPException(413, '音源文件最大 600 KB')
    if db.query(MusicSource).filter_by(digest=digest).first():
        raise HTTPException(409, '此音源已经导入')
    if db.query(MusicSource).count() >= 30:
        raise HTTPException(409, '最多保留 30 个音源')
    row = MusicSource(name=body.name.strip(), digest=digest, script=body.script)
    db.add(row); db.commit(); CACHE.clear()
    return source_out(row)


class SourceEdit(BaseModel):
    enabled: bool
    position: int = Field(ge=0, le=999)
    model_config = {'extra': 'forbid'}


def get_source(db, source_id):
    row = db.get(MusicSource, source_id)
    if not row:
        raise HTTPException(404, '音源不存在')
    return row


@router.put('/sources/{source_id}')
def edit_source(source_id: int, body: SourceEdit, response: Response, db: Session = Depends(get_db), user=Depends(require_superadmin)):
    private(response)
    row = get_source(db, source_id)
    if body.enabled and not json.loads(row.capabilities):
        raise HTTPException(409, '请先进行兼容性测试')
    row.enabled, row.position = body.enabled, body.position
    db.commit(); CACHE.clear()
    return source_out(row)


@router.delete('/sources/{source_id}', status_code=204)
def delete_source(source_id: int, response: Response, db: Session = Depends(get_db), user=Depends(require_superadmin)):
    private(response); db.delete(get_source(db, source_id)); db.commit(); CACHE.clear()


@router.post('/sources/{source_id}/test')
async def test_source(source_id: int, request: Request, response: Response, db: Session = Depends(get_db), user=Depends(require_superadmin)):
    limit(request, 'probe', 10); private(response)
    row = get_source(db, source_id)
    try:
        async with asyncio.timeout(18):
            result = await run_source(row.script, row.name)
        row.capabilities = json.dumps(result.get('capabilities') or {})
        row.status = '兼容性通过，播放需实测' if json.loads(row.capabilities) else '未报告支持的平台'
    except Exception:
        row.capabilities = '{}'; row.enabled = False; row.status = '初始化失败 / 请求超时'
    db.commit(); CACHE.clear()
    return source_out(row)


class Resolve(BaseModel):
    song: Song
    quality: Literal['128k', '320k', 'flac', 'flac24bit'] = '128k'
    exclude: list[int] = Field(default_factory=list, max_length=30)
    model_config = {'extra': 'forbid'}


def ticket(url, source_id, name):
    now = time.monotonic()
    token = secrets.token_urlsafe(32)
    TICKETS[token] = (now + 1800, url)
    while len(TICKETS) > 500:
        TICKETS.popitem(last=False)
    return {'url': '/api/music/stream/' + token, 'source_id': source_id, 'source_name': name, 'expires_in': 1800}


def check_audio(url):
    r, c, final = open_http(url, headers={'Range': 'bytes=0-511'})
    try:
        if r.status not in (200, 206):
            raise ValueError('音频不可用')
        kind = r.getheader('Content-Type', '').lower()
        head = r.read(512)
        # Avoid accepting JSON/HTML errors disguised as successful media replies.
        if 'text/' in kind or 'json' in kind or not head or head.lstrip().startswith((b'{', b'<', b'[')):
            raise ValueError('音源未返回音频')
        if not (kind.startswith('audio/') or head.startswith((b'ID3', b'fLaC', b'OggS', b'RIFF', b'\xff')) or head[4:8] == b'ftyp'):
            raise ValueError('音频格式未识别')
        return final
    finally:
        r.close(); c.close()


@router.post('/resolve')
async def resolve(body: Resolve, request: Request, response: Response, db: Session = Depends(get_db)):
    limit(request, 'resolve', 20); private(response)
    rows = [(s.id, s.name, s.script) for s in db.query(MusicSource).filter_by(enabled=True).order_by(MusicSource.position, MusicSource.id)
            if s.id not in body.exclude and body.song.source in json.loads(s.capabilities)]
    if not rows:
        raise HTTPException(503, '没有可用音源，请联系管理员导入并启用音源')
    info = body.song.model_dump()
    info.update(songmid=body.song.id, hash=body.song.id, albumName=body.song.album)
    # Return after one healthy provider; frontend can explicitly exclude it on playback failure.
    try:
        async with asyncio.timeout(28):
            for source_id, name, script in rows[:4]:
                key = ('url', source_id, body.song.key, body.quality)
                try:
                    url = cached(key)
                    if not url:
                        data = await run_source(script, name, 'musicUrl', body.song.source, dict(type=body.quality, musicInfo=info))
                        url = await asyncio.to_thread(check_audio, data.get('result'))
                        remember(key, url, 120)
                    return ticket(url, source_id, name)
                except Exception:
                    CACHE.pop(key, None)
    except TimeoutError:
        pass
    raise HTTPException(502, '本次音源暂不可用，已尝试换源。可换平台或稍后重试')


@router.get('/stream/{token}')
async def stream(token: str, request: Request):
    value = TICKETS.get(token)
    if not value or value[0] < time.monotonic():
        TICKETS.pop(token, None)
        raise HTTPException(410, '播放地址已过期，请重新播放')
    limit(request, 'stream', 60)
    headers = {}
    range_header = request.headers.get('range')
    if range_header:
        if not re.fullmatch(r'bytes=\d*-\d*', range_header) or range_header == 'bytes=-':
            raise HTTPException(416, '无效播放范围')
        headers['Range'] = range_header
    try:
        await asyncio.wait_for(STREAMS.acquire(), timeout=2)
    except TimeoutError:
        raise HTTPException(503, '播放器繁忙，请稍后重试')
    try:
        r, c, _ = await asyncio.to_thread(open_http, value[1], 'GET', headers, None, 10)
        if r.status not in (200, 206) or 'text/' in r.getheader('Content-Type', '') or 'json' in r.getheader('Content-Type', '') or int(r.getheader('Content-Length', '0')) > 100 * 1024 * 1024:
            r.close(); c.close()
            raise ValueError()
    except Exception:
        STREAMS.release()
        raise HTTPException(502, '音频源响应异常')
    async def chunks():
        total = 0
        try:
            async with asyncio.timeout(600):
                while total < 100 * 1024 * 1024:
                    chunk = await asyncio.to_thread(r.read1, min(65536, 100 * 1024 * 1024 - total))
                    if not chunk:
                        break
                    total += len(chunk)
                    yield chunk
        finally:
            r.close(); c.close(); STREAMS.release()
    outgoing = {'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff'}
    for h in ('Content-Length', 'Content-Range', 'Accept-Ranges'):
        if r.getheader(h):
            outgoing[h] = r.getheader(h)
    return StreamingResponse(chunks(), status_code=r.status, media_type=r.getheader('Content-Type', 'audio/mpeg'), headers=outgoing)


def ensure_library(db, user_id):
    rows = db.query(MusicList).filter_by(user_id=user_id).all()
    for kind, name in (('favorites', '我喜欢'), ('history', '最近播放')):
        if not any(r.kind == kind for r in rows):
            db.add(MusicList(user_id=user_id, kind=kind, name=name))
    db.commit()


def owned_list(db, list_id, user_id):
    row = db.query(MusicList).filter_by(id=list_id, user_id=user_id).first()
    if not row:
        raise HTTPException(404, '歌单不存在')
    return row


@router.get('/library')
def library(response: Response, db: Session = Depends(get_db), user=Depends(get_current_user)):
    private(response); ensure_library(db, user.id)
    return [{'id': row.id, 'name': row.name, 'kind': row.kind,
             'songs': [json.loads(e.song) for e in db.query(MusicEntry).filter_by(list_id=row.id).order_by(MusicEntry.updated_at.desc(), MusicEntry.id.desc()).limit(500)]}
            for row in db.query(MusicList).filter_by(user_id=user.id).order_by(MusicList.id)]


@router.get('/recommended')
def recommended(response: Response, db: Session = Depends(get_db)):
    """The explicitly shared jackfei favorites only; all other lists stay private."""
    response.headers['Cache-Control'] = 'no-store'
    rows = db.query(MusicEntry).join(MusicList, MusicEntry.list_id == MusicList.id).join(
        User, MusicList.user_id == User.id).filter(User.username == 'jackfei', MusicList.kind == 'favorites').order_by(
        MusicEntry.updated_at.desc(), MusicEntry.id.desc()).limit(500).all()
    songs, seen = [], set()
    for row in rows:
        song = Song.model_validate_json(row.song)
        if song.key not in seen:
            songs.append(song.model_dump()); seen.add(song.key)
    return {'name': 'jackfei的歌单', 'owner': 'jackfei', 'songs': songs}


class ListName(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    model_config = {'extra': 'forbid'}
    @field_validator('name')
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError('请输入名称')
        return value.strip()


@router.post('/lists', status_code=201)
def create_list(body: ListName, response: Response, db: Session = Depends(get_db), user=Depends(get_current_user)):
    private(response)
    if db.query(MusicList).filter_by(user_id=user.id).count() >= 32:
        raise HTTPException(409, '歌单数量达到上限')
    row = MusicList(user_id=user.id, name=body.name, kind='playlist'); db.add(row); db.commit()
    return dict(id=row.id, name=row.name, kind=row.kind, songs=[])


@router.put('/lists/{list_id}')
def rename_list(list_id: int, body: ListName, response: Response, db: Session = Depends(get_db), user=Depends(get_current_user)):
    private(response); row = owned_list(db, list_id, user.id)
    if row.kind != 'playlist':
        raise HTTPException(409, '系统歌单保留名称')
    row.name = body.name; db.commit(); return {'ok': True}


@router.delete('/lists/{list_id}')
def delete_list(list_id: int, response: Response, db: Session = Depends(get_db), user=Depends(get_current_user)):
    private(response); row = owned_list(db, list_id, user.id)
    if row.kind != 'playlist':
        raise HTTPException(409, '系统歌单请清空内容')
    db.query(MusicEntry).filter_by(list_id=list_id).delete(); db.delete(row); db.commit(); return {'ok': True}


@router.put('/lists/{list_id}/songs')
def save_song(list_id: int, song: Song, response: Response, db: Session = Depends(get_db), user=Depends(get_current_user)):
    private(response); row = owned_list(db, list_id, user.id)
    entry = db.query(MusicEntry).filter_by(list_id=list_id, song_key=song.key).first()
    if not entry:
        count = db.query(MusicEntry).filter_by(list_id=list_id).count()
        if count >= 500 and row.kind != 'history':
            raise HTTPException(409, '一个歌单最多 500 首歌')
        entry = MusicEntry(list_id=list_id, song_key=song.key)
        db.add(entry)
    entry.song = song.model_dump_json(); entry.updated_at = datetime.utcnow()
    db.flush()
    if row.kind == 'history':
        old = [e.id for e in db.query(MusicEntry.id).filter_by(list_id=list_id).order_by(MusicEntry.updated_at.desc(), MusicEntry.id.desc()).offset(100)]
        if old:
            db.query(MusicEntry).filter(MusicEntry.id.in_(old)).delete(synchronize_session=False)
    db.commit(); return {'ok': True}


@router.delete('/lists/{list_id}/songs')
def remove_song(list_id: int, response: Response, key: str = Query(default='', max_length=220), db: Session = Depends(get_db), user=Depends(get_current_user)):
    private(response); owned_list(db, list_id, user.id)
    query = db.query(MusicEntry).filter_by(list_id=list_id)
    if key:
        query = query.filter_by(song_key=key)
    query.delete(); db.commit(); return {'ok': True}
