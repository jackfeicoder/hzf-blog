"""Publish only the media feature files using the existing backed-up release flow."""
from pathlib import Path
import sys

from deploy_study import release

FILES = [
    "backend/main.py", "backend/media_models.py", "backend/routers/media.py",
    "frontend/src/App.jsx", "frontend/src/api.js", "frontend/src/index.css",
    "frontend/src/components/Layout.jsx", "frontend/src/pages/Videos.jsx",
    "frontend/src/pages/Music.jsx", "frontend/src/pages/media.css",
]

if __name__ == "__main__":
    release(Path(sys.argv[1]), files=FILES, required_paths=("/api/media/videos", "/api/study/today"))
