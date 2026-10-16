"""Read-only incident diagnostics, run via SSH stdin. No config/database writes.

Probe output contains status/categories only, never provider keys or media URLs.
"""
import asyncio
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import statistics
import sys
import time
from urllib.parse import urlsplit

ROOT = Path('/www/wwwroot/blog.120115.xyz/backend')


def emit(kind, **data):
    print(json.dumps({'event': kind, **data}, ensure_ascii=False), flush=True)


def read_summary():
    names = ('music_worker.py', 'music_runtime.cjs', 'music_http.py', 'routers/music.py',
             '../frontend/src/music/controller.js')
    emit('online_hashes', hashes={name: hashlib.sha256((ROOT / name).read_bytes().replace(b'\r\n', b'\n')).hexdigest() for name in names})
    with sqlite3.connect('file:' + str(ROOT / 'blog.db') + '?mode=ro', uri=True) as db:
        rows = db.execute('SELECT id,name,script,enabled,position,capabilities FROM music_sources ORDER BY position,id').fetchall()
        emit('sources', rows=[{'id': r[0], 'name': r[1], 'enabled': bool(r[3]), 'position': r[4], 'platforms': list(json.loads(r[5]))} for r in rows])
        samples = {}
        for (raw,) in db.execute('SELECT song FROM music_entries ORDER BY updated_at DESC'):
            song = json.loads(raw)
            if song.get('name') in ('爱错', 'Letting Go'):
                samples.setdefault(song['name'], song)
                if song.get('name') == '爱错' and song.get('singer') == '王力宏':
                    samples['爱错'] = song
        emit('samples', songs=[{'name': s['name'], 'singer': s.get('singer'), 'source': s['source'], 'id': s['id']} for s in samples.values()])
    path = ROOT / '.runtime/music-routing.sqlite3'
    with sqlite3.connect('file:' + str(path) + '?mode=ro', uri=True) as db:
        db.row_factory = sqlite3.Row
        events = [dict(r) for r in db.execute('SELECT * FROM events WHERE at>? ORDER BY id', (time.time() - 86400,))]
    emit('events_window', stored_count=len(events), reasons=dict(Counter(e['reason'] for e in events if e['status'] == 'failed')))
    groups = {}
    for e in events:
        key = (e['source_id'], e['source_name'], e['platform'], e['stage'], e['status'])
        groups.setdefault(key, []).append(e['elapsed_ms'])
    emit('events_groups', rows=[{'source_id': k[0], 'name': k[1], 'platform': k[2], 'stage': k[3], 'status': k[4], 'count': len(v), 'median_ms': statistics.median(v), 'max_ms': max(v)} for k, v in groups.items()])
    emit('songs_recent', songs=[{'name': title, 'failed_attempts': sum(e['status'] == 'failed' for e in events if e['title'] == title), 'resolved': sum(e['stage'] == 'resolved' for e in events if e['title'] == title), 'stream_ready': sum(e['stage'] == 'stream_ready' for e in events if e['title'] == title)} for title in dict.fromkeys(e['title'] for e in events)][-12:])
    return rows, samples


