"""Additive direct-origin vhost and webroot certificate; preserve old hosts."""
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
TARGET = VHOST / 'ithzf.xyz.conf'
ACME = Path('/www/wwwroot/ithzf-acme')
NGINX = '/www/server/nginx/sbin/nginx'
CONF = '/www/server/nginx/conf/nginx.conf'
CERT = Path('/etc/letsencrypt/live/ithzf.xyz')


def run(*args):
    subprocess.run(args, check=True)


def reload():
    run(NGINX, '-t', '-c', CONF)
    run(NGINX, '-s', 'reload', '-c', CONF)


def atomic(path, text):
    temporary = path.with_name(path.name + '.ithzf-tmp')
    temporary.write_text(text)
    os.replace(temporary, path)


def http_block(ready=False):
    response = 'return 308 https://ithzf.xyz$request_uri;' if ready else 'return 503;'
    return '''server {
    listen 80;
    server_name ithzf.xyz www.ithzf.xyz blog.ithzf.xyz;
    root /www/wwwroot/ithzf-acme;
    location ^~ /.well-known/acme-challenge/ {
        default_type text/plain;
        try_files $uri =404;
    }
    location / { ''' + response + ''' }
}
'''


def prepare():
    if TARGET.exists() or CERT.exists():
        raise RuntimeError('New domain target already exists; inspect before changing')
    backup = ROOT / '.deploy-backups' / ('ithzf-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
    backup.mkdir(mode=0o700)
    shutil.copytree(VHOST, backup / 'nginx')
    with sqlite3.connect('file:' + str(ROOT / 'backend/blog.db') + '?mode=ro', uri=True) as source:
        with sqlite3.connect(backup / 'blog.db') as destination:
            source.backup(destination)
    os.chmod(backup / 'blog.db', 0o600)
    manifest = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in VHOST.glob('*.conf')}
    (backup / 'manifest.json').write_text(json.dumps(manifest))
    (ACME / '.well-known/acme-challenge').mkdir(parents=True, exist_ok=True)
    atomic(TARGET, http_block())
    try:
        reload()
    except Exception:
        TARGET.rename(backup / 'failed-http.conf')
        reload()
        raise
    print('BACKUP=' + str(backup), flush=True)


def issue():
    if TARGET.read_text() != http_block():
        raise RuntimeError('Expected prepared HTTP challenge vhost')
    renewal = Path('/etc/letsencrypt/renewal/blog.120115.xyz.conf').read_text()
    account = next(line.split('=', 1)[1].strip() for line in renewal.splitlines() if line.startswith('account ='))
    run('certbot', 'certonly', '--webroot', '-w', str(ACME), '--cert-name', 'ithzf.xyz',
        '-d', 'ithzf.xyz', '-d', 'www.ithzf.xyz', '-d', 'blog.ithzf.xyz',
        '--account', account, '--non-interactive', '--agree-tos',
        '--deploy-hook', NGINX + ' -t -c ' + CONF + ' && ' + NGINX + ' -s reload -c ' + CONF)


def activate():
    if TARGET.read_text() != http_block() or not (CERT / 'fullchain.pem').is_file():
        raise RuntimeError('Expected challenge vhost and issued certificate')
    original = (VHOST / 'blog.120115.xyz.conf').read_text()
    start = original.index('server {', original.index('server {') + 1)
    main = original[start:].replace('listen 8443 ssl;', 'listen 443 ssl http2;')
    main = main.replace('server_name blog.120115.xyz;', 'server_name ithzf.xyz;')
    main = main.replace('/etc/letsencrypt/live/blog.120115.xyz/', str(CERT) + '/')
    main = main.replace('blog.120115.xyz.ssl.', 'ithzf.xyz.ssl.')
    # This vhost is direct-origin: do not trust client-supplied forwarded IPs.
    main = main.replace('proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;', 'proxy_set_header X-Forwarded-For $remote_addr;')
    main = main.replace('    index index.html;', '    index index.html;\n    client_max_body_size 6m;')
    main = main.replace('    location / {', '    location = /index.html { add_header Cache-Control "no-cache"; }\n    location / {')
    main = main.replace('    location /docs { proxy_pass http://127.0.0.1:8001; proxy_set_header Host $host; }', '    location /docs { return 404; }')
    main = main.replace('    location /openapi.json { proxy_pass http://127.0.0.1:8001; }', '    location /openapi.json { return 404; }')
    aliases = '''
server {
    listen 443 ssl http2;
    server_name www.ithzf.xyz blog.ithzf.xyz;
    ssl_certificate /etc/letsencrypt/live/ithzf.xyz/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/ithzf.xyz/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    return 308 https://ithzf.xyz$request_uri;
}
'''
    atomic(TARGET, http_block(True) + '\n' + main + aliases)
    try:
        reload()
    except Exception:
        atomic(TARGET, http_block())
        reload()
        raise
    print('ITHZF_HTTPS_ACTIVE', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['prepare', 'issue', 'activate'])
    args = parser.parse_args()
    {'prepare': prepare, 'issue': issue, 'activate': activate}[args.mode]()
