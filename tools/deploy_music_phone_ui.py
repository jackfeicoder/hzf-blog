"""Backed-up phone-only CSS release; no backend restart or runtime-data writes."""
import argparse
import io
import json
from pathlib import Path
import subprocess
import tarfile

from deploy_music_reliability import ROOT, normalized_hash, state_fingerprint

FILES = ['frontend/src/music/compact.css']
LIVE_INDEX = '310b50dcfb5670f53c0d5b8204952ce3b7687a02f334c2660b42b90c3ea9b446'


def pack():
    local = Path(__file__).resolve().parents[1]
    source_names = subprocess.check_output(['git', 'ls-files', 'frontend/src'], cwd=local, text=True).splitlines()
    baseline = {name: normalized_hash(subprocess.check_output(['git', 'show', 'HEAD:' + name], cwd=local))
                for name in source_names}
    baseline['frontend/dist/index.html'] = LIVE_INDEX
    paths = [local / name for name in FILES]
    paths += list((local / 'backend').glob('*.py')) + list((local / 'backend/routers').glob('*.py'))
    paths += list((local / 'backend/tests').glob('test_*.py')) + [local / 'backend/music_runtime.cjs']
    paths += list((local / 'frontend/dist').rglob('*'))
    paths += [local / 'tools' / name for name in ('deploy_music_phone_ui.py', 'deploy_music_reliability.py', 'deploy_study.py')]
    archive = local / '.local-history/music-phone-ui-release.tar.gz'
    with tarfile.open(archive, 'w:gz') as bundle:
        for path in sorted(set(paths)):
            if path.is_file():
                bundle.add(path, arcname=path.relative_to(local), recursive=False)
        payload = json.dumps(baseline).encode()
        entry = tarfile.TarInfo('baseline.json'); entry.size = len(payload)
        bundle.addfile(entry, io.BytesIO(payload))
    print(archive)


def release(stage):
    from deploy_study import release as publish
    stage = stage.resolve(strict=True)
    if stage.parent != Path('/tmp') or not stage.name.startswith('hzf-study-music-phone-ui-'):
        raise RuntimeError('Unexpected staging directory')
    for name, digest in json.loads((stage / 'baseline.json').read_text()).items():
        if normalized_hash((ROOT / name).read_bytes()) != digest:
            raise RuntimeError('Production source changed: ' + name)
    before = state_fingerprint()
    audio_files = {path: path.stat().st_size for path in (ROOT / 'backend/.music-cache').glob('*.audio')}
    backup = publish(stage, files=FILES, restart_backend=False,
                     required_paths=('/api/music/resolve', '/api/music/lyrics/resolve', '/api/appearance'))
    after = state_fingerprint()
    assert before['sources'] == after['sources'] and before['appearance'] == after['appearance'], 'Inspect live settings'
    assert all(path.is_file() and path.stat().st_size == size for path, size in audio_files.items()), 'Inspect cache files'
    print('CACHE_FILES_PRESERVED=' + str(len(audio_files)), flush=True)
    print('RUNTIME_CONFIG_PRESERVED=' + json.dumps(after), flush=True)
    print('MUSIC_PHONE_UI_RELEASE_OK; BACKUP=' + str(backup), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('mode', choices=['pack', 'release']); parser.add_argument('stage', nargs='?')
    args = parser.parse_args()
    pack() if args.mode == 'pack' else release(Path(args.stage))
