"""Publish a verified frontend-only refinement; no backend restart/data changes."""
from datetime import datetime, timezone
from pathlib import Path
import shutil
import sys
from deploy_study import ROOT, atomic_copy


def publish(stage):
    stage = stage.resolve(strict=True)
    if not str(stage).startswith('/tmp/hzf-study-music-ui-') or not (stage / 'frontend/dist/index.html').is_file():
        raise RuntimeError('Unexpected frontend staging directory')
    backup = ROOT / '.deploy-backups' / ('music-ui-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
    backup.mkdir(mode=0o700)
    shutil.copytree(ROOT / 'frontend/dist', backup / 'dist')
    shutil.copy2(ROOT / 'frontend/src/pages/Music.jsx', backup / 'Music.jsx')
    try:
        atomic_copy(stage / 'frontend/src/pages/Music.jsx', ROOT / 'frontend/src/pages/Music.jsx')
        for source in (stage / 'frontend/dist').rglob('*'):
            if source.is_file() and source.name != 'index.html':
                atomic_copy(source, ROOT / 'frontend/dist' / source.relative_to(stage / 'frontend/dist'))
        atomic_copy(stage / 'frontend/dist/index.html', ROOT / 'frontend/dist/index.html')
    except BaseException:
        atomic_copy(backup / 'Music.jsx', ROOT / 'frontend/src/pages/Music.jsx')
        atomic_copy(backup / 'dist/index.html', ROOT / 'frontend/dist/index.html')
        raise
    print('UI_RELEASE_OK; BACKUP=' + str(backup))


if __name__ == '__main__':
    publish(Path(sys.argv[1]))
