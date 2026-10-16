import asyncio
from collections import OrderedDict, deque
from datetime import datetime
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import secrets
import sqlite3
import time
from typing import Literal
from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse, FileResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from auth import get_current_user, require_superadmin
from database import get_db
from music_models import MusicEntry, MusicList, MusicSource
from music_http import fetch, open_http, target
from music_search import platform_search
from music_worker import run_source
from music_routing import RoutingStore, choose_quality, same_recording, route_key
from music_playback import AudioCache, SingleFlight, SourceCooling, url_key, health_key
from music_files import MusicFiles
from models import User

router = APIRouter(prefix='/api/music', tags=['music'])
PLATFORMS = {'wy': 'netease', 'tx': 'tencent', 'kw': 'kuwo', 'kg': 'kugou', 'mg': 'migu'}
GD = 'https://music-api.gdstudio.xyz/api.php'
CACHE = OrderedDict()
TICKETS = OrderedDict()
LIMITS = OrderedDict()
UPSTREAM = asyncio.Semaphore(6)
STREAMS = asyncio.Semaphore(8)
ROUTING = RoutingStore()
AUDIO_CACHE = AudioCache(path=Path(__file__).resolve().parents[1] / '.runtime' / 'music-addresses.sqlite3')
URL_FLIGHTS = SingleFlight()
SOURCE_COOLING = SourceCooling()
FILE_CACHE = MusicFiles(enabled=os.getenv('MUSIC_FILE_CACHE', '1') == '1')
logger = logging.getLogger('uvicorn.error')


def observation(context, stage, status, reason='', started=None):
    elapsed = int((time.monotonic() - started) * 1000) if started else 0
    try:
        ROUTING.record(context, stage, status, reason, elapsed)
    except Exception:
        logger.warning('music_routing_store_unavailable')
    # No URLs, tokens, scripts, credentials or listener identity in logs.
    logger.info('music_event %s', json.dumps(dict(song=context.get('title'), source_id=context['source_id'],
                platform=context['song']['source'], stage=stage, status=status, reason=reason, elapsed_ms=elapsed), ensure_ascii=False))


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
        response.headers['Cache-Control'] = 'public, max-age=60'
        return result
    try:
        async with asyncio.timeout(10):
            if source != 'wy':
                data = await platform_search(upstream, source, q.strip(), page)
            else:
                try:
                    async with asyncio.timeout(2.5):
                        data = await platform_search(upstream, source, q.strip(), page)
                except Exception:
                    data = await upstream(GD + '?' + urlencode(dict(types='search', source=PLATFORMS[source], name=q.strip(), count=20, pages=page)))
                    if not isinstance(data, list):
                        raise ValueError('搜索格式异常')
        if not isinstance(data, list):
            raise ValueError('搜索格式异常')
        items = []
        for row in data[:20]:
            if not isinstance(row, dict):
                continue
            try:
                artist = row.get('artist', [])
                song = Song(source=source, id=str(row.get('id', '')), name=row.get('name', ''),
                            singer=' / '.join(artist) if isinstance(artist, list) else str(artist),
                            album=row.get('album', ''), pic_id=str(row.get('pic_id') or ''), lyric_id=str(row.get('lyric_id') or ''), duration=row.get('duration', 0))
                if not any(item['id'] == song.id for item in items):
                    items.append(song.model_dump())
            except (ValueError, TypeError):
                continue
        response.headers['Cache-Control'] = 'public, max-age=60'
        try:
            await asyncio.to_thread(FILE_CACHE.catalogue, items)
        except (OSError, ValueError, sqlite3.Error):
            pass
        return remember(key, dict(items=items, page=page, has_more=len(data) == 20))
    except Exception:
        raise HTTPException(502, '该平台搜索暂时没有响应，请切换平台或稍后重试', headers={'Cache-Control': 'no-store'})


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
        value = {'lyric': str(data.get('lyric') or '')[:100000], 'translation': str(data.get('tlyric') or '')[:100000]}
        # Empty/non-timed metadata is not a usable lyric and must not stay for an hour.
        return remember(key, value, 3600 if has_lyrics(value) else 15)
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
def sources(response: Response, db: Session = Depends(get_db), user=Depends(require_superadmin)):
    private(response)
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
    attempted: list[Annotated[str, Field(max_length=250)]] = Field(default_factory=list, max_length=60)
    refresh_token: str = Field(default='', max_length=100, pattern=r'^[a-zA-Z0-9_\-]*$')
    allow_platform_fallback: bool = True
    model_config = {'extra': 'forbid'}


