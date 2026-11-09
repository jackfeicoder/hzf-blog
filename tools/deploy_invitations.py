"""Additive invitation/visitor release; never overwrite settings or music caches."""
from pathlib import Path
import argparse
import io
import json
import subprocess
import sys
import tarfile
from deploy_study import release
from deploy_music_reliability import ROOT, normalized_hash, state_fingerprint

FILES = [
    "backend/models.py", "backend/schemas.py", "backend/routers/auth_router.py",
    "backend/routers/visitors.py", "frontend/src/api.js", "frontend/src/AuthContext.jsx",
    "frontend/src/pages/Admin.jsx", "frontend/src/pages/Register.jsx",
    "frontend/src/pages/Visitors.jsx", "frontend/src/components/InviteManager.jsx",
]

def pack():
    local = Path(__file__).resolve().parents[1]
    baseline_names = subprocess.check_output(
        ['git', 'ls-tree', '-r', '--name-only', 'ac84ff6', 'frontend/src'], cwd=local, text=True,
    ).splitlines() + [name for name in FILES if name.startswith('backend/')]
    baseline = {name: normalized_hash(subprocess.check_output(['git', 'show', 'ac84ff6:' + name], cwd=local))
                for name in baseline_names}
    baseline['frontend/src/components/InviteManager.jsx'] = None
    paths = [local / name for name in FILES]
    # A runtime compatibility test locates this fixture relative to its file.
    # Package it for tests only; it is deliberately absent from deployment FILES.
    paths += [local / 'backend/music_runtime.cjs']
    paths += list((local / 'backend/tests').glob('test_*.py'))
    paths += list((local / 'frontend/dist').rglob('*'))
    paths += [local / 'tools' / name for name in ('deploy_invitations.py', 'deploy_study.py', 'deploy_music_reliability.py')]
    archive = local / '.local-history/invitations-release.tar.gz'
    with tarfile.open(archive, 'w:gz') as bundle:
        for path in sorted(set(paths)):
            if path.is_file():
                bundle.add(path, arcname=path.relative_to(local), recursive=False)
        payload = json.dumps(baseline).encode()
        info = tarfile.TarInfo('baseline.json'); info.size = len(payload)
        bundle.addfile(info, io.BytesIO(payload))
    print(archive)


def publish(stage):
    for name, digest in json.loads((stage / 'baseline.json').read_text()).items():
        path = ROOT / name
        if (digest is None and path.exists()) or (digest is not None and (not path.is_file() or normalized_hash(path.read_bytes()) != digest)):
            raise RuntimeError('Production changed since inspection: ' + name)
    before = state_fingerprint()
    audio = {p: (p.stat().st_size, p.stat().st_mtime_ns) for p in (ROOT / 'backend/.music-cache').glob('*.audio')}
    backup = release(stage, files=FILES, required_paths=("/api/auth/invitations", "/api/visitors"))
    after = state_fingerprint()
    assert before['sources'] == after['sources'] and before['appearance'] == after['appearance'], 'Inspect runtime settings'
    assert all(p.is_file() and (p.stat().st_size, p.stat().st_mtime_ns) == stats for p, stats in audio.items()), 'Inspect audio cache'
    print('SETTINGS_AND_AUDIO_CACHE_PRESERVED=' + str(len(audio)), flush=True)
    print('INVITATIONS_RELEASE_OK; BACKUP=' + str(backup), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['pack', 'release'])
    parser.add_argument('stage', nargs='?')
    args = parser.parse_args()
    pack() if args.mode == 'pack' else publish(Path(args.stage))
