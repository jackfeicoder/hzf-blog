"""Guarded music caching/compatibility release with staged upstream verification."""
import argparse
import hashlib
import json
from pathlib import Path
import tarfile
from deploy_music_reliability import state_fingerprint

ROOT = Path('/www/wwwroot/blog.120115.xyz')
FILES = ['backend/music_worker.py','backend/music_runtime.cjs','backend/music_playback.py','backend/music_routing.py',
         'backend/music_search.py','backend/routers/music.py',
         'frontend/src/music/api.js','frontend/src/music/controller.js']
BASELINE = {
    'backend/music_worker.py':'bb50741c750b81ac5380d30a2c4e2662f10caec8e7ae446270883a59ba65b158',
    'backend/music_runtime.cjs':'0ff84c417203b952768d66c0757fb6b557198bd9e70951eeb622a057686cd810',
    'backend/routers/music.py':'dcb9c064dd6634948554c37edc9446e12e78d3de61361bee800b437407d2fd40',
    'frontend/src/music/controller.js':'0ed22b722f5ca88ec42bfb3fc411f68414e3523018f393dc56c0f127b26cd6a3',
    'backend/music_search.py':'ed289488ad974c47e2ad22db3fa2e1b87079d97a9270a710e5f3a6e821f460c5',
    'frontend/src/music/api.js':'2163ee4110a8390018167cd2774a401da04c73378a3dfd669730f1e7b390d344',
    'backend/music_routing.py':'06b0a49ab0284e68adc3ecaa0fdd1a68d2ba7c66bd4327e737ada9ec018707c4',
}


def pack():
    local = Path(__file__).resolve().parents[1]
    paths = [local / name for name in FILES]
    paths += list((local/'backend').glob('*.py')) + list((local/'backend/routers').glob('*.py'))
    paths += list((local/'backend/tests').glob('test_*.py')) + list((local/'frontend/dist').rglob('*'))
    paths += [local/'tools'/name for name in ('deploy_music_fast.py','deploy_music_reliability.py','deploy_study.py','verify_music_fast.py')]
    archive = local/'.local-history/music-fast-release.tar.gz'
    with tarfile.open(archive,'w:gz') as bundle:
        for path in sorted(set(paths)):
            if path.is_file(): bundle.add(path,arcname=path.relative_to(local),recursive=False)
    print(archive)


def release(stage):
    from deploy_study import release as publish
    stage = stage.resolve(strict=True)
    if stage.parent != Path('/tmp') or not stage.name.startswith('hzf-study-music-fast-'):
        raise RuntimeError('Unexpected staging directory')
    for name,digest in BASELINE.items():
        if hashlib.sha256((ROOT/name).read_bytes().replace(b'\r\n',b'\n')).hexdigest() != digest:
            raise RuntimeError('Production source changed: '+name)
    if (ROOT/'backend/music_playback.py').exists(): raise RuntimeError('Playback helper already exists')
    before = state_fingerprint()
    backup = publish(stage,files=FILES,required_paths=('/api/music/resolve','/api/music/lyrics/resolve','/api/music/diagnostics','/api/appearance'))
    after = state_fingerprint()
    assert before['sources'] == after['sources'] and before['appearance'] == after['appearance'], 'Live configuration changed; inspect'
    print('RUNTIME_CONFIG_PRESERVED='+json.dumps(after),flush=True)
    print('MUSIC_FAST_RELEASE_OK; BACKUP='+str(backup),flush=True)


if __name__ == '__main__':
    parser=argparse.ArgumentParser();parser.add_argument('mode',choices=['pack','release']);parser.add_argument('stage',nargs='?')
    args=parser.parse_args()
    pack() if args.mode=='pack' else release(Path(args.stage))