def ticket(url, source_id, name, context=None):
    now = time.monotonic()
    if context is not None:
        context['audio_url'] = url
    token = secrets.token_urlsafe(32)
    TICKETS[token] = (now + 1800, url, context)
    while len(TICKETS) > 500:
        TICKETS.popitem(last=False)
    return {'url': '/api/music/stream/' + token, 'source_id': source_id, 'source_name': name, 'expires_in': 1800,
            **({'playback_song': context['song'], 'quality': context['quality']} if context else {})}


def has_lyrics(data):
    return bool(re.search(r'\[\d{1,3}:\d{2}(?:[.:]\d{1,3})?\]', data.get('lyric') or ''))


async def recording_matches(song, request, platforms):
    key = ('recordings', song.key, song.name, song.singer, tuple(platforms))
    value = cached(key)
    if value is not None:
        return value
    if not song.singer:
        return []
    matches = []
    async def find(platform):
        try:
            async with asyncio.timeout(4):
                result = await search(request, Response(), q=(song.name+' '+song.singer)[:100], source=platform, page=1)
            candidates = [row for row in result['items'] if same_recording(song.model_dump(), row)]
            if candidates:
                return candidates[0]
        except Exception:
            pass
    values = await asyncio.gather(*(find(p) for p in platforms[:2]))
    matches = [v for v in values if v]
    return remember(key, matches, 1800 if matches else 15)


class LyricResolve(BaseModel):
    song: Song
    playback_song: Song | None = None
    model_config = {'extra': 'forbid'}


@router.post('/lyrics/resolve')
async def resolve_lyrics(body: LyricResolve, request: Request, response: Response):
    private(response)
    candidates = [body.song]
    if body.playback_song and body.playback_song.key != body.song.key and same_recording(body.song.model_dump(), body.playback_song.model_dump()):
        candidates.insert(0, body.playback_song)
    try:
        async with asyncio.timeout(14):
            for candidate in candidates:
                try:
                    async with asyncio.timeout(4):
                        data = await lyrics(request, source=candidate.source, id=candidate.lyric_id or candidate.id)
                except TimeoutError:
                    continue
                if has_lyrics(data):
                    return {**data, 'source': candidate.source, 'song_id': candidate.id}
            alternatives = await recording_matches(body.song, request, [p for p in ('wy', 'kg', 'tx') if p not in {s.source for s in candidates}])
            for row in alternatives:
                candidate = Song.model_validate(row)
                try:
                    async with asyncio.timeout(3):
                        data = await lyrics(request, source=candidate.source, id=candidate.lyric_id or candidate.id)
                    if has_lyrics(data):
                        return {**data, 'source': candidate.source, 'song_id': candidate.id}
                except TimeoutError:
                    continue
    except TimeoutError:
        pass
    return {'lyric': '', 'translation': '', 'source': body.song.source, 'song_id': body.song.id}


@router.get('/diagnostics')
def diagnostics(response: Response, user=Depends(require_superadmin)):
    private(response)
    return ROUTING.diagnostics()


def failed_stream(context, reason):
    if context and context.get('file_id'):
        return
    if context and not context.get('failed'):
        context['failed'] = True
        AUDIO_CACHE.discard(url_key(context['source_id'], context['digest'], context['song']['source']+':'+context['song']['id'], context['quality']), context.get('audio_url'))
        SOURCE_COOLING.failed(health_key(context['source_id'], context['digest'], context['song']['source'], context['quality']), context['song_key'])
        observation(context, 'stream_error', 'failed', reason)


class PlaybackFeedback(BaseModel):
    token: str = Field(min_length=20, max_length=100, pattern=r'^[a-zA-Z0-9_\-]+$')
    event: Literal['playing', 'error', 'stalled']
    model_config = {'extra': 'forbid'}


