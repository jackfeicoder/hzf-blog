"""Guarded lyric persistence release; never replace live music or appearance data."""
import argparse
import io
import json
from pathlib import Path
import subprocess
import tarfile

from deploy_music_reliability import normalized_hash, state_fingerprint

ROOT = Path('/www/wwwroot/blog.120115.xyz')
FILES = ['backend/routers/music.py', 'backend/music_lyrics.py']


def pack():
    local = Path(__file__).resolve().parents[1]
    baseline = {'backend/routers/music.py': normalized_hash(subprocess.check_output(
        ['git', 'show', 'HEAD:backend/routers/music.py'], cwd=local)), 'backend/music_lyrics.py': None}
    # The shared release helper republishes the identical build; guard against a
    # newer live UI so this backend change never reverts someone else's release.
    baseline['frontend/dist/index.html'] = normalized_hash((local / 'frontend/dist/index.html').read_bytes())
    paths = list((local / 'backend').glob('*.py')) + list((local / 'backend/routers').glob('*.py'))
    paths += list((local / 'backend/tests').glob('test_*.py')) + [local / 'backend/music_runtime.cjs']
    paths += list((local / 'frontend/dist').rglob('*'))
    paths += [local / 'tools' / name for name in ('deploy_music_lyrics.py', 'verify_music_lyrics_live.py',
                                                 'deploy_music_reliability.py', 'deploy_study.py')]
    archive = local / '.local-history/music-lyrics-release.tar.gz'
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
    if stage.parent != Path('/tmp') or not stage.name.startswith('hzf-study-music-lyrics-'):
        raise RuntimeError('Unexpected staging directory')
    for name, digest in json.loads((stage / 'baseline.json').read_text()).items():
        target = ROOT / name
        if (digest is None and target.exists()) or (digest is not None and normalized_hash(target.read_bytes()) != digest):
            raise RuntimeError('Production source changed: ' + name)
    before = state_fingerprint()
    backup = publish(stage, files=FILES,
                     required_paths=('/api/music/lyrics/resolve', '/api/music/file-cache', '/api/appearance'))
    after = state_fingerprint()
    assert before['sources'] == after['sources'] and before['appearance'] == after['appearance'], 'Inspect live settings'
    print('RUNTIME_CONFIG_PRESERVED=' + json.dumps(after), flush=True)
    print('MUSIC_LYRICS_RELEASE_OK; BACKUP=' + str(backup), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['pack', 'release'])
    parser.add_argument('stage', nargs='?')
    args = parser.parse_args()
    pack() if args.mode == 'pack' else release(Path(args.stage))
