"""Backed-up targeted AI release and private runtime-key migration."""
import argparse
import ast
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
from datetime import datetime, timezone

FILES = ['backend/routers/chat.py', 'backend/schemas_chat.py', 'backend/sensenova_catalog.py',
         'backend/chat_limits.py', 'frontend/src/api.js', 'frontend/src/pages/ChatAI.jsx',
         'frontend/src/chat/config.js']
EXPECTED_LEGACY = '4bb8a972d76d9c9a61301e7aae0e92ad7f781f99d9cb2cba568a943d1d5f55e7'


def pack():
    local = Path(__file__).resolve().parents[1]
    archive = local/'.local-history/chat-release.tar.gz'
    archive.parent.mkdir(exist_ok=True)
    paths = [local/name for name in FILES]
    paths += list((local/'backend').glob('*.py')) + list((local/'backend/routers').glob('*.py'))
    paths += list((local/'backend/tests').glob('test_*.py'))
    paths += list((local/'frontend/dist').rglob('*'))
    paths += [Path(__file__).resolve(), local/'tools/deploy_study.py', local/'tools/verify_chat.py']
    with tarfile.open(archive,'w:gz') as bundle:
        for path in sorted(set(paths)):
            if path.is_file(): bundle.add(path, arcname=path.relative_to(local), recursive=False)
    print(archive)


def release(stage):
    from deploy_study import ROOT, release as deploy, atomic_copy
    stage = stage.resolve(strict=True)
    if stage.parent != Path('/tmp') or not stage.name.startswith('hzf-study-chat-'):
        raise RuntimeError('Unexpected staging directory')
    legacy = ROOT/'backend/routers/chat.py'
    if hashlib.sha256(legacy.read_bytes()).hexdigest() != EXPECTED_LEGACY:
        raise RuntimeError('Live chat source changed since inspection')
    key = ''
    for node in ast.parse(legacy.read_text()).body:
        if isinstance(node, ast.Assign) and any(isinstance(t,ast.Name) and t.id=='DEFAULT_FREE_KEY' for t in node.targets):
            if isinstance(node.value,ast.Constant) and isinstance(node.value.value,str):
                key=node.value.value.strip()
    if not key or not key.startswith('sk-'):
        raise RuntimeError('Expected legacy provider key is missing')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    backup = ROOT/'.deploy-backups'/f'chat-config-{stamp}'
    backup.mkdir(mode=0o700)
    targets = {'sensenova.env': ROOT/'backend/sensenova.env',
               '96-sensenova.conf': Path('/etc/systemd/system/hzf-blog.service.d/96-sensenova.conf'),
               'gitignore': ROOT/'.gitignore'}
    existed = {}
    for name,path in targets.items():
        existed[name]=path.is_file()
        if existed[name]: shutil.copy2(path,backup/name)
    try:
        secret = targets['sensenova.env']
        descriptor = os.open(secret, os.O_WRONLY|os.O_CREAT|os.O_TRUNC, 0o600)
        with os.fdopen(descriptor,'w') as handle: handle.write('SENSENOVA_API_KEY='+key+'\n')
        os.chmod(secret,0o600)
        unit = targets['96-sensenova.conf']
        unit.parent.mkdir(exist_ok=True)
        unit.write_text('[Service]\nEnvironmentFile='+str(secret)+'\n')
        ignore = targets['gitignore']
        old = ignore.read_text() if ignore.exists() else ''
        if '/backend/sensenova.env' not in old.splitlines():
            ignore.write_text(old.rstrip()+'\n\n# Server-only AI runtime credential\n/backend/sensenova.env\n')
        subprocess.run(['git','check-ignore','--quiet','backend/sensenova.env'],cwd=ROOT,check=True)
        subprocess.run(['systemctl','daemon-reload'],check=True)
        print(f'CONFIG_BACKUP={backup}',flush=True)
        app_backup = deploy(stage,files=FILES,required_paths=('/api/chat','/api/chat/stream','/api/chat/providers','/api/appearance','/api/music/search'))
        print('CHAT_RELEASE_OK; server key migrated to private environment file',flush=True)
    except Exception:
        for name,path in targets.items():
            if existed[name]: atomic_copy(backup/name,path)
            elif path.is_file(): path.unlink()
        subprocess.run(['systemctl','daemon-reload'],check=False)
        subprocess.run(['systemctl','restart','hzf-blog.service'],check=False)
        print('CHAT_CONFIG_ROLLED_BACK; backups retained',flush=True)
        raise


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('mode',choices=['pack','release'])
    parser.add_argument('stage',nargs='?')
    args=parser.parse_args()
    pack() if args.mode=='pack' else release(Path(args.stage))
