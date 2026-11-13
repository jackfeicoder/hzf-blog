"""Backed-up CDT traffic-counter correction and daily read-only sync."""
from datetime import datetime, timezone
from pathlib import Path
import argparse
import io
import json
import os
import shutil
import subprocess
import tarfile
from deploy_music_reliability import ROOT, normalized_hash, state_fingerprint
from deploy_study import release

FILES = ['backend/cdt_usage.py', 'backend/routers/visitors.py', 'frontend/src/api.js',
         'frontend/src/pages/Visitors.jsx', 'frontend/src/components/VisitorTraffic.jsx',
         'frontend/src/components/visitor-traffic.css']
NEW = ()
UNITS = ('hzf-cdt-usage.service', 'hzf-cdt-usage.timer')


def pack():
    local = Path(__file__).resolve().parents[1]
    names = subprocess.check_output(['git', 'ls-tree', '-r', '--name-only', 'd49c5f3', 'frontend/src'], cwd=local, text=True).splitlines()
    names += ['backend/routers/visitors.py', 'backend/cdt_usage.py']
    baseline = {name: normalized_hash(subprocess.check_output(['git', 'show', 'd49c5f3:' + name], cwd=local)) for name in names}
    baseline.update({name: None for name in NEW})
    paths = [local / name for name in FILES] + list((local / 'frontend/dist').rglob('*'))
    paths += list((local / 'backend/tests').glob('test_*.py')) + [local / 'backend/music_runtime.cjs']
    paths += [local / 'tools' / name for name in ('publish_cdt_usage.py', 'deploy_study.py', 'deploy_music_reliability.py', *UNITS)]
    with tarfile.open(local / '.local-history/cdt-usage.tar.gz', 'w:gz') as bundle:
        for path in paths:
            if path.is_file(): bundle.add(path, arcname=path.relative_to(local), recursive=False)
        payload = json.dumps(baseline).encode(); info = tarfile.TarInfo('baseline.json'); info.size = len(payload)
        bundle.addfile(info, io.BytesIO(payload))
    print('PACKED_CDT_USAGE')


def publish(stage):
    for name, digest in json.loads((stage / 'baseline.json').read_text()).items():
        path = ROOT / name
        if (digest is None and path.exists()) or (digest is not None and normalized_hash(path.read_bytes()) != digest):
            raise RuntimeError('Production changed: ' + name)
    for unit in UNITS:
        target = Path('/etc/systemd/system') / unit
        if not target.is_file():
            raise RuntimeError('Missing existing daily sync: ' + unit)
    subprocess.run(['systemd-analyze', 'calendar', '*-*-* 13:30:00 Asia/Shanghai'], check=True)
    before = state_fingerprint()
    backup = release(stage, files=FILES, required_paths=('/api/visitors/traffic', '/api/visitors'))
    assert before == state_fingerprint(), 'Inspect concurrent runtime changes'
    for unit in UNITS:
        target = Path('/etc/systemd/system') / unit
        shutil.copy2(target, backup / unit)
        shutil.copy2(stage / 'tools' / unit, target)
        os.chmod(target, 0o644)
    subprocess.run(['systemctl', 'daemon-reload'], check=True)
    subprocess.run(['systemctl', 'enable', '--now', 'hzf-cdt-usage.timer'], check=True)
    subprocess.run([str(ROOT / 'backend/venv/bin/python'), str(ROOT / 'backend/cdt_usage.py'), '--force'], check=True)
    print('CDT_USAGE_RELEASE_OK; BACKUP=' + str(backup), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('mode', choices=['pack', 'release']); parser.add_argument('stage', nargs='?')
    args = parser.parse_args()
    pack() if args.mode == 'pack' else publish(Path(args.stage))
