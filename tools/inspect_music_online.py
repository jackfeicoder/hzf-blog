"""Read-only music/config audit. Never emits scripts, keys, or private song lists."""
import hashlib
import json
from pathlib import Path
import sqlite3
import tarfile

root = Path('/www/wwwroot/blog.120115.xyz')
paths = list((root / 'frontend/src').rglob('*'))
paths += [root / 'frontend/package.json', root / 'frontend/package-lock.json', root / 'backend/routers/music.py']
paths += list((root / 'backend').glob('music*'))
files = [p for p in paths if p.is_file()]
print(json.dumps({'hashes': {str(p.relative_to(root)): hashlib.sha256(p.read_bytes().replace(b'\r\n', b'\n')).hexdigest() for p in files}}))
with sqlite3.connect('file:'+str(root/'backend/blog.db')+'?mode=ro', uri=True) as db:
    db.row_factory = sqlite3.Row
    sources = [dict(row) for row in db.execute('SELECT id,name,enabled,position,status,capabilities,digest FROM music_sources ORDER BY position,id')]
    print(json.dumps({'sources': sources}, ensure_ascii=False))
    tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND (name LIKE '%appearance%' OR name LIKE '%music%')")]
    counts = {table: db.execute('SELECT COUNT(*) FROM "'+table+'"').fetchone()[0] for table in tables}
    print(json.dumps({'counts': counts}))
archive = Path('/tmp/hzf-music-online-20261007.tar.gz')
with tarfile.open(archive, 'w:gz') as bundle:
    for path in files:
        bundle.add(path, arcname=path.relative_to(root), recursive=False)
print('ARCHIVE='+str(archive))
