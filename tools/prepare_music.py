"""Build an offline runtime from the host's Node binary; verify archived sources.

Run against a temporary staging DB first. Output contains metadata only, never scripts/keys.
"""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

IMAGE = 'hzf-music-node:20261002'
ARCHIVE = Path('/root/music-source-review-20261002')
NAMES = {'sixyin': '六音', 'huibq': 'Huibq', 'flower': '野花', 'lx': '独家音源', 'changqing': '长青', 'huanyin': '幻音', 'ikun': 'ikun', 'grass': '野草', 'juhe': '聚合 API', 'qdy': '全豆要'}


def build():
    if subprocess.run(['docker', 'image', 'inspect', IMAGE], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
        return
    stage = Path(tempfile.mkdtemp(prefix='hzf-music-image-', dir='/tmp'))
    root = stage / 'rootfs'; root.mkdir()
    binary = Path('/usr/bin/node')
    shutil.copy2(binary, root / 'node')
    libs = subprocess.check_output(['ldd', str(binary)], text=True)
    for name in set(re.findall(r'(/[^\s]+)', libs)):
        origin = Path(name)
        if origin.is_file():
            destination = root / str(origin).lstrip('/')
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(origin, destination)
    (root / 'etc').mkdir()
    (root / 'etc/passwd').write_text('nobody:x:65534:65534:nobody:/:/nonexistent\n')
    (stage / 'Dockerfile').write_text('FROM scratch\nCOPY rootfs /\nUSER 65534:65534\n')
    subprocess.run(['docker', 'build', '--network=none', '-t', IMAGE, str(stage)], check=True)
    subprocess.run(['docker', 'run', '--rm', '--network', 'none', '--read-only', '--cap-drop', 'ALL', IMAGE, '/node', '--version'], check=True)


async def verify(backend, output):
    sys.path.insert(0, str(backend))
    os.environ['MUSIC_SANDBOX'] = 'docker'
    from music_worker import run_source
    from routers.music import check_audio
    expected = {}
    for line in (ARCHIVE / 'MANIFEST.sha256').read_text().splitlines():
        digest, file = line.split(maxsplit=1)
        expected[Path(file.lstrip('*')).name] = digest
    results = []
    # Two actual metadata IDs, not a promise of availability for all songs.
    sample = {'id': '2652820720', 'songmid': '2652820720', 'hash': '2652820720', 'name': '晴天(深情版)', 'singer': 'Lucky小爱', 'albumName': '晴天(深情版)'}
    for index, (slug, name) in enumerate(NAMES.items()):
        raw = (ARCHIVE / f'{slug}.js').read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if digest != expected.get(f'{slug}.js'):
            raise RuntimeError(f'Archive checksum mismatch: {slug}')
        script = raw.decode('utf-8-sig')
        result = dict(name=name, digest=hashlib.sha256(script.encode()).hexdigest(), script=script,
                      enabled=False, position=20 + index, status='初始化失败 / 超时', capabilities='{}')
        try:
            probe = await run_source(script, name)
            caps = probe.get('capabilities', {})
            result['capabilities'] = json.dumps(caps)
            result['status'] = '兼容性通过，播放需实测'
            if 'wy' in caps:
                try:
                    playback = await run_source(script, name, 'musicUrl', 'wy', {'type': '128k', 'musicInfo': sample})
                    await asyncio.to_thread(check_audio, playback.get('result'))
                    result['enabled'] = True
                    result['status'] = '样本播放地址已验证'
                except Exception:
                    result['status'] = '兼容性通过，样本播放失败'
        except Exception:
            pass
        results.append(result)
        print(json.dumps({k: v for k, v in result.items() if k not in ('script', 'capabilities', 'digest')}, ensure_ascii=False), flush=True)
        output.write_text(json.dumps(results, ensure_ascii=False))
        os.chmod(output, 0o600)
    return results


if __name__ == '__main__':
    build()
    asyncio.run(verify(Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()))
