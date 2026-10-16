"""Guarded frontend defaults and narrowly scoped production source settings."""
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
from urllib.request import Request, urlopen

from deploy_study import ROOT, atomic_copy, release
from audit_music_sources import mp3_duration

EXPECTED = {
    'frontend/src/pages/Music.jsx': 'c737d0cb711d4ca7d77276ebd876ed602bd8bc7db0d530ca7c60a15f663fb6da',
    'frontend/src/music/store.js': '521b00c35c53e499b59cd132310b86d8fabde4e2a46d1abde4e5b4916bf34664',
    'frontend/src/music/labels.js': 'fd71e054618e792ddd3601decddd7c094d91c77f299a892be30ee5df0fcc365b',
}
DB = ROOT / 'backend/blog.db'
OLD_SETTINGS = [(5, '长青', 1, 24), (10, '全豆要', 1, 29)]
NEW_SETTINGS = [(5, '长青', 1, 0), (10, '全豆要', 0, 29)]


def settings(db):
    return db.execute('select id,name,enabled,position from music_sources where id in (5,10) order by id').fetchall()


def update_settings(expected, desired):
    with sqlite3.connect(DB, timeout=10) as db:
        db.execute('BEGIN IMMEDIATE')
        if settings(db) != expected:
            raise RuntimeError('Music settings changed concurrently; manual review required')
        for source_id, name, enabled, position in desired:
            cursor = db.execute('update music_sources set enabled=?,position=? where id=? and name=?',
                                (enabled, position, source_id, name))
            if cursor.rowcount != 1:
                raise RuntimeError('Unexpected source row count')


def verify_playback():
    song = dict(source='kg', id='0D7E8C11C961A17EB8779FEB0CA772E3', name='枫', singer='周杰伦',
                album='十一月的萧邦', duration=275, pic_id='', lyric_id='0D7E8C11C961A17EB8779FEB0CA772E3')
    request = Request('http://127.0.0.1:8001/api/music/resolve',
                      data=json.dumps(dict(song=song, quality='128k')).encode(),
                      headers={'Content-Type': 'application/json'})
    with urlopen(request, timeout=35) as response:
        result = json.load(response)
    if result.get('source_id') != 5 or not result.get('url', '').startswith('/api/music/stream/'):
        raise RuntimeError('Unexpected playback source')
    request = Request('http://127.0.0.1:8001' + result['url'], headers={'Range': 'bytes=0-65535'})
    with urlopen(request, timeout=25) as response:
        if response.status != 206 or not response.headers.get('Content-Type', '').startswith('audio/'):
            raise RuntimeError('Playback verification did not return ranged audio')
        total = int(response.headers.get('Content-Range', '').rsplit('/', 1)[-1])
        blob = response.read(65536)
    duration = mp3_duration(blob, total).get('duration_seconds', 0)
    if len(blob) != 65536 or not 260 <= duration <= 290:
        raise RuntimeError('Playback duration or audio bytes differ from the verified original')
    print(json.dumps(dict(event='PLAYBACK_OK', source_id=5, quality='128k',
                          audio_bytes=total, duration_seconds=duration)), flush=True)


def deploy(stage):
    for name, digest in EXPECTED.items():
        if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != digest:
            raise RuntimeError(f'Live file changed since inspection: {name}')
    with sqlite3.connect(f'file:{DB}?mode=ro', uri=True) as db:
        if settings(db) != OLD_SETTINGS:
            raise RuntimeError('Live source settings differ from the inspected baseline')
        capabilities = json.loads(db.execute('select capabilities from music_sources where id=5').fetchone()[0])
        if 'musicUrl' not in capabilities.get('kg', {}).get('actions', []):
            raise RuntimeError('Preferred source lacks the required capability')
    pid = subprocess.check_output(['systemctl', 'show', 'hzf-blog.service', '-p', 'MainPID', '--value'], text=True).strip()
    backup = release(stage, files=list(EXPECTED), required_paths=(
        '/api/music/search', '/api/music/resolve', '/api/music/recommended',
    ), restart_backend=False)
    changed = False
    try:
        update_settings(OLD_SETTINGS, NEW_SETTINGS)
        changed = True
        verify_playback()
        current_pid = subprocess.check_output(['systemctl', 'show', 'hzf-blog.service', '-p', 'MainPID', '--value'], text=True).strip()
        if pid != current_pid:
            raise RuntimeError('Backend PID changed during deployment')
        print('MUSIC_DEFAULTS_OK; backend PID unchanged', flush=True)
    except Exception:
        try:
            if changed:
                update_settings(NEW_SETTINGS, OLD_SETTINGS)
        finally:
            for name in EXPECTED:
                atomic_copy(backup / name, ROOT / name)
            atomic_copy(backup / 'frontend/dist/index.html', ROOT / 'frontend/dist/index.html')
        print('MUSIC_DEFAULTS_ROLLED_BACK; user data retained', flush=True)
        raise


if __name__ == '__main__':
    deploy(Path(sys.argv[1]))