async def probe(rows, samples):
    sys.path.insert(0, str(ROOT))
    os.environ['MUSIC_SANDBOX'] = 'docker'
    import music_worker
    from music_http import fetch, open_http
    traces = []

    def observed_fetch(url, options=None):
        started = time.monotonic()
        options = options or {}
        trace = {'host': urlsplit(url).hostname, 'method': options.get('method', 'GET'), 'headers': list((options.get('headers') or {}).keys())}
        try:
            result = fetch(url, options)
            trace['http'] = result['statusCode']
            body = result['body']
            trace['body_type'] = type(body).__name__
            if isinstance(body, dict):
                trace['body_keys'] = list(body)[:12]
                trace['codes'] = {k: body[k] for k in ('code', 'status', 'success') if isinstance(body.get(k), (int, bool))}
                message = str(body.get('msg') or body.get('message') or body.get('error') or '').lower()
                for category, words in {'auth': ('token', 'key', '授权', '密钥', '鉴权'), 'rate_limit': ('频繁', '限流', 'rate limit'), 'missing': ('not found', '不存在', '找不到'), 'payment': ('付费', '充值', '余额', '会员')}.items():
                    if any(w in message for w in words): trace['category'] = category
            return result
        except Exception as error:
            trace['exception'] = type(error).__name__
            if isinstance(error, ValueError) and re.fullmatch(r'[\u4e00-\u9fff A-Za-z()]+', str(error)):
                trace['reason'] = str(error)[:80]
            raise
        finally:
            trace['seconds'] = round(time.monotonic() - started, 3)
            traces.append(trace)
    music_worker.fetch = observed_fetch

    async def attempt(row, song):
        traces.clear()
        emit('probe_start', source_id=row[0], title=song['name'], platform=song['source'])
        info = dict(song, songmid=song['id'], hash=song['id'], albumName=song.get('album', ''))
        start = time.monotonic()
        result = {'source_id': row[0], 'title': song['name'], 'platform': song['source']}
        try:
            diagnostic_prefix = '''
;(() => {
  console.group = console.groupEnd = console.groupCollapsed = () => {};
  const register = lx.on;
  lx.on = (event, fn) => register(event, event === lx.EVENT_NAMES.request ? async data => {
    try { return await fn(data) } catch (error) {
      const message = String(error.message || '');
      return { diagnostic: { kind: String(error.name || 'Error'),
        property: message.match(/reading ['"]([A-Za-z0-9_]+)['"]/)?.[1] || '',
        missing_function: message.match(/([A-Za-z_$][A-Za-z0-9_$.]*) is not a function/)?.[1] || '',
        missing_global: message.match(/([A-Za-z_$][A-Za-z0-9_$]*) is not defined/)?.[1] || '',
        native_argument: message.match(/The ["']([A-Za-z0-9_]+)["'] argument/)?.[1] || '',
        category: /key|token|授权|密钥|鉴权/i.test(message) ? 'auth' : /timeout|超时/i.test(message) ? 'timeout' : 'script_error' } };
    }
  } : fn);
})();
'''
            async with asyncio.timeout(18):
                data = await music_worker.run_source(diagnostic_prefix + row[2], row[1], 'musicUrl', song['source'], dict(type='128k', musicInfo=info))
            result['resolve_seconds'] = round(time.monotonic() - start, 3)
            url = data.get('result')
            result['url_type'] = type(url).__name__
            if isinstance(url, dict) and isinstance(url.get('diagnostic'), dict):
                result['script_error'] = url['diagnostic']
            if isinstance(url, str):
                result['media_host'] = urlsplit(url).hostname
                def check():
                    before = time.monotonic()
                    r, c, _ = open_http(url, headers={'Range': 'bytes=0-65535'}, timeout=8)
                    try:
                        first = r.read1(512)
                        first_seconds = time.monotonic() - before
                        total = len(first)
                        while total < 65536 and time.monotonic() - before < 12:
                            chunk = r.read1(min(65536 - total, 16384))
                            if not chunk: break
                            total += len(chunk)
                        return {'http': r.status, 'content_type': r.getheader('Content-Type', ''), 'first_seconds': round(first_seconds, 3), 'read_bytes': total, 'read_seconds': round(time.monotonic() - before, 3)}
                    finally: r.close(); c.close()
                result['audio'] = await asyncio.to_thread(check)
        except Exception as error:
            result['exception'] = type(error).__name__
        result.update(seconds=round(time.monotonic() - start, 3), trace=list(traces))
        emit('probe', **result)

    for title, ids in [('爱错', (2,))]:
        if title not in samples: continue
        for source_id in ids:
            row = next((r for r in rows if r[0] == source_id and r[3]), None)
            if row and samples[title]['source'] in json.loads(row[5]):
                await attempt(row, samples[title])


if __name__ == '__main__':
    rows, samples = read_summary()
    asyncio.run(probe(rows, samples))
