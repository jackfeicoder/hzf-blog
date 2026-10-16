"""Backend-only, baseline-guarded persistent address / daily visitor release."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tarfile

ROOT = Path('/www/wwwroot/blog.120115.xyz')
BASELINE = {
    'backend/music_playback.py': '63e4b227b366d9209c29394bef4f219de518a9bc34e814234900791160384bd1',
    'backend/routers/music.py': 'ecb2432cd36636b07b11644238f89d1a2eb95f0ab6c29094ac9787f076831a72',
    'backend/music_routing.py': '7393eb82f5dfeb0ce7df5c968337372c0738fb291315a1ffa0fc539e0df64c9e',
    'backend/models.py': 'a4662f8ff8cf4cf09d396c5e5133c814d86adf120c45164ffe8375cb0d7b3357',
    'backend/routers/visitors.py': '2448a1e786f46caed89983d7874115de68bb2abfe2c7fadd1a0f7d3475ff5125',
}


def pack():
    local = Path(__file__).resolve().parents[1]
    archive = local / '.local-history/persistent-visits-release.tar.gz'
    paths = list((local/'backend').glob('*.py')) + list((local/'backend/routers').glob('*.py'))
    paths += list((local/'backend/tests').glob('test_*.py'))
    paths += [local/'backend/music_runtime.cjs']
    paths += [local/'tools'/name for name in ('deploy_persistent_visits.py', 'deploy_study.py', 'deploy_music_reliability.py', 'check_music_live_cache.py')]
    archive.parent.mkdir(exist_ok=True)
    with tarfile.open(archive, 'w:gz') as bundle:
        for path in sorted(set(paths)):
            bundle.add(path, arcname=path.relative_to(local), recursive=False)
    print(archive)


def sqlite_backup(source, destination):
    with sqlite3.connect('file:' + str(source) + '?mode=ro', uri=True) as db:
        with sqlite3.connect(destination) as target:
            db.backup(target)
    os.chmod(destination, 0o600)


def release(stage):
    from deploy_study import atomic_copy, health
    from deploy_music_reliability import state_fingerprint
    stage = stage.resolve(strict=True)
    if stage.parent != Path('/tmp') or not stage.name.startswith('hzf-study-persistent-visits-'):
        raise RuntimeError('Unexpected staging directory')
    for name, digest in BASELINE.items():
        if hashlib.sha256((ROOT/name).read_bytes()).hexdigest() != digest:
            raise RuntimeError('Production source changed: ' + name)
        if not (stage/name).is_file():
            raise RuntimeError('Missing staged source: ' + name)
    index_hash = hashlib.sha256((ROOT/'frontend/dist/index.html').read_bytes()).hexdigest()
    before = state_fingerprint()
    # Test complete staged backend before touching live code. Test fixtures use
    # disposable databases, including the new persistent address store.
    subprocess.run([str(ROOT/'backend/venv/bin/python'), '-m', 'unittest', 'discover',
                    '-s', 'tests', '-p', 'test_*.py'], cwd=stage/'backend', check=True)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    backup = ROOT/'.deploy-backups'/('persistent-visits-' + stamp)
    backup.mkdir(parents=True, mode=0o700)
    os.chmod(backup.parent, 0o700)
    for name in BASELINE:
        destination = backup/name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT/name, destination)
    sqlite_backup(ROOT/'backend/blog.db', backup/'blog.db')
    runtime_backup = backup/'runtime'
    runtime_backup.mkdir(mode=0o700)
    for name in ('music-routing.sqlite3', 'music-addresses.sqlite3'):
        source = ROOT/'backend/.runtime'/name
        if source.is_file():
            sqlite_backup(source, runtime_backup/name)
    print('BACKUP=' + str(backup), flush=True)
    try:
        for name in BASELINE:
            atomic_copy(stage/name, ROOT/name)
        subprocess.run(['systemctl', 'restart', 'hzf-blog.service'], check=True)
        health(('/api/music/resolve', '/api/music/feedback', '/api/visitors', '/api/appearance'))
        with sqlite3.connect('file:' + str(ROOT/'backend/blog.db') + '?mode=ro', uri=True) as db:
            assert db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='visit_days'").fetchone()
        after = state_fingerprint()
        assert before['sources'] == after['sources'] and before['appearance'] == after['appearance']
        assert hashlib.sha256((ROOT/'frontend/dist/index.html').read_bytes()).hexdigest() == index_hash
        print('RUNTIME_CONFIG_PRESERVED=' + json.dumps(after), flush=True)
        print('PERSISTENT_VISITS_RELEASE_OK', flush=True)
    except Exception:
        for name in BASELINE:
            atomic_copy(backup/name, ROOT/name)
        subprocess.run(['systemctl', 'restart', 'hzf-blog.service'], check=False)
        print('APPLICATION_ROLLED_BACK; additive table and live data retained', flush=True)
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['pack', 'release'])
    parser.add_argument('stage', nargs='?')
    args = parser.parse_args()
    pack() if args.mode == 'pack' else release(Path(args.stage))
