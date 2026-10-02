"""Small backed-up release: public jackfei favorites and labeled player controls."""
from pathlib import Path
import sys
from deploy_study import release

FILES = [
    'backend/routers/music.py', 'frontend/src/pages/Music.jsx',
    'frontend/src/music/PlayerBar.jsx', 'frontend/src/music/controller.js',
    'frontend/src/music/music.css',
]

if __name__ == '__main__':
    release(Path(sys.argv[1]), files=FILES, required_paths=(
        '/api/music/recommended', '/api/music/library', '/api/music/resolve',
    ))
