"""Frontend-only follow-up; preserve active backend and audio streams."""
from pathlib import Path
import sys
from deploy_study import release

if __name__=='__main__':
    release(Path(sys.argv[1]),files=['frontend/src/music/controller.js'],restart_backend=False,
            required_paths=('/api/music/resolve','/api/music/diagnostics','/api/music/lyrics/resolve'))
