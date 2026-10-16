"""Targeted visitor-privacy release; no secrets or database in the archive."""
import argparse
from pathlib import Path
import tarfile

FILES = [
    'backend/routers/visitors.py', 'frontend/src/App.jsx',
    'frontend/src/components/Layout.jsx', 'frontend/src/components/AdminOnly.jsx',
    'frontend/src/navigation.js',
]


def pack():
    root = Path(__file__).resolve().parents[1]
    archive = root / '.local-history/visitors-release.tar.gz'
    archive.parent.mkdir(exist_ok=True)
    paths = [root / name for name in FILES]
    paths += list((root / 'backend').glob('*.py'))
    paths += list((root / 'backend/routers').glob('*.py'))
    paths += list((root / 'backend/tests').glob('test_*.py'))
    paths += list((root / 'frontend/dist').rglob('*'))
    paths += [Path(__file__).resolve(), root / 'tools/deploy_study.py']
    with tarfile.open(archive, 'w:gz') as bundle:
        for path in sorted(set(paths)):
            if path.is_file():
                bundle.add(path, arcname=path.relative_to(root), recursive=False)
    print(archive)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['pack', 'release'])
    parser.add_argument('stage', nargs='?')
    args = parser.parse_args()
    if args.mode == 'pack':
        pack()
    else:
        from deploy_study import release
        stage = Path(args.stage).resolve(strict=True)
        if stage.parent != Path('/tmp') or not stage.name.startswith('hzf-study-visitors-'):
            raise RuntimeError('Unexpected visitor staging directory')
        release(stage, files=FILES, required_paths=('/api/visitors', '/api/chat/providers', '/api/appearance'))
