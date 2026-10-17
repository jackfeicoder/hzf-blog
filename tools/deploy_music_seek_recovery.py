"""Front-end-only, guarded seek/reconnect release; preserve all audio bytes."""
import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tarfile

from deploy_music_reliability import ROOT, normalized_hash, state_fingerprint

FILES = ['frontend/src/music/controller.js', 'frontend/src/music/playbackAddresses.js']


def pack():
    local = Path(__file__).resolve().parents[1]
    names = subprocess.check_output(['git', 'ls-files', 'frontend/src'], cwd=local, text=True).splitlines()
    baseline = {name: normalized_hash(subprocess.check_output(['git', 'show', 'HEAD:' + name], cwd=local)) for name in names}
    with tarfile.open(local / '.local-history/music-direct-cache-release.tar.gz') as previous:
        baseline['frontend/dist/index.html'] = normalized_hash(previous.extractfile('frontend/dist/index.html').read())
    paths = [local / name for name in FILES]
    paths += list((local / 'backend').glob('*.py')) + list((local / 'backend/routers').glob('*.py'))
    paths += list((local / 'backend/tests').glob('test_*.py')) + [local / 'backend/music_runtime.cjs']
    paths += list((local / 'frontend/dist').rglob('*'))
    paths += [local / 'tools' / name for name in ('deploy_music_seek_recovery.py', 'deploy_music_reliability.py', 'deploy_study.py')]
    archive = local / '.local-history/music-seek-recovery-release.tar.gz'
    with tarfile.open(archive, 'w:gz') as bundle:
        for path in sorted(set(paths)):
            if path.is_file(): bundle.add(path, arcname=path.relative_to(local), recursive=False)
        payload = json.dumps(baseline).encode(); entry = tarfile.TarInfo('baseline.json'); entry.size = len(payload)
        bundle.addfile(entry, io.BytesIO(payload))
    print(archive)


def audio_versions():
    result = {}
    for path in (ROOT / 'backend/.music-cache').glob('*.audio'):
        with path.open('rb') as source:
            result[path] = hashlib.file_digest(source, 'sha256').hexdigest()
    return result


def release(stage):
    from deploy_study import release as publish
    stage = stage.resolve(strict=True)
    if stage.parent != Path('/tmp') or not stage.name.startswith('hzf-study-music-seek-'):
        raise RuntimeError('Unexpected staging directory')
    for name, digest in json.loads((stage / 'baseline.json').read_text()).items():
        path = ROOT / name
        if not path.is_file() or normalized_hash(path.read_bytes()) != digest:
            raise RuntimeError('Production changed: ' + name)
    before, audio = state_fingerprint(), audio_versions()
    snapshot = ROOT / '.deploy-backups' / ('music-seek-runtime-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
    snapshot.mkdir(mode=0o700)
    for source in (ROOT / 'backend/.runtime').glob('*.sqlite3'):
        with sqlite3.connect('file:' + str(source) + '?mode=ro', uri=True) as origin:
            destination = snapshot / source.name
            with sqlite3.connect(destination) as target: origin.backup(target)
            os.chmod(destination, 0o600)
    print('RUNTIME_BACKUP=' + str(snapshot), flush=True)
    backup = publish(stage, files=FILES, restart_backend=False,
                     required_paths=('/api/music/cached', '/api/music/resolve', '/api/music/recommended', '/api/appearance'))
    after, current = state_fingerprint(), audio_versions()
    assert before['sources'] == after['sources'] and before['appearance'] == after['appearance'], 'Inspect runtime settings'
    assert all(current.get(path) == digest for path, digest in audio.items()), 'Inspect existing cache files'
    print('CACHE_FILES_CHECKSUMS_PRESERVED=' + str(len(audio)), flush=True)
    print('RUNTIME_CONFIG_PRESERVED=' + json.dumps(after), flush=True)
    print('MUSIC_SEEK_RECOVERY_RELEASE_OK; BACKUP=' + str(backup), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('mode', choices=['pack', 'release']); parser.add_argument('stage', nargs='?')
    args = parser.parse_args()
    pack() if args.mode == 'pack' else release(Path(args.stage))
