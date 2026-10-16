"""Targeted welcome/biography release; archive contains no credentials or DB."""
import argparse
from pathlib import Path
import tarfile

FILES = [
    'backend/schemas.py', 'backend/public_identity.py',
    'frontend/src/App.jsx', 'frontend/src/AuthContext.jsx',
    'frontend/src/components/Layout.jsx', 'frontend/src/components/BioText.jsx',
    'frontend/src/components/bio-text.css', 'frontend/src/bioLinks.js',
    'frontend/src/pages/Profile.jsx', 'frontend/src/pages/Welcome.jsx',
    'frontend/src/pages/welcome.css', 'frontend/src/welcome/policy.js',
    'frontend/src/welcome/WelcomeGate.jsx',
]


def pack():
    local = Path(__file__).resolve().parents[1]
    archive = local / '.local-history/welcome-release.tar.gz'
    archive.parent.mkdir(exist_ok=True)
    paths = [local / name for name in FILES]
    paths += list((local / 'backend').glob('*.py'))
    paths += list((local / 'backend/routers').glob('*.py'))
    # The local site-key AI feature has not been released. Keep its router
    # unchanged and exclude that feature's tests from production checks.
    paths += [p for p in (local / 'backend/tests').glob('test_*.py')
              if p.name != 'test_chat_config.py']
    paths += list((local / 'frontend/dist').rglob('*'))
    paths += [Path(__file__).resolve(), local / 'tools/deploy_study.py',
              local / 'tools/verify_welcome.py']
    with tarfile.open(archive, 'w:gz') as bundle:
        for path in sorted(set(paths)):
            if path.is_file():
                bundle.add(path, arcname=path.relative_to(local), recursive=False)
    print(archive)


def release(stage):
    from deploy_study import release as deploy
    stage = stage.resolve(strict=True)
    if stage.parent != Path('/tmp') or not stage.name.startswith('hzf-study-welcome-'):
        raise RuntimeError('Unexpected staging path')
    deploy(stage, files=FILES, required_paths=(
        '/api/users/{username}', '/api/auth/register', '/api/appearance',
        '/api/music/search', '/api/upload/image',
    ))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['pack', 'release'])
    parser.add_argument('stage', nargs='?')
    args = parser.parse_args()
    pack() if args.mode == 'pack' else release(Path(args.stage))
