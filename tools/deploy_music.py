"""Backed-up music release; verified defaults are seeded before publishing HTML."""
import json
from pathlib import Path
import subprocess
import sys
import deploy_study

FILES = [
    'backend/main.py', 'backend/routers/admin.py', 'backend/routers/music.py',
    'backend/music_models.py', 'backend/music_http.py', 'backend/music_worker.py', 'backend/music_runtime.cjs',
    'frontend/src/App.jsx', 'frontend/src/pages/Music.jsx',
    'frontend/src/music/api.js', 'frontend/src/music/logic.js', 'frontend/src/music/store.js',
    'frontend/src/music/controller.js', 'frontend/src/music/MusicHost.jsx',
    'frontend/src/music/PlayerEngine.jsx', 'frontend/src/music/PlayerBar.jsx',
    'frontend/src/music/Sources.jsx', 'frontend/src/music/music.css',
]


def release(stage, verified):
    if not str(verified.resolve()).startswith('/tmp/hzf-study-music-'):
        raise RuntimeError('Unexpected verified source directory')
    defaults = json.loads(verified.read_text())
    if len(defaults) != 10 or not any(s['enabled'] for s in defaults):
        raise RuntimeError('No verified default playback source')
    subprocess.run(['docker', 'image', 'inspect', 'hzf-music-node:20261002'], check=True, stdout=subprocess.DEVNULL)
    dropin = Path('/etc/systemd/system/hzf-blog.service.d/90-music.conf')
    before = dropin.read_bytes() if dropin.exists() else None
    dropin.parent.mkdir(parents=True, exist_ok=True)
    dropin.write_text('[Service]\nEnvironment="MUSIC_SANDBOX=docker"\n')
    subprocess.run(['systemctl', 'daemon-reload'], check=True)
    original_health = deploy_study.health

    def after_health(paths):
        original_health(paths)
        sys.path.insert(0, str(deploy_study.ROOT / 'backend'))
        from database import SessionLocal
        from music_models import MusicSource
        with SessionLocal() as db:
            for item in defaults:
                if not db.query(MusicSource).filter_by(digest=item['digest']).first():
                    db.add(MusicSource(**item))
            db.commit()
        print('VERIFIED_DEFAULTS_SEEDED', flush=True)

    deploy_study.health = after_health
    try:
        deploy_study.release(stage, FILES, required_paths=('/api/music/search', '/api/music/resolve', '/api/music/library', '/api/admin/users', '/api/media/videos'))
    except BaseException:
        if before is None:
            dropin.unlink(missing_ok=True)
        else:
            dropin.write_bytes(before)
        subprocess.run(['systemctl', 'daemon-reload'], check=False)
        subprocess.run(['systemctl', 'restart', 'hzf-blog.service'], check=False)
        raise
    finally:
        deploy_study.health = original_health


if __name__ == '__main__':
    release(Path(sys.argv[1]), Path(sys.argv[2]))
