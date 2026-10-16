"""Read-only, sequential playback audit using the production LX sandbox.

Run on the blog host. Never enables a source or exports scripts, keys or URLs.
"""
import asyncio
import argparse
import json
import os
from pathlib import Path
import sqlite3
import sys
import time
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import urlopen

ROOT = Path('/www/wwwroot/blog.120115.xyz/backend')
PLATFORMS = ('wy', 'tx', 'kw', 'kg', 'mg')
ALIASES = dict(wy='小云', tx='小Q', kw='小酷', kg='小狗', mg='小咪')


def emit(event):
    print(json.dumps(event, ensure_ascii=False), flush=True)


def mp3_duration(blob, total):
    """Read bounded MPEG frame metadata; no playback URLs or audio are saved."""
    start = 10 + sum((blob[6+i] & 127) << (21-7*i) for i in range(4)) if blob.startswith(b'ID3') else 0
    for pos in range(start, min(len(blob)-4, start+12000)):
        a, b, c, _ = blob[pos:pos+4]
        if a != 255 or b & 224 != 224 or ((b >> 1) & 3) != 1: continue
        version, bitrate_index, sample_index = (b >> 3) & 3, c >> 4, (c >> 2) & 3
        if version == 1 or bitrate_index in (0, 15) or sample_index == 3: continue
        sample_rate = [44100, 48000, 32000][sample_index] / (1 if version == 3 else 2 if version == 2 else 4)
        rates = [0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320] if version == 3 else [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160]
        bitrate = rates[bitrate_index]
        frame_size = int((144000 if version == 3 else 72000) * bitrate / sample_rate) + ((c >> 1) & 1)
        for tag in (b'Xing', b'Info'):
            offset = blob.find(tag, pos+4, pos+frame_size)
            if offset >= 0 and int.from_bytes(blob[offset+4:offset+8], 'big') & 1:
                frames = int.from_bytes(blob[offset+8:offset+12], 'big')
                return dict(duration_seconds=round(frames * (1152 if version == 3 else 576) / sample_rate, 2), duration_method=tag.decode())
        return dict(estimated_duration_seconds=round((total-start) * 8 / (bitrate * 1000), 2), duration_method='CBR estimate')
    return {}


def original(song):
    # Never treat a cover, fan-channel artist, or a short clip as the original.
    return (song.get('name', '').strip() == '枫'
            and song.get('singer', '').strip() == '周杰伦'
            and (not song.get('duration') or 260 <= song['duration'] <= 290))


