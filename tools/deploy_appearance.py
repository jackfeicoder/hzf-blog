"""Targeted appearance release. No credentials or live DB in the archive."""
import argparse
import json
from pathlib import Path
import tarfile

FILES = ['backend/main.py', 'backend/models.py', 'backend/routers/appearance.py',
         'frontend/src/App.jsx', 'frontend/src/main.jsx', 'frontend/src/api.js',
         'frontend/src/components/Layout.jsx', 'frontend/src/appearance/settings.js',
         'frontend/src/appearance/AppearanceContext.jsx', 'frontend/src/appearance/AppearanceHost.jsx',
         'frontend/src/appearance/AppearanceSettings.jsx', 'frontend/src/appearance/appearance.css']


def pack():
    local = Path(__file__).resolve().parents[1]
    archive = local / '.local-history/appearance-release.tar.gz'
    archive.parent.mkdir(exist_ok=True)
    paths = [local / name for name in FILES]
    paths += list((local / 'backend').glob('*.py')) + list((local / 'backend/routers').glob('*.py'))
    # Production's AI router predates the local site-key feature. That router
    # is deliberately not part of this UI release. Its local-only tests are
    # excluded from production checks; all appearance/security/media tests run.
    paths += [p for p in (local / 'backend/tests').glob('test_*.py') if p.name != 'test_chat_config.py']
    paths += list((local / 'frontend/dist').rglob('*'))
    paths += [Path(__file__).resolve(), local / 'tools/deploy_study.py', local / 'tools/verify_appearance.py']
    with tarfile.open(archive, 'w:gz') as bundle:
        for path in sorted(set(paths)):
            if path.is_file():
                bundle.add(path, arcname=path.relative_to(local), recursive=False)
    print(archive)


def release(stage, frontend_only=False):
    from deploy_study import release as deploy
    stage = stage.resolve(strict=True)
    if stage.parent != Path('/tmp') or not stage.name.startswith('hzf-study-'):
        raise RuntimeError('Unexpected staging path')
    files = [name for name in FILES if name.startswith('frontend/src/')] if frontend_only else FILES
    backup = deploy(stage, files=files, required_paths=('/api/appearance', '/api/music/search', '/api/upload/image'), restart_backend=not frontend_only)
    (backup / 'appearance-result.json').write_text(json.dumps({'status':'RELEASE_OK','feature':'appearance'}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['pack','release'])
    parser.add_argument('stage', nargs='?')
    parser.add_argument('--frontend-only', action='store_true')
    args = parser.parse_args()
    pack() if args.mode == 'pack' else release(Path(args.stage), args.frontend_only)
