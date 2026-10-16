"""Safely extract an export and verify every file and every SQLite database."""
import argparse
from contextlib import closing
import hashlib
import json
from pathlib import Path, PurePosixPath
import sqlite3
import tarfile


def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(chunk)
    return value.hexdigest()


def safe_relative(name):
    relative = PurePosixPath(name)
    if relative.is_absolute() or '..' in relative.parts or '\\' in name or ':' in name or not relative.parts:
        raise RuntimeError('Unsafe export path')
    return relative


def unpack(archive, destination, expected):
    if digest(archive) != expected:
        raise RuntimeError('Archive checksum mismatch')
    destination.mkdir(exist_ok=False)
    with tarfile.open(archive, 'r:gz') as bundle:
        for entry in bundle.getmembers():
            relative = safe_relative(entry.name)
            if not entry.isfile():
                raise RuntimeError('Unsafe archive member')
            target = destination.joinpath(*relative.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with bundle.extractfile(entry) as source, target.open('xb') as output:
                import shutil
                shutil.copyfileobj(source, output)
    manifest = json.loads((destination / 'manifest.json').read_text())
    databases = []
    for row in manifest['files']:
        target = destination.joinpath(*safe_relative(row['path']).parts)
        if not target.is_file() or target.stat().st_size != row['bytes'] or digest(target) != row['sha256']:
            raise RuntimeError('File verification failed: ' + row['path'])
        with target.open('rb') as stream:
            sqlite = stream.read(16) == b'SQLite format 3\x00'
        if sqlite:
            with closing(sqlite3.connect(target.as_uri() + '?mode=ro', uri=True)) as db:
                if db.execute('PRAGMA quick_check').fetchall() != [('ok',)]:
                    raise RuntimeError('Database integrity check failed')
            databases.append(row['path'])
    print(json.dumps(dict(verified_files=len(manifest['files']), total_bytes=manifest['total_bytes'],
        sqlite_databases=databases, r2=manifest['r2'], destination=str(destination)), ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('archive', type=Path)
    parser.add_argument('destination', type=Path)
    parser.add_argument('sha256')
    args = parser.parse_args()
    unpack(args.archive, args.destination, args.sha256)
