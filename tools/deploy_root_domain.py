"""Prepare and activate an additive root-domain vhost; existing hosts stay intact."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess

ROOT = Path('/www/wwwroot/blog.120115.xyz')
VHOST = Path('/www/server/panel/vhost/nginx')
TARGET = VHOST / '120115.xyz-blog.conf'
CERT = Path('/www/server/panel/vhost/cert/120115-blog')
EXPECTED = 'a4df4ce0254db8987bdb3b4d5e10dd01e6c4cf6ed73cebc5610c433a1f0e67e9'


def run(*args):
    return subprocess.check_output(args, text=True, stderr=subprocess.STDOUT)


def emit(value):
    print(json.dumps(value, ensure_ascii=False), flush=True)


def reload_nginx():
    # This host's running master is managed by the panel, not systemd.
    pid = Path('/www/server/nginx/logs/nginx.pid').read_text().strip()
    command = Path(f'/proc/{pid}/cmdline').read_bytes()
    if b'/www/server/nginx/sbin/nginx' not in command or b'/www/server/nginx/conf/nginx.conf' not in command:
        raise RuntimeError('Nginx PID does not match the inspected panel-managed master')
    run('nginx', '-s', 'reload')


def atomic_bytes(path, content, mode=0o644):
    temporary = path.with_name(path.name + '.root-release-tmp')
    temporary.write_bytes(content)
    os.chmod(temporary, mode)
    os.replace(temporary, path)


def prepare():
    if TARGET.exists() or CERT.exists():
        raise RuntimeError('Root-domain destination already exists; inspect before modifying')
    original = VHOST / 'blog.120115.xyz.conf'
    if hashlib.sha256(original.read_bytes()).hexdigest() != EXPECTED:
        raise RuntimeError('Existing blog vhost changed since inspection')
    backup = ROOT / '.deploy-backups' / ('root-domain-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
    backup.mkdir(mode=0o700)
    os.chmod(backup.parent, 0o700)
    shutil.copytree(VHOST, backup / 'nginx')
    atomic_bytes(backup / 'nginx-expanded.txt', run('nginx', '-T').encode(), 0o600)
    with sqlite3.connect(f'file:{ROOT}/backend/blog.db?mode=ro', uri=True) as source:
        with sqlite3.connect(backup / 'blog.db') as destination:
            source.backup(destination)
    os.chmod(backup / 'blog.db', 0o600)
    manifest = {'backup': str(backup), 'pid': run('systemctl', 'show', 'hzf-blog.service', '-p', 'MainPID', '--value').strip(),
                'vhosts': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in VHOST.glob('*.conf')}}
    atomic_bytes(backup / 'manifest.json', json.dumps(manifest).encode(), 0o600)
    CERT.mkdir(mode=0o700)
    run('openssl', 'req', '-new', '-newkey', 'rsa:2048', '-nodes', '-keyout', str(CERT / 'privkey.pem'),
        '-out', str(CERT / 'request.csr'), '-subj', '/CN=120115.xyz', '-addext', 'subjectAltName=DNS:120115.xyz')
    os.chmod(CERT / 'privkey.pem', 0o600)
    emit({**manifest, 'csr': (CERT / 'request.csr').read_text()})


def checked_backup(value):
    backup = Path(value).resolve(strict=True)
    if backup.parent != ROOT / '.deploy-backups' or not backup.name.startswith('root-domain-'):
        raise RuntimeError('Unexpected backup target')
    return backup


def activate(value):
    backup = checked_backup(value)
    manifest = json.loads((backup / 'manifest.json').read_text())
    if TARGET.exists():
        raise RuntimeError('Unexpected existing root vhost')
    for name, digest in manifest['vhosts'].items():
        if hashlib.sha256((VHOST / name).read_bytes()).hexdigest() != digest:
            raise RuntimeError('Existing vhost changed concurrently')
    run('openssl', 'verify', '-CAfile', str(CERT / 'origin-ca.pem'), '-verify_hostname', '120115.xyz', str(CERT / 'fullchain.pem'))
    certificate_key = run('openssl', 'x509', '-in', str(CERT / 'fullchain.pem'), '-pubkey', '-noout')
    private_key = run('openssl', 'pkey', '-in', str(CERT / 'privkey.pem'), '-pubout')
    if certificate_key != private_key:
        raise RuntimeError('Certificate does not match the private key')
    text = (VHOST / 'blog.120115.xyz.conf').read_text()
    text = text[text.index('server {', text.index('server {') + 1):]
    text = text.replace('server_name blog.120115.xyz;', 'server_name 120115.xyz;')
    text = text.replace('/etc/letsencrypt/live/blog.120115.xyz/', str(CERT) + '/')
    text = text.replace('    index index.html;', '    index index.html;\n    client_max_body_size 6m;')
    text = text.replace('        proxy_http_version 1.1;', '        proxy_http_version 1.1;\n        proxy_read_timeout 620s;\n        proxy_buffering off;')
    text = text.replace('    location / {', '''    location ^~ /uploads/ {
        proxy_pass http://127.0.0.1:8001;
        proxy_set_header Host $host;
    }
    location = /index.html { add_header Cache-Control "no-cache"; }
    location / {''')
    text = text.replace('blog.120115.xyz.ssl', '120115.xyz.ssl')
    atomic_bytes(TARGET, text.encode())
    try:
        run('nginx', '-t')
        reload_nginx()
        pid = run('systemctl', 'show', 'hzf-blog.service', '-p', 'MainPID', '--value').strip()
        if pid != manifest['pid']:
            raise RuntimeError('Backend PID changed')
        emit({'event': 'ROOT_VHOST_OK', 'backend_pid_unchanged': True, 'backup': str(backup)})
    except Exception:
        TARGET.rename(backup / 'failed-root-vhost.conf')
        run('nginx', '-t'); reload_nginx()
        raise


def rollback(value):
    backup = checked_backup(value)
    if TARGET.exists():
        TARGET.rename(backup / 'rolled-back-root-vhost.conf')
        run('nginx', '-t'); reload_nginx()
    if CERT.exists():
        CERT.rename(backup / 'unused-origin-certificate')
    emit({'event': 'ROOT_VHOST_ROLLED_BACK', 'backup': str(backup)})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('prepare', 'activate', 'rollback'))
    parser.add_argument('backup', nargs='?')
    args = parser.parse_args()
    if args.mode == 'prepare': prepare()
    elif args.mode == 'activate': activate(args.backup)
    else: rollback(args.backup)