@router.post('/feedback', status_code=204)
def playback_feedback(body: PlaybackFeedback, request: Request, response: Response):
    limit(request, 'feedback', 60)
    private(response)
    value = TICKETS.get(body.token)
    context = value[2] if value and value[0] > time.monotonic() else None
    if not context:
        return
    if context.get('file_id'):
        # Browser-side network stalls do not prove a complete local file is bad.
        if body.event == 'error':
            FILE_CACHE.invalidate(context['file_id'], context.get('file_checksum'))
        return
    # Browser feedback never promotes unverified URLs or globally penalizes a source.
    if body.event == 'playing' and context.get('ready') and not context.get('reported_playing'):
        context['reported_playing'] = True
        observation(context, 'playing', 'ok')
    elif body.event != 'playing' and not context.get('reported_error'):
        context['reported_error'] = True
        AUDIO_CACHE.discard(url_key(context['source_id'], context['digest'], context['song']['source']+':'+context['song']['id'], context['quality']), context.get('audio_url'))
        SOURCE_COOLING.failed(health_key(context['source_id'], context['digest'], context['song']['source'], context['quality']), context['song_key'])
        observation(context, 'playback_error', 'failed', body.event)


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
    limit(request, 'resolve-any', 120); private(response)
    refresh_ticket = TICKETS.get(body.refresh_token)
    local_refresh = refresh_ticket and refresh_ticket[0] > time.monotonic() and refresh_ticket[2] and refresh_ticket[2].get('file_id') and refresh_ticket[2].get('song_key') == body.song.key
    if not local_refresh:
        try:
            local = FILE_CACHE.get(body.song.model_dump(), body.quality)
            if not local and body.quality == '128k':
                local = FILE_CACHE.get(body.song.model_dump(), '320k')
        except (OSError, ValueError, sqlite3.Error):
            local = None
        if local:
            context = dict(file_id=local['id'], file_checksum=local['checksum'], song_key=body.song.key, song=local['song'], quality=local['quality'],
                           requested_quality=body.quality, source_id=0, digest='', ready=False)
            return {**ticket('', 0, '本机缓存', context), 'cache_hit': True, 'file_cache_hit': True, 'attempted': []}
    limit(request, 'resolve', 20)
    rows = db.query(MusicSource).filter_by(enabled=True).order_by(MusicSource.position, MusicSource.id).all()
    if not rows:
        raise HTTPException(503, '没有可用音源，请联系管理员导入并启用音源')
    attempted = list(dict.fromkeys(body.attempted))
    candidates = [body.song]
    preferred = ROUTING.preferred(body.song.key, body.quality)
    if preferred and not any(s.id == preferred['source_id'] and s.digest == preferred['digest'] for s in rows):
        preferred = None
    if preferred:
        remembered = Song.model_validate_json(preferred['song'])
        if remembered.key != body.song.key and same_recording(body.song.model_dump(), remembered.model_dump()):
            candidates.insert(0, remembered)
    refresh = TICKETS.get(body.refresh_token)
    refresh_context = refresh[2] if refresh and refresh[0] > time.monotonic() else None
    if refresh_context and not any(s.id == refresh_context['source_id'] and s.digest == refresh_context['digest'] for s in rows):
        refresh_context = None
    if refresh_context and refresh_context['song_key'] != body.song.key:
        refresh_context = None
    if refresh_context and refresh_context['song_key'] == body.song.key:
        candidates.insert(0, Song.model_validate(refresh_context['song']))
    deadline = time.monotonic() + 27
    exhausted, tried_candidates = True, set()
    fresh_attempts = cooling_skipped = globally_skipped = 0
    cooling_waits = []

    async def attempt(candidate):
        nonlocal exhausted, fresh_attempts, cooling_skipped, globally_skipped
        eligible = [s for s in rows if candidate.source in json.loads(s.capabilities)
                    and 'musicUrl' in json.loads(s.capabilities)[candidate.source].get('actions', [])
                    and not (candidate.source == body.song.source and s.id in body.exclude)]
        preferred_id = refresh_context['source_id'] if refresh_context and candidate.key == refresh_context['song']['source']+':'+refresh_context['song']['id'] else (preferred['source_id'] if preferred else None)
        eligible = ROUTING.ranked(eligible, candidate.model_dump(), body.quality, preferred_id, body.song.key)
        if refresh_context:
            eligible.sort(key=lambda s: s.id != preferred_id)
        else:
            # Reuse a known address before paying for another script/container.
            eligible.sort(key=lambda s: AUDIO_CACHE.get(url_key(s.id, s.digest, candidate.key, choose_quality(json.loads(s.capabilities)[candidate.source], body.quality))) is None)
        for row in eligible:
            actual_quality = choose_quality(json.loads(row.capabilities)[candidate.source], body.quality)
            route = route_key(row.id, candidate.model_dump(), actual_quality)
            if route in attempted:
                continue
            remaining = deadline - time.monotonic()
            if remaining < 2:
                exhausted = False
                return None
            attempted.append(route)
            context = dict(song_key=body.song.key, title=body.song.name, singer=body.song.singer,
                           source_id=row.id, source_name=row.name, digest=row.digest, song=candidate.model_dump(),
                           quality=actual_quality, requested_quality=body.quality, original_song=body.song.model_dump(), ready=False)
            supported = json.loads(row.capabilities)[candidate.source].get('qualitys', [])
            context['cacheable'] = actual_quality == next((q for q in ('128k', '320k', 'flac', 'flac24bit') if q in supported), '128k')
            key = url_key(row.id, row.digest, candidate.key, actual_quality)
            source_key = health_key(row.id, row.digest, candidate.source, actual_quality)
            force = bool(refresh_context and row.id == refresh_context['source_id'] and candidate.key == refresh_context['song']['source'] + ':' + refresh_context['song']['id'])
            if force:
                AUDIO_CACHE.discard(key)
            url = AUDIO_CACHE.get(key)
            if not force and not url and SOURCE_COOLING.blocked(source_key, body.song.key):
                cooling_skipped += 1
                globally_skipped += int(SOURCE_COOLING.globally_blocked(source_key))
                cooling_waits.append(SOURCE_COOLING.retry_after(source_key, body.song.key))
                continue
            started = time.monotonic()
            try:
                cache_hit = bool(url)
                async with asyncio.timeout(min(11, remaining)):
                    if not url:
                        fresh_attempts += 1
                        # Capture loop locals: the shared task may outlive its caller.
                        async def fresh(row=row, candidate=candidate, actual_quality=actual_quality, key=key, source_key=source_key):
                            try:
                                async with asyncio.timeout(10):
                                    info = candidate.model_dump()
                                    info.update(songmid=candidate.id, hash=candidate.id, albumName=candidate.album)
                                    data = await run_source(row.script, row.name, 'musicUrl', candidate.source, dict(type=actual_quality, musicInfo=info))
                                    value = await asyncio.to_thread(check_audio, data.get('result'))
                                    AUDIO_CACHE.put(key, value)
                                    SOURCE_COOLING.succeeded(source_key, body.song.key)
                                    return value
                            except Exception:
                                SOURCE_COOLING.failed(source_key, body.song.key)
                                raise
                        url = await URL_FLIGHTS.run(key, fresh)
                    observation(context, 'resolved', 'ok', started=started)
                    return {**ticket(url, row.id, row.name, context), 'attempted': attempted, 'cache_hit': cache_hit}
            except Exception as error:
                observation(context, 'resolve_error', 'failed', type(error).__name__, started)
        return None

    async def primary():
        for candidate in candidates:
            if candidate.key in tried_candidates:
                continue
            tried_candidates.add(candidate.key)
            result = await attempt(candidate)
            if result:
                return result

    async def backup():
        nonlocal exhausted
        # Warm/cache hits finish before this delay: no speculative lookup then.
        await asyncio.sleep(4 if preferred or refresh_context else 1.2)
        if deadline - time.monotonic() < 5:
            exhausted = False
            return
        alternatives = await recording_matches(body.song, request, [p for p in ('wy', 'kg', 'tx', 'kw', 'mg') if p not in {s.source for s in candidates} and any(p in json.loads(r.capabilities) for r in rows)])
        for matched in alternatives:
            candidate = Song.model_validate(matched)
            if candidate.key not in tried_candidates:
                tried_candidates.add(candidate.key)
                result = await attempt(candidate)
                if result:
                    return result

    if body.allow_platform_fallback and body.song.singer:
        tasks = {asyncio.create_task(primary()), asyncio.create_task(backup())}
        pending = tasks.copy()
        try:
            while pending:
                done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
                results = [task.result() for task in done]
                for result in results:
                    if result:
                        return result
        finally:
            for task in tasks:
                if not task.done(): task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
    else:
        result = await primary()
        if result:
            return result
    if not fresh_attempts and cooling_skipped:
        retry_after = max(1, min(cooling_waits))
        raise HTTPException(503, detail={'message': f'音源连续失败，正在短暂冷却，约 {retry_after} 秒后可重试或换个平台', 'cooldown': globally_skipped == cooling_skipped, 'retry_after': retry_after},
                            headers={'Retry-After': str(retry_after), 'Cache-Control': 'no-store'})
    raise HTTPException(502, detail={'message': '本次可用音源未返回音频，已尝试换源；请稍后重试',
                                    'attempted': attempted, 'continue': not exhausted}, headers={'Cache-Control': 'no-store'})