async def audit(source_ids=None):
    sys.path.insert(0, str(ROOT))
    os.environ['MUSIC_SANDBOX'] = 'docker'
    import music_worker
    from music_http import fetch, open_http
    from music_search import platform_search

    observations = []
    def observed_fetch(url, options=None):
        trace = observations
        try:
            data = fetch(url, options)
            body = data['body']
            observation = {'status': data['statusCode'], 'body_type': type(body).__name__}
            if isinstance(body, dict):
                for key in ('code', 'status', 'success'):
                    value = body.get(key)
                    if isinstance(value, (int, bool)):
                        observation[key] = value
                message = str(body.get('message') or body.get('msg') or body.get('error') or '')
                for label, words in [('credential_required', ('key', 'token', '密钥', '鉴权', '授权')),
                                     ('payment_required', ('付费', '会员', '余额', '充值')),
                                     ('rate_limited', ('频繁', '限流', 'rate limit'))]:
                    if any(word in message.lower() for word in words): observation['category'] = label
            trace.append(observation)
            return data
        except Exception as error:
            trace.append({'error_type': type(error).__name__})
            raise
    music_worker.fetch = observed_fetch

    async def metadata(url, options=None):
        data = await asyncio.to_thread(fetch, url, options)
        if data['statusCode'] != 200: raise ValueError('metadata_http_error')
        return data['body']

    samples = {}
    for platform in PLATFORMS:
        started = time.monotonic()
        try:
            url = 'http://127.0.0.1:8001/api/music/search?' + urlencode(dict(q='枫 周杰伦', source=platform))
            def search():
                with urlopen(url, timeout=14) as response: return json.load(response)
            payload = await asyncio.to_thread(search)
            songs = [song for song in payload['items'] if original(song)]
            # Native metadata can supplement the first 20 results, but do not
            # manufacture IDs or use a cover as proof of original playback.
            if not songs and platform == 'wy':
                data = await metadata('https://music.163.com/api/search/get?' + urlencode(dict(s='枫 周杰伦', type=1, limit=100, offset=0)))
                candidates = data.get('result', {}).get('songs', []) if isinstance(data, dict) else []
                songs = [dict(source='wy', id=str(r['id']), name=r['name'], singer=' / '.join(a['name'] for a in r.get('artists', [])),
                              album=r.get('album', {}).get('name', ''), duration=r.get('duration', 0) / 1000)
                         for r in candidates if isinstance(r, dict)]
                songs = [song for song in songs if original(song)]
            if not songs and platform == 'kw':
                data = await metadata('http://search.kuwo.cn/r.s?' + urlencode(dict(client='kt', all='枫 周杰伦', pn=0, rn=100, ft='music', encoding='utf8', rformat='json', vermerge=1, mobi=1)))
                songs = [dict(source='kw', id=str(r.get('MUSICRID', '')).removeprefix('MUSIC_'), name=r.get('SONGNAME') or r.get('NAME') or '',
                              singer=r.get('ARTIST', ''), album=r.get('ALBUM', ''), duration=float(r.get('DURATION') or 0))
                         for r in data.get('abslist', []) if isinstance(r, dict)]
                songs = [song for song in songs if original(song)]
            if songs: samples[platform] = songs[0]
            emit(dict(event='search', platform=platform, label=ALIASES[platform], original_found=bool(songs),
                      sample=songs[0] if songs else None, seconds=round(time.monotonic() - started, 2)))
        except Exception as error:
            emit(dict(event='search', platform=platform, original_found=False, error_type=type(error).__name__))

    with sqlite3.connect(f'file:{ROOT}/blog.db?mode=ro', uri=True) as db:
        rows = db.execute('select id,name,script,enabled,position from music_sources order by position,id').fetchall()
    if source_ids: rows = [row for row in rows if row[0] in source_ids]
    results = []
    for source_id, name, script, enabled, position in rows:
        observations = []
        started = time.monotonic()
        emit(dict(event='probe_start', source_id=source_id, name=name, enabled=bool(enabled)))
        try:
            async with asyncio.timeout(18):
                capabilities = (await music_worker.run_source(script, name)).get('capabilities') or {}
            emit(dict(event='probe', source_id=source_id, ok=True, platforms=list(capabilities), seconds=round(time.monotonic() - started, 2)))
        except Exception as error:
            result = dict(event='probe', source_id=source_id, name=name, ok=False, error_type=type(error).__name__,
                          seconds=round(time.monotonic() - started, 2), upstream=list(observations))
            results.append(result); emit(result); continue
        for platform in PLATFORMS:
            if platform not in capabilities or 'musicUrl' not in capabilities[platform].get('actions', []): continue
            if platform not in samples:
                result = dict(event='playback', source_id=source_id, name=name, platform=platform, status='no_original_metadata')
                results.append(result); emit(result); continue
            song = samples[platform]
            info = dict(song, songmid=song['id'], hash=song['id'], albumName=song.get('album', ''))
            observations = []; started = time.monotonic(); stage = 'resolve'
            emit(dict(event='playback_start', source_id=source_id, platform=platform))
            try:
                async with asyncio.timeout(20):
                    data = await music_worker.run_source(script, name, 'musicUrl', platform, dict(type='128k', musicInfo=info))
                    stage = 'audio'
                    def check():
                        response, connection, _ = open_http(data.get('result'), headers={'Range': 'bytes=0-65535'})
                        try:
                            kind = response.getheader('Content-Type', '').lower()
                            content_range = response.getheader('Content-Range', '')
                            blob = response.read(65536)
                            total = int(content_range.rsplit('/', 1)[-1]) if '/' in content_range else int(response.getheader('Content-Length', '0'))
                            valid = response.status in (200, 206) and len(blob) > 1024 and not ('text/' in kind or 'json' in kind)
                            valid = valid and (kind.startswith('audio/') or blob.startswith((b'ID3', b'fLaC', b'OggS', b'RIFF', b'\xff')) or blob[4:8] == b'ftyp')
                            return dict(valid=valid, http_status=response.status, content_type=kind, bytes_read=len(blob), content_range=content_range,
                                        **(mp3_duration(blob, total) if valid else {}))
                        finally: response.close(); connection.close()
                    audio = await asyncio.to_thread(check)
                result = dict(event='playback', source_id=source_id, name=name, platform=platform,
                              status='audio_verified' if audio['valid'] else 'invalid_audio', **audio)
            except Exception as error:
                result = dict(event='playback', source_id=source_id, name=name, platform=platform,
                              status=stage + '_failed', error_type=type(error).__name__)
            result.update(seconds=round(time.monotonic() - started, 2), upstream=list(observations))
            results.append(result); emit(result)
    emit(dict(event='summary', sources_tested=len(rows), originals_found=list(samples),
              verified=[dict(source_id=r['source_id'], name=r['name'], platform=r['platform']) for r in results if r.get('status') == 'audio_verified'],
              database_modified=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-id', action='append', type=int, choices=range(1, 31))
    args = parser.parse_args()
    asyncio.run(audit(args.source_id))
