"""Publish only the dock UI; compare against the last deployed compact bundle."""
import argparse
import io
import json
from pathlib import Path
import tarfile
from deploy_music_reliability import normalized_hash, state_fingerprint

ROOT = Path('/www/wwwroot/blog.120115.xyz')
FILES = ['frontend/src/pages/Music.jsx', 'frontend/src/music/PlayerBar.jsx',
         'frontend/src/music/compact.css', 'frontend/src/music/playerDock.js']


def pack():
    local = Path(__file__).resolve().parents[1]
    with tarfile.open(local / '.local-history/music-compact-release.tar.gz') as previous:
        baseline = {name: normalized_hash(previous.extractfile(name).read()) for name in FILES[:3]}
    paths = [local / name for name in FILES]
    paths += list((local / 'backend').glob('*.py')) + list((local / 'backend/routers').glob('*.py'))
    paths += list((local / 'backend/tests').glob('test_*.py')) + list((local / 'frontend/dist').rglob('*'))
    paths += [local / 'tools' / name for name in ('deploy_music_dock.py', 'deploy_music_reliability.py', 'deploy_study.py')]
    archive = local / '.local-history/music-dock-release.tar.gz'
    with tarfile.open(archive, 'w:gz') as bundle:
        for path in sorted(set(paths)):
            if path.is_file(): bundle.add(path, arcname=path.relative_to(local), recursive=False)
        payload = json.dumps(baseline).encode()
        entry = tarfile.TarInfo('baseline.json'); entry.size = len(payload)
        bundle.addfile(entry, io.BytesIO(payload))
    print(archive)


def release(stage):
    from deploy_study import release as publish
    stage = stage.resolve(strict=True)
    if stage.parent != Path('/tmp') or not stage.name.startswith('hzf-study-music-dock-'):
        raise RuntimeError('Unexpected staging directory')
    for name, digest in json.loads((stage / 'baseline.json').read_text()).items():
        if normalized_hash((ROOT / name).read_bytes()) != digest:
            raise RuntimeError('Production source has changed: ' + name)
    if (ROOT / FILES[-1]).exists(): raise RuntimeError('Dock file already exists')
    before = state_fingerprint()
    backup = publish(stage, files=FILES, restart_backend=False,
                     required_paths=('/api/music/resolve', '/api/music/lyrics/resolve', '/api/appearance'))
    after = state_fingerprint()
    assert before['sources'] == after['sources'] and before['appearance'] == after['appearance'], 'Live settings changed; inspect'
    print('RUNTIME_CONFIG_PRESERVED=' + json.dumps(after), flush=True)
    print('MUSIC_DOCK_RELEASE_OK; BACKUP=' + str(backup), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('mode', choices=['pack', 'release']); parser.add_argument('stage', nargs='?')
    args = parser.parse_args()
    pack() if args.mode == 'pack' else release(Path(args.stage))
