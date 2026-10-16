"""Create a private, read-only production export for recovery on another machine.

Run on the Linux blog host, not on a development checkout. Does not stop services,
delete files, modify production data or upload anything to a third party.
"""
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sqlite3
import subprocess
import tarfile
import tempfile

ROOT = Path('/www/wwwroot/blog.120115.xyz')
EXCLUDED_DIRS = {'.deploy-backups', '.git', 'venv', 'node_modules', '__pycache__'}


def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(chunk)
    return value.hexdigest()


def sqlite_copy(source, target):
    with closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True, timeout=10)) as src:
        with closing(sqlite3.connect(target)) as dest:
            src.backup(dest)
            if dest.execute('PRAGMA quick_check').fetchall() != [('ok',)]:
                raise RuntimeError('Exported SQLite database failed integrity check')
    os.chmod(target, 0o600)


def copy_file(source, target):
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with source.open('rb') as stream:
        sqlite = stream.read(16) == b'SQLite format 3\x00'
    if sqlite:
        sqlite_copy(source, target)
    else:
        shutil.copy2(source, target)


def export_project(stage):
    skipped = []
    for base, dirs, files in os.walk(ROOT, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in EXCLUDED_DIRS and not d.startswith('dist.backup.')
                         and not (Path(base) / d).is_symlink())
        for name in sorted(files):
            source = Path(base) / name
            if source.is_symlink() or name.endswith(('.part', '.pyc', '.db-wal', '.db-shm', '.sqlite3-wal', '.sqlite3-shm')):
                skipped.append(str(source.relative_to(ROOT)))
                continue
            copy_file(source, stage / 'project' / source.relative_to(ROOT))
    return skipped


def export_config(stage):
    configs = [Path('/etc/systemd/system/hzf-blog.service')]
    configs += sorted(Path('/etc/systemd/system/hzf-blog.service.d').glob('*.conf'))
    nginx = Path('/www/server/panel/vhost/nginx/blog.120115.xyz.conf')
    configs += [nginx, Path('/www/server/panel/vhost/rewrite/blog.120115.xyz.conf')]
    text = nginx.read_text()
    for path in re.findall(r'^\s*(?:ssl_certificate|ssl_certificate_key|include)\s+([^;\s]+)\s*;', text, re.M):
        target = Path(path)
        # Only explicit references belonging to this blog, never all vhosts.
        if target.is_absolute() and target.is_file():
            configs.append(target)
    for source in sorted(set(configs)):
        if source.is_file():
            copy_file(source, stage / 'config' / source.relative_to('/'))


def export_r2(stage):
    import boto3
    from botocore.config import Config
    pid = subprocess.check_output(['systemctl', 'show', 'hzf-blog.service', '-p', 'MainPID', '--value'], text=True).strip()
    env = dict(entry.split(b'=', 1) for entry in Path('/proc/' + pid + '/environ').read_bytes().split(b'\0') if b'=' in entry)
    settings = {name: env.get(name.encode(), b'').decode() for name in
                ('R2_ACCOUNT_ID', 'R2_BUCKET', 'R2_ACCESS_KEY_ID', 'R2_SECRET_ACCESS_KEY')}
    if not all(settings.values()):
        raise RuntimeError('R2 export requires the blog service R2 settings')
    client = boto3.client('s3', endpoint_url='https://' + settings['R2_ACCOUNT_ID'] + '.r2.cloudflarestorage.com',
        aws_access_key_id=settings['R2_ACCESS_KEY_ID'], aws_secret_access_key=settings['R2_SECRET_ACCESS_KEY'],
        region_name='auto', config=Config(connect_timeout=5, read_timeout=30, retries={'max_attempts': 2}))
    objects = []
    for page in client.get_paginator('list_objects_v2').paginate(Bucket=settings['R2_BUCKET']):
        for entry in page.get('Contents', []):
            key = entry['Key']
            relative = PurePosixPath(key)
            if relative.is_absolute() or '..' in relative.parts or '\\' in key or '\x00' in key:
                raise RuntimeError('Unexpected R2 object path')
            if key.endswith('/'):
                continue
            target = stage / 'r2-objects' / str(relative)
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            response = client.get_object(Bucket=settings['R2_BUCKET'], Key=key, IfMatch=entry['ETag'])
            with closing(response['Body']) as source, target.open('xb') as dest:
                shutil.copyfileobj(source, dest)
            os.chmod(target, 0o600)
            if target.stat().st_size != entry['Size']:
                raise RuntimeError('R2 object size changed during export')
            objects.append(dict(key=key, bytes=target.stat().st_size, sha256=digest(target),
                content_type=response.get('ContentType'), cache_control=response.get('CacheControl')))
    (stage / 'r2-metadata.json').write_text(json.dumps(dict(bucket=settings['R2_BUCKET'], objects=objects), ensure_ascii=False, indent=2))
    return dict(objects=len(objects), bytes=sum(row['bytes'] for row in objects))


def main():
    os.umask(0o077)
    stage = Path(tempfile.mkdtemp(prefix='hzf-local-export-', dir='/tmp'))
    skipped = export_project(stage)
    export_config(stage)
    r2 = export_r2(stage)
    files = [dict(path=str(path.relative_to(stage)), bytes=path.stat().st_size, sha256=digest(path))
             for path in sorted(stage.rglob('*')) if path.is_file()]
    manifest = dict(created_utc=datetime.now(timezone.utc).isoformat(), source=str(ROOT), files=files,
        total_bytes=sum(row['bytes'] for row in files), r2=r2,
        excluded_directories=sorted(EXCLUDED_DIRS) + ['frontend/dist.backup.*'], skipped=skipped)
    (stage / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    archive = stage.with_suffix('.tar.gz')
    with tarfile.open(archive, 'w:gz') as bundle:
        for path in sorted(stage.rglob('*')):
            if path.is_file():
                bundle.add(path, arcname=str(path.relative_to(stage)), recursive=False)
    os.chmod(archive, 0o600)
    print(json.dumps(dict(stage=str(stage), archive=str(archive), sha256=digest(archive),
        archive_bytes=archive.stat().st_size, files=len(files), total_bytes=manifest['total_bytes'], r2=r2)), flush=True)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        # Do not expose credentials or signed request metadata from SDK errors.
        print('EXPORT_FAILED=' + type(error).__name__, flush=True)
        raise SystemExit(1) from None
