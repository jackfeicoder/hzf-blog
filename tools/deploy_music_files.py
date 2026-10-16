"""Targeted file-cache release; preserve live sources, playlists and appearance."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile

from deploy_music_reliability import normalized_hash, state_fingerprint

ROOT = Path('/www/wwwroot/blog.120115.xyz')
NGINX = Path('/www/server/panel/vhost/nginx/blog.120115.xyz.conf')
DROPIN = Path('/etc/systemd/system/hzf-blog.service.d/97-music-files.conf')
BASELINE = {
    'backend/routers/music.py':'a6970cdd5a0dfd940f385eb5d80c8e1e027431d00c23a0f63bdfe5404b39b713',
    'backend/main.py':'059fe59c1338ba7d811331526927b4a632a75912113d409f09235d480b685397',
    'backend/requirements.txt':'d69a9d42cf5a63a7094632a3032d4b825a1d7519ac0de80bc3abd844cd1fcf2e',
    'frontend/src/music/PlayerBar.jsx':'f34588b2eabdde0aa79c778ac31f3ae5486f657b7b3254213162e646463e3350',
    'frontend/src/music/controller.js':'6f04ed0c6a9bbb6621eab8732024ecbf0c06e26cfabe6c41b365ff03bbd599b0',
    'frontend/src/music/store.js':'c09b3e527ac2722db2da3d734f3a80ef260f253d846e1a744a1733b6482e2ff6',
    'frontend/src/music/compact.css':'442f0591436e8cb56d436384477fe926440aa84a1c3b24208d0db1ab7b89ee67',
    'frontend/src/music/Sources.jsx':'1bd0429c8366c6e2c021d93c3b81bc18d8710037fdf77572d95610122f93a884',
}
NEW = ['backend/music_files.py','frontend/src/music/seekGesture.js']
FILES = list(BASELINE) + NEW


def pack():
    local = Path(__file__).resolve().parents[1]
    archive = local/'.local-history/music-files-release.tar.gz'
    paths = [local/name for name in FILES]
    paths += list((local/'backend').glob('*.py')) + list((local/'backend/routers').glob('*.py'))
    paths += list((local/'backend/tests').glob('test_*.py')) + [local/'backend/music_runtime.cjs']
    paths += list((local/'frontend/dist').rglob('*'))
    paths += [local/'tools'/name for name in ('deploy_music_files.py','deploy_study.py','deploy_music_reliability.py','verify_music_file_stage.py','verify_music_files_live.py')]
    with tarfile.open(archive,'w:gz') as bundle:
        for path in sorted(set(paths)):
            if path.is_file(): bundle.add(path,arcname=path.relative_to(local),recursive=False)
    print(archive)


def release(stage):
    import grp
    from deploy_study import release as publish
    stage = stage.resolve(strict=True)
    if stage.parent != Path('/tmp') or not stage.name.startswith('hzf-study-music-files-'):
        raise RuntimeError('Unexpected staging directory')
    for name,digest in BASELINE.items():
        if hashlib.sha256((ROOT/name).read_bytes()).hexdigest() != digest:
            raise RuntimeError('Production source changed: '+name)
    for name in NEW:
        if (ROOT/name).exists(): raise RuntimeError('New target already exists: '+name)
    if normalized_hash(NGINX.read_bytes()) != 'cb88b2f8de28d95f5c9b10256e81d9861b1e9cc75e1900bbfdc7267a5e42330c' or DROPIN.exists():
        raise RuntimeError('Infrastructure changed since inspection')
    subprocess.run([str(ROOT/'backend/venv/bin/python'),'-m','pip','install','--index-url','https://pypi.org/simple','mutagen>=1.47,<2'],check=True)
    before = state_fingerprint()
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    infrastructure = ROOT/'.deploy-backups'/('music-files-infrastructure-'+stamp)
    infrastructure.mkdir(parents=True,mode=0o700)
    shutil.copy2(NGINX,infrastructure/'blog.nginx.conf')
    print('INFRASTRUCTURE_BACKUP='+str(infrastructure),flush=True)
    block = '''    # Private, complete music files; direct external requests return 404.
    location ^~ /_music_cache/ {
        internal;
        alias /www/wwwroot/blog.120115.xyz/backend/.music-cache/;
        sendfile on;
        max_ranges 1;
        add_header X-Music-Cache HIT always;
    }
    location ^~ /api/music/stream/ {
        proxy_pass http://127.0.0.1:8001;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_http_version 1.1;
        proxy_buffering off;
        proxy_read_timeout 620s;
    }
'''
    text = NGINX.read_text()
    if text.count('    location /api/ {') != 2:
        raise RuntimeError('Unexpected blog server blocks')
    cache = ROOT/'backend/.music-cache'
    cache.mkdir(mode=0o750,exist_ok=True)
    os.chown(cache,0,grp.getgrnam('www').gr_gid)
    os.chmod(cache,0o750)
    try:
        NGINX.write_text(text.replace('    location /api/ {',block+'    location /api/ {'))
        subprocess.run(['nginx','-t'],check=True)
        DROPIN.parent.mkdir(parents=True,exist_ok=True)
        DROPIN.write_text('[Service]\nEnvironment=MUSIC_FILE_CACHE=1\nEnvironment=MUSIC_CACHE_ACCEL=1\n')
        subprocess.run(['systemctl','daemon-reload'],check=True)
        subprocess.run(['nginx','-s','reload'],check=True)
        backup = publish(stage,files=FILES,required_paths=('/api/music/file-cache','/api/music/resolve','/api/music/feedback','/api/visitors'))
        after = state_fingerprint()
        assert before['sources']==after['sources'] and before['appearance']==after['appearance']
        print('RUNTIME_CONFIG_PRESERVED='+json.dumps(after),flush=True)
        print('MUSIC_FILES_RELEASE_OK; BACKUP='+str(backup),flush=True)
    except Exception:
        shutil.copy2(infrastructure/'blog.nginx.conf',NGINX)
        DROPIN.unlink(missing_ok=True)
        subprocess.run(['systemctl','daemon-reload'],check=False)
        subprocess.run(['nginx','-t'],check=False)
        subprocess.run(['nginx','-s','reload'],check=False)
        subprocess.run(['systemctl','restart','hzf-blog.service'],check=False)
        print('INFRASTRUCTURE_ROLLED_BACK',flush=True)
        raise


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('mode',choices=['pack','release']);parser.add_argument('stage',nargs='?')
    args=parser.parse_args()
    pack() if args.mode=='pack' else release(Path(args.stage))
