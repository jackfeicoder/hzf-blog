"""Targeted backed-up release for private source management and platform aliases."""
from pathlib import Path
import sys
from deploy_study import release

FILES = ['backend/routers/music.py', 'frontend/src/pages/Music.jsx',
         'frontend/src/music/Sources.jsx', 'frontend/src/music/PlayerBar.jsx',
         'frontend/src/music/labels.js']

if __name__ == '__main__':
    release(Path(sys.argv[1]), files=FILES, required_paths=(
        '/api/music/sources', '/api/music/search', '/api/music/resolve',
    ))
