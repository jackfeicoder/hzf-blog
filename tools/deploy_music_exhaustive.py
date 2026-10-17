"""Targeted exhaustive-routing release; preserve live settings and user data."""
import argparse
import io
import json
from pathlib import Path
import subprocess
import tarfile

from deploy_music_reliability import ROOT, normalized_hash, state_fingerprint

FILES = ['backend/music_candidates.py', 'backend/music_search.py', 'backend/music_worker.py',
         'backend/routers/music.py', 'frontend/src/music/retry.js', 'frontend/src/music/api.js',
         'frontend/src/music/controller.js']
NEW = {'backend/music_candidates.py', 'frontend/src/music/retry.js'}


def pack():
    local = Path(__file__).resolve().parents[1]
    baseline = {name: None if name in NEW else normalized_hash(subprocess.check_output(
        ['git', 'show', 'HEAD:' + name], cwd=local)) for name in FILES}
    # Last released build, not the new local build being published.
    with tarfile.open(local / '.local-history/music-lyrics-release.tar.gz') as old:
        baseline['frontend/dist/index.html'] = normalized_hash(old.extractfile('frontend/dist/index.html').read())
    paths = list((local / 'backend').glob('*.py')) + list((local / 'backend/routers').glob('*.py'))
    paths += list((local / 'backend/tests').glob('test_*.py')) + [local / 'backend/music_runtime.cjs']
    paths += [local / name for name in FILES] + list((local / 'frontend/dist').rglob('*'))
    paths += [local / 'tools' / name for name in ('deploy_music_exhaustive.py', 'verify_music_exhaustive_stage.py',
                                                'deploy_music_reliability.py', 'deploy_study.py')]
    archive = local / '.local-history/music-exhaustive-release.tar.gz'
    with tarfile.open(archive, 'w:gz') as bundle:
        for path in sorted(set(paths)):
            if path.is_file(): bundle.add(path, arcname=path.relative_to(local), recursive=False)
        data = json.dumps(baseline).encode()
        info = tarfile.TarInfo('baseline.json'); info.size = len(data)
        bundle.addfile(info, io.BytesIO(data))
    print(archive)


def release(stage):
    from deploy_study import release as publish
    stage = stage.resolve(strict=True)
    if stage.parent != Path('/tmp') or not stage.name.startswith('hzf-study-music-exhaustive-'):
        raise RuntimeError('Unexpected staging directory')
    for name, digest in json.loads((stage / 'baseline.json').read_text()).items():
        target = ROOT / name
        if (digest is None and target.exists()) or (digest is not None and normalized_hash(target.read_bytes()) != digest):
            raise RuntimeError('Production source changed: ' + name)
    before = state_fingerprint()
    backup = publish(stage, files=FILES, required_paths=('/api/music/resolve', '/api/music/lyrics/resolve', '/api/appearance'))
    after = state_fingerprint()
    assert before['sources'] == after['sources'] and before['appearance'] == after['appearance'], 'Inspect live settings'
    print('RUNTIME_CONFIG_PRESERVED=' + json.dumps(after), flush=True)
    print('MUSIC_EXHAUSTIVE_RELEASE_OK; BACKUP=' + str(backup), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['pack', 'release']); parser.add_argument('stage', nargs='?')
    args = parser.parse_args()
    pack() if args.mode == 'pack' else release(Path(args.stage))
