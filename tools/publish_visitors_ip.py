"""Targeted visitor IP recording/display release with backups and rollback."""
from pathlib import Path
import argparse
import io
import json
import subprocess
import tarfile
from deploy_music_reliability import ROOT, normalized_hash, state_fingerprint
from deploy_study import release

FILES = ['backend/access_policy.py', 'backend/routers/visitors.py', 'frontend/src/api.js',
         'frontend/src/App.jsx', 'frontend/src/pages/Visitors.jsx', 'frontend/src/components/VisitTracker.jsx']


def pack():
    local = Path(__file__).resolve().parents[1]
    names = subprocess.check_output(['git', 'ls-tree', '-r', '--name-only', 'f7502cd', 'frontend/src'], cwd=local, text=True).splitlines()
    names += FILES[:2]
    baseline = {name: normalized_hash(subprocess.check_output(['git', 'show', 'f7502cd:' + name], cwd=local)) for name in names}
    baseline['frontend/src/components/VisitTracker.jsx'] = None
    paths = [local / name for name in FILES] + list((local / 'frontend/dist').rglob('*'))
    paths += list((local / 'backend/tests').glob('test_*.py')) + [local / 'backend/music_runtime.cjs']
    paths += [local / 'tools' / name for name in ('publish_visitors_ip.py', 'deploy_study.py', 'deploy_music_reliability.py')]
    with tarfile.open(local / '.local-history/visitors-ip.tar.gz', 'w:gz') as bundle:
        for path in paths:
            if path.is_file(): bundle.add(path, arcname=path.relative_to(local), recursive=False)
        payload = json.dumps(baseline).encode(); info = tarfile.TarInfo('baseline.json'); info.size = len(payload)
        bundle.addfile(info, io.BytesIO(payload))
    print('PACKED_VISITORS_IP')


def publish(stage):
    for name, digest in json.loads((stage / 'baseline.json').read_text()).items():
        path = ROOT / name
        if (digest is None and path.exists()) or (digest is not None and normalized_hash(path.read_bytes()) != digest):
            raise RuntimeError('Production changed: ' + name)
    before = state_fingerprint()
    release(stage, files=FILES, required_paths=('/api/visitors/track', '/api/visitors'))
    assert before == state_fingerprint(), 'Inspect concurrent runtime changes'
    print('VISITORS_IP_RELEASE_OK')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('mode', choices=['pack', 'release']); parser.add_argument('stage', nargs='?')
    args = parser.parse_args()
    pack() if args.mode == 'pack' else publish(Path(args.stage))
