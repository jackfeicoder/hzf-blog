"""Targeted CSS-only release, preserving backend and music runtime state."""
from pathlib import Path
import argparse
import io
import json
import subprocess
import tarfile
from deploy_music_reliability import ROOT, normalized_hash, state_fingerprint
from deploy_study import release

FILES = ['frontend/src/music/music.css']


def pack():
    local = Path(__file__).resolve().parents[1]
    names = subprocess.check_output(['git', 'ls-tree', '-r', '--name-only', '521bfb6', 'frontend/src'], cwd=local, text=True).splitlines()
    baseline = {name: normalized_hash(subprocess.check_output(['git', 'show', '521bfb6:' + name], cwd=local)) for name in names}
    paths = [local / name for name in FILES] + list((local / 'frontend/dist').rglob('*'))
    paths += [local / 'tools' / name for name in ('publish_player_layers.py', 'deploy_study.py', 'deploy_music_reliability.py')]
    with tarfile.open(local / '.local-history/player-layers.tar.gz', 'w:gz') as bundle:
        for path in paths:
            if path.is_file(): bundle.add(path, arcname=path.relative_to(local), recursive=False)
        for name, payload in {
            'baseline.json': json.dumps(baseline).encode(),
            'backend/tests/test_frontend_package.py': b'import unittest\nfrom pathlib import Path\nclass PackageTests(unittest.TestCase):\n def test_player_layers_packaged(self):\n  root=Path(__file__).resolve().parents[2]\n  css=(root/"frontend/src/music/music.css").read_text()\n  self.assertIn(".music-player-bar { z-index:55; }",css)\n  self.assertIn(".music-queue-popover { z-index:56; }",css)\n  self.assertTrue((root/"frontend/dist/index.html").is_file())\n',
        }.items():
            info = tarfile.TarInfo(name); info.size = len(payload); bundle.addfile(info, io.BytesIO(payload))
    print('PACKED_PLAYER_LAYERS')


def publish(stage):
    for name, digest in json.loads((stage / 'baseline.json').read_text()).items():
        if normalized_hash((ROOT / name).read_bytes()) != digest:
            raise RuntimeError('Production changed: ' + name)
    before = state_fingerprint()
    release(stage, files=FILES, required_paths=('/api/health',), restart_backend=False)
    assert before == state_fingerprint(), 'Inspect concurrent runtime changes'
    print('PLAYER_LAYERS_RELEASE_OK')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('mode', choices=['pack', 'release']); parser.add_argument('stage', nargs='?')
    args = parser.parse_args()
    pack() if args.mode == 'pack' else publish(Path(args.stage))
