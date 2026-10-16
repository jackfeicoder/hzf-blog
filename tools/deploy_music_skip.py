"""Guarded frontend-only automatic skip release, preserving live settings."""
import argparse
import hashlib
import json
from pathlib import Path
import tarfile
from deploy_music_reliability import state_fingerprint

ROOT = Path('/www/wwwroot/blog.120115.xyz')
FILES = ['frontend/src/music/controller.js', 'frontend/src/music/logic.js']
BASELINE = {
    FILES[0]: '76975588b7e5ee96cfe17295b59d25bc7afcc17d3a8241465901232ea0827fb2',
    FILES[1]: '35ae1f1b48b64883c3051c44880fe8168fbbea51e0542cb592c0dda0aadcd017',
}


def pack():
    local = Path(__file__).resolve().parents[1]
    paths = [local / name for name in FILES]
    paths += list((local / 'backend').glob('*.py')) + list((local / 'backend/routers').glob('*.py'))
    paths += list((local / 'backend/tests').glob('test_*.py')) + list((local / 'frontend/dist').rglob('*'))
    paths += [local / 'tools' / name for name in ('deploy_music_skip.py', 'deploy_music_reliability.py', 'deploy_study.py')]
    archive = local / '.local-history/music-skip-release.tar.gz'
    with tarfile.open(archive, 'w:gz') as bundle:
        for path in sorted(set(paths)):
            if path.is_file(): bundle.add(path, arcname=path.relative_to(local), recursive=False)
    print(archive)


def release(stage):
    from deploy_study import release as publish
    stage = stage.resolve(strict=True)
    if stage.parent != Path('/tmp') or not stage.name.startswith('hzf-study-music-skip-'):
        raise RuntimeError('Unexpected staging directory')
    for name, digest in BASELINE.items():
        if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != digest:
            raise RuntimeError('Production source changed: ' + name)
    before = state_fingerprint()
    backup = publish(stage, files=FILES, restart_backend=False,
                     required_paths=('/api/music/resolve', '/api/music/lyrics/resolve', '/api/appearance'))
    after = state_fingerprint()
    assert before['sources'] == after['sources'] and before['appearance'] == after['appearance'], 'Live settings changed; inspect'
    print('RUNTIME_CONFIG_PRESERVED=' + json.dumps(after), flush=True)
    print('MUSIC_SKIP_RELEASE_OK; BACKUP=' + str(backup), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('mode', choices=['pack', 'release']); parser.add_argument('stage', nargs='?')
    args = parser.parse_args()
    pack() if args.mode == 'pack' else release(Path(args.stage))
