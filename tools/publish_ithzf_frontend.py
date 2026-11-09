"""Frontend-only filing footer release, using the existing backup/rollback helper."""
from pathlib import Path
import argparse
import io
import json
import subprocess
import tarfile
from deploy_music_reliability import ROOT, normalized_hash, state_fingerprint
from deploy_study import release

FILES = ['frontend/src/components/Layout.jsx', 'frontend/src/index.css', 'frontend/src/siteInfo.js']


def pack():
    local = Path(__file__).resolve().parents[1]
    names = subprocess.check_output(['git', 'ls-tree', '-r', '--name-only', '7d5be38', 'frontend/src'], cwd=local, text=True).splitlines()
    baseline = {name: normalized_hash(subprocess.check_output(['git', 'show', '7d5be38:' + name], cwd=local)) for name in names}
    baseline['frontend/src/siteInfo.js'] = None
    paths = [local / name for name in FILES]
    paths += list((local / 'frontend/dist').rglob('*'))
    paths += [local / 'tools' / name for name in ('publish_ithzf_frontend.py', 'deploy_study.py', 'deploy_music_reliability.py')]
    with tarfile.open(local / '.local-history/ithzf-frontend.tar.gz', 'w:gz') as bundle:
        for path in paths:
            if path.is_file():
                bundle.add(path, arcname=path.relative_to(local), recursive=False)
        for name, payload in {
            'baseline.json': json.dumps(baseline).encode(),
            'backend/tests/test_frontend_package.py': b'import unittest\nfrom pathlib import Path\nclass PackageTests(unittest.TestCase):\n def test_footer_is_packaged(self):\n  root=Path(__file__).resolve().parents[2]\n  self.assertTrue((root/"frontend/dist/index.html").is_file())\n  self.assertIn("beian.miit.gov.cn", (root/"frontend/src/siteInfo.js").read_text())\n',
        }.items():
            info = tarfile.TarInfo(name); info.size = len(payload)
            bundle.addfile(info, io.BytesIO(payload))
    print('PACKED_ITHZF_FRONTEND')


def publish(stage):
    for name, digest in json.loads((stage / 'baseline.json').read_text()).items():
        path = ROOT / name
        if (digest is None and path.exists()) or (digest is not None and normalized_hash(path.read_bytes()) != digest):
            raise RuntimeError('Production changed: ' + name)
    before = state_fingerprint()
    release(stage, files=FILES, required_paths=('/api/health',), restart_backend=False)
    assert before == state_fingerprint(), 'Runtime data changed; inspect concurrent activity'
    print('ITHZF_FOOTER_RELEASE_OK')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('mode', choices=['pack', 'release']); parser.add_argument('stage', nargs='?')
    args = parser.parse_args()
    pack() if args.mode == 'pack' else publish(Path(args.stage))