@router.get('/stream/{token}')
async def stream(token: str, request: Request):
    value = TICKETS.get(token)
    if not value or value[0] < time.monotonic():
        TICKETS.pop(token, None)
        raise HTTPException(410, '播放地址已过期，请重新播放')
    limit(request, 'stream', 60)
    context = value[2]
    if context and not context.get('file_id'):
        try:
            complete = await asyncio.to_thread(FILE_CACHE.get, context.get('original_song', context['song']), context['quality'])
            if complete:
                context['file_id'] = complete['id']
                context['file_checksum'] = complete['checksum']
        except (OSError, ValueError, sqlite3.Error):
            pass
    if context and context.get('file_id'):
        local = FILE_CACHE.by_id(context['file_id'], pin=True)
        if not local:
            raise HTTPException(410, '本机缓存已更新，请重新播放')
        outgoing = {'Cache-Control': 'private, max-age=2592000', 'X-Content-Type-Options': 'nosniff',
                    'X-Music-Cache': 'HIT', 'ETag': '"' + local['checksum'] + '"'}
        if os.getenv('MUSIC_CACHE_ACCEL') == '1':
            outgoing['X-Accel-Redirect'] = '/_music_cache/' + local['id'] + '.audio'
            return Response(media_type=local['mime'], headers=outgoing)
        return FileResponse(FILE_CACHE.path(local['id']), media_type=local['mime'], headers=outgoing)
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
    failure_reason = 'stream_open_failed'
    try:
        r = c = None
        r, c, _ = await asyncio.to_thread(open_http, value[1], 'GET', headers, None, 10)
        if r.status not in (200, 206) or 'text/' in r.getheader('Content-Type', '') or 'json' in r.getheader('Content-Type', '') or int(r.getheader('Content-Length', '0')) > 100 * 1024 * 1024:
            failure_reason = f'http_{r.status}' if r.status not in (200, 206) else 'non_audio_response'
            r.close(); c.close()
            raise ValueError()
        first = await asyncio.to_thread(r.read1, 512)
        # Probe success is not stream success: validate the actual transfer, too.
        if not first or first.lstrip().startswith((b'{', b'<', b'[')):
            failure_reason = 'empty_or_invalid_audio'
            r.close(); c.close()
            raise ValueError('Invalid audio transfer')
    except Exception:
        if r:
            r.close()
        if c:
            c.close()
        STREAMS.release()
        failed_stream(value[2], failure_reason)
        raise HTTPException(502, '音频源响应异常')
    context = value[2]
    if context and not context.get('ready'):
        context['ready'] = True
        SOURCE_COOLING.succeeded(health_key(context['source_id'], context['digest'], context['song']['source'], context['quality']), context['song_key'])
        observation(context, 'stream_ready', 'ok')
        # Best effort, independent of this listener's connection and seek range.
        # Never enqueue a byte-range fragment as a completed song.
        if context.get('cacheable', True):
            FILE_CACHE.enqueue(context.get('original_song', context['song']), context['quality'], value[1])
    async def chunks():
        total = len(first)
        try:
            async with asyncio.timeout(600):
                yield first
                while total < 100 * 1024 * 1024:
                    chunk = await asyncio.to_thread(r.read1, min(65536, 100 * 1024 * 1024 - total))
                    if not chunk:
                        expected = int(r.getheader('Content-Length', '0'))
                        if expected and total < expected:
                            failed_stream(context, 'truncated_audio')
                        break
                    total += len(chunk)
                    yield chunk
        except Exception as error:
            failed_stream(context, type(error).__name__)
            raise
        finally:
            r.close(); c.close(); STREAMS.release()
    outgoing = {'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff'}
    for h in ('Content-Length', 'Content-Range', 'Accept-Ranges'):
        if r.getheader(h):
            outgoing[h] = r.getheader(h)
    return StreamingResponse(chunks(), status_code=r.status, media_type=r.getheader('Content-Type', 'audio/mpeg'), headers=outgoing)


@router.get('/file-cache')
def file_cache_summary(response: Response, user=Depends(require_superadmin)):
    private(response)
    return FILE_CACHE.summary()


@router.delete('/file-cache/{identifier}', status_code=204)
def remove_cached_file(identifier: str, response: Response, user=Depends(require_superadmin)):
    private(response)
    if not re.fullmatch(r'[a-f0-9]{64}', identifier):
        raise HTTPException(422, '无效缓存编号')
    if not FILE_CACHE.remove(identifier):
        raise HTTPException(409, '这首歌最近正在播放，请稍后清除缓存')


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
    return {'name': '管理员的歌单', 'owner': 'administrator', 'songs': songs}


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
