"""Frontend-only backed-up release; preserve live music and appearance data."""
import argparse
from pathlib import Path
import tarfile
from deploy_music_reliability import normalized_hash, state_fingerprint

ROOT = Path('/www/wwwroot/blog.120115.xyz')
FILES = ['frontend/src/pages/Music.jsx', 'frontend/src/music/PlayerBar.jsx',
         'frontend/src/music/CoverArt.jsx', 'frontend/src/music/cover.js',
         'frontend/src/music/compact.css', 'frontend/src/music/lyricSettings.js']
BASELINE = {
    'frontend/src/pages/Music.jsx': 'f9ccf16f31fd9d865986a2739b34ba187b986ad10af85933c416b7d7d8d3302d',
    'frontend/src/music/PlayerBar.jsx': 'a9940f77b594adfbd2a43a152dcc9c3c8854e298fc72fbba5df4cafd3641ae74',
    'frontend/src/music/music.css': 'b0761ad9fd55e67e1161f930c9e8ed0ff36214a2552500a2eb557450070837b4',
}


def pack():
    local = Path(__file__).resolve().parents[1]
    archive = local / '.local-history/music-compact-release.tar.gz'
    paths = [local / name for name in FILES]
    paths += list((local / 'backend').glob('*.py'))
    paths += list((local / 'backend/routers').glob('*.py'))
    paths += list((local / 'backend/tests').glob('test_*.py'))
    paths += list((local / 'frontend/dist').rglob('*'))
    paths += [local / 'tools' / name for name in ('deploy_music_compact.py', 'deploy_music_reliability.py', 'deploy_study.py')]
    with tarfile.open(archive, 'w:gz') as bundle:
        for path in sorted(set(paths)):
            if path.is_file():
                bundle.add(path, arcname=path.relative_to(local), recursive=False)
    print(archive)


def release(stage):
    import json
    from deploy_study import release as publish
    stage = stage.resolve(strict=True)
    if stage.parent != Path('/tmp') or not stage.name.startswith('hzf-study-music-compact-'):
        raise RuntimeError('Unexpected staging directory')
    for name, digest in BASELINE.items():
        if normalized_hash((ROOT / name).read_bytes()) != digest:
            raise RuntimeError('Production differs from inspected source: ' + name)
    for name in FILES[2:]:
        if (ROOT / name).exists():
            raise RuntimeError('New release file already exists: ' + name)
    before = state_fingerprint()
    print('PRESERVED_BEFORE=' + json.dumps(before), flush=True)
    backup = publish(stage, files=FILES, restart_backend=False,
                     required_paths=('/api/music/resolve', '/api/music/lyrics/resolve', '/api/music/diagnostics', '/api/appearance'))
    after = state_fingerprint()
    assert before['sources'] == after['sources'] and before['appearance'] == after['appearance'], 'Runtime configuration changed; inspect'
    print('RUNTIME_CONFIG_PRESERVED=' + json.dumps(after), flush=True)
    print('MUSIC_COMPACT_RELEASE_OK; BACKUP=' + str(backup), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['pack', 'release'])
    parser.add_argument('stage', nargs='?')
    args = parser.parse_args()
    pack() if args.mode == 'pack' else release(Path(args.stage))
