"""Guarded backend-only cache-retention fix, with existing-file preservation audit."""
import argparse
import io
import json
from pathlib import Path
import sqlite3
import subprocess
import tarfile

from deploy_music_reliability import ROOT, normalized_hash, state_fingerprint

FILES = ['backend/routers/music.py']


def cache_state():
    base = ROOT / 'backend'
    with sqlite3.connect('file:' + str(base / '.runtime/music-files.sqlite3') + '?mode=ro',uri=True) as db:
        rows = db.execute('SELECT id,size,checksum FROM files').fetchall()
    return {identifier:(size,digest) for identifier,size,digest in rows
            if (base / '.music-cache' / (identifier+'.audio')).is_file()
            and (base / '.music-cache' / (identifier+'.audio')).stat().st_size == size}


def pack():
    local = Path(__file__).resolve().parents[1]
    baseline = {name:normalized_hash(subprocess.check_output(['git','show','HEAD:'+name],cwd=local)) for name in FILES}
    baseline['frontend/dist/index.html'] = normalized_hash((local / 'frontend/dist/index.html').read_bytes())
    paths = list((local / 'backend').glob('*.py')) + list((local / 'backend/routers').glob('*.py'))
    paths += list((local / 'backend/tests').glob('test_*.py')) + [local / 'backend/music_runtime.cjs']
    paths += list((local / 'frontend/dist').rglob('*'))
    paths += [local / 'tools' / name for name in ('deploy_music_cache_retention.py','deploy_music_reliability.py','deploy_study.py')]
    archive = local / '.local-history/music-cache-retention-release.tar.gz'
    with tarfile.open(archive,'w:gz') as bundle:
        for path in sorted(set(paths)):
            if path.is_file(): bundle.add(path,arcname=path.relative_to(local),recursive=False)
        payload=json.dumps(baseline).encode(); info=tarfile.TarInfo('baseline.json'); info.size=len(payload)
        bundle.addfile(info,io.BytesIO(payload))
    print(archive)


def release(stage):
    from deploy_study import release as publish
    stage = stage.resolve(strict=True)
    if stage.parent != Path('/tmp') or not stage.name.startswith('hzf-study-music-retain-'):
        raise RuntimeError('Unexpected staging directory')
    for name,digest in json.loads((stage/'baseline.json').read_text()).items():
        if normalized_hash((ROOT/name).read_bytes()) != digest: raise RuntimeError('Production changed: '+name)
    before, files_before = state_fingerprint(), cache_state()
    backup = publish(stage,files=FILES,required_paths=('/api/music/resolve','/api/music/feedback','/api/music/file-cache'))
    after, files_after = state_fingerprint(), cache_state()
    assert before['sources']==after['sources'] and before['appearance']==after['appearance'], 'Inspect settings'
    assert all(files_after.get(key)==value for key,value in files_before.items()), 'Inspect concurrent cache changes'
    print('CACHE_FILES_PRESERVED='+str(len(files_before)),flush=True)
    print('RUNTIME_CONFIG_PRESERVED='+json.dumps(after),flush=True)
    print('MUSIC_CACHE_RETENTION_RELEASE_OK; BACKUP='+str(backup),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('mode',choices=['pack','release']); parser.add_argument('stage',nargs='?')
    args=parser.parse_args(); pack() if args.mode=='pack' else release(Path(args.stage))
