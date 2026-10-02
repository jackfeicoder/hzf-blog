"""Guarded frontend-only music fallback release; retain backend PID and data."""
import hashlib
from pathlib import Path
import sys
from deploy_study import ROOT, release

EXPECTED = {
    'frontend/src/music/api.js': 'b2ea098275c38ac3f64250de87013b6a4589ac7b2e4b5efa9ac925a6bfc4f1c2',
    'frontend/src/music/controller.js': '465b9e448107eb7436c6e06712a139da5020dc8abc0669971a03712a1a2c8bb2',
    'frontend/src/pages/Music.jsx': 'b6a450483b64f9f0c8ae25265da52c93e52978020670c570cf023450b52fd36d',
}
FILES = [*EXPECTED, 'frontend/src/music/search.js']

if __name__ == '__main__':
    for name, digest in EXPECTED.items():
        if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != digest:
            raise RuntimeError(f'Live file changed since inspection: {name}')
    if (ROOT / 'frontend/src/music/search.js').exists():
        raise RuntimeError('Unexpected existing search helper')
    release(Path(sys.argv[1]), files=FILES, required_paths=(
        '/api/music/search', '/api/music/resolve', '/api/music/recommended',
    ), restart_backend=False)
