"""Frontend-only seek fix; guard production against the pre-change Git snapshot."""
import argparse
import io
import json
from pathlib import Path
import subprocess
import tarfile

from deploy_music_reliability import normalized_hash, state_fingerprint

ROOT = Path('/www/wwwroot/blog.120115.xyz')
FILES = ['frontend/src/music/PlayerBar.jsx', 'frontend/src/music/controller.js',
         'frontend/src/music/seekGesture.js', 'frontend/src/music/compact.css',
         'frontend/src/components/Layout.jsx', 'frontend/src/components/NavigationLink.js']


def pack():
    local = Path(__file__).resolve().parents[1]
    baseline = {name: normalized_hash(subprocess.check_output(['git', 'show', 'HEAD:' + name], cwd=local)) for name in FILES[:-1]}
    baseline[FILES[-1]] = None  # New component must not overwrite an existing live file.
    paths = [local / name for name in FILES]
    paths += list((local / 'backend').glob('*.py')) + list((local / 'backend/routers').glob('*.py'))
    paths += list((local / 'backend/tests').glob('test_*.py')) + [local / 'backend/music_runtime.cjs']
    paths += list((local / 'frontend/dist').rglob('*'))
    paths += [local / 'tools' / name for name in ('deploy_music_seek.py', 'deploy_music_reliability.py', 'deploy_study.py')]
    archive = local / '.local-history/music-seek-release.tar.gz'
    with tarfile.open(archive, 'w:gz') as bundle:
        for path in sorted(set(paths)):
            if path.is_file():
                bundle.add(path, arcname=path.relative_to(local), recursive=False)
        payload = json.dumps(baseline).encode()
        entry = tarfile.TarInfo('baseline.json'); entry.size = len(payload)
        bundle.addfile(entry, io.BytesIO(payload))
    print(archive)


def release(stage):
    from deploy_study import release as publish
    stage = stage.resolve(strict=True)
    if stage.parent != Path('/tmp') or not stage.name.startswith('hzf-study-music-seek-'):
        raise RuntimeError('Unexpected staging directory')
    for name, digest in json.loads((stage / 'baseline.json').read_text()).items():
        target = ROOT / name
        if (digest is None and target.exists()) or (digest is not None and normalized_hash(target.read_bytes()) != digest):
            raise RuntimeError('Production source changed: ' + name)
    before = state_fingerprint()
    backup = publish(stage, files=FILES, restart_backend=False,
                     required_paths=('/api/music/resolve', '/api/music/file-cache', '/api/appearance'))
    after = state_fingerprint()
    assert before['sources'] == after['sources'] and before['appearance'] == after['appearance'], 'Live settings changed; inspect'
    print('RUNTIME_CONFIG_PRESERVED=' + json.dumps(after), flush=True)
    print('MUSIC_SEEK_RELEASE_OK; BACKUP=' + str(backup), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['pack', 'release'])
    parser.add_argument('stage', nargs='?')
    args = parser.parse_args()
    pack() if args.mode == 'pack' else release(Path(args.stage))
