"""Backed-up targeted release for platform search and the mobile lyric player."""
from pathlib import Path
import sys
from deploy_study import release

FILES = [
    'backend/routers/music.py', 'backend/music_search.py', 'backend/music_http.py',
    'frontend/src/pages/Music.jsx', 'frontend/src/music/PlayerBar.jsx',
    'frontend/src/music/store.js', 'frontend/src/music/api.js', 'frontend/src/music/logic.js', 'frontend/src/music/music.css',
]

if __name__ == '__main__':
    release(Path(sys.argv[1]), files=FILES, required_paths=(
        '/api/music/search', '/api/music/recommended', '/api/music/resolve',
    ))
