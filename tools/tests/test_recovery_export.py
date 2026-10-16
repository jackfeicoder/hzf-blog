from contextlib import closing
import io
import json
from pathlib import Path
import sqlite3
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import export_server_recovery as export
from verify_recovery_export import unpack


class RecoveryExportTests(unittest.TestCase):
    def test_sqlite_online_copy_preserves_committed_wal_data(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with closing(sqlite3.connect(root / 'live.db')) as db:
                db.execute('PRAGMA journal_mode=WAL')
                db.execute('CREATE TABLE notes (value TEXT)')
                db.execute('INSERT INTO notes VALUES (?)', ('committed data',)); db.commit()
                export.sqlite_copy(root / 'live.db', root / 'copy.db')
                with closing(sqlite3.connect(root / 'copy.db')) as copy:
                    self.assertEqual(copy.execute('SELECT * FROM notes').fetchall(), [('committed data',)])

    def test_project_includes_private_configuration_and_data_but_not_old_backups_or_dependencies(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / 'live'; stage = Path(folder) / 'export'
            for name in ['backend/.env', 'backend/uploads/avatar.webp', 'backend/.music-cache/one.audio',
                         'backend/.music-cache/pending.part', '.deploy-backups/old/blog.db',
                         'backend/venv/dependency', 'frontend/node_modules/dependency',
                         'frontend/dist.backup.old/index.html', 'frontend/dist/index.html']:
                path = root / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(b'test')
            with patch.object(export, 'ROOT', root):
                skipped = export.export_project(stage)
            saved = sorted(str(p.relative_to(stage / 'project')).replace('\\', '/')
                           for p in (stage / 'project').rglob('*') if p.is_file())
            self.assertEqual(saved, ['backend/.env', 'backend/.music-cache/one.audio',
                                     'backend/uploads/avatar.webp', 'frontend/dist/index.html'])
            self.assertEqual(len(skipped), 1)

    def make_archive(self, root, entries):
        archive = root / 'export.tar.gz'
        with tarfile.open(archive, 'w:gz') as bundle:
            for name, content in entries.items():
                info = tarfile.TarInfo(name); info.size = len(content)
                bundle.addfile(info, io.BytesIO(content))
        return archive

    def test_archive_hash_file_hash_and_sqlite_integrity_are_verified(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with closing(sqlite3.connect(root / 'db')) as db:
                db.execute('CREATE TABLE notes (value TEXT)'); db.commit()
            content = (root / 'db').read_bytes()
            manifest = {'files': [{'path': 'project/backend/blog.db', 'bytes': len(content),
                         'sha256': export.digest(root / 'db')}], 'total_bytes': len(content), 'r2': {'objects': 0, 'bytes': 0}}
            archive = self.make_archive(root, {'project/backend/blog.db': content,
                                               'manifest.json': json.dumps(manifest).encode()})
            unpack(archive, root / 'valid', export.digest(archive))
            with self.assertRaises(RuntimeError):
                unpack(archive, root / 'bad-hash', '0' * 64)
            manifest['files'][0]['sha256'] = '0' * 64
            archive = self.make_archive(root, {'project/backend/blog.db': content,
                                               'manifest.json': json.dumps(manifest).encode()})
            with self.assertRaises(RuntimeError):
                unpack(archive, root / 'bad-file', export.digest(archive))

    def test_unsafe_member_cannot_escape_export_directory(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            archive = self.make_archive(root, {'../escaped.txt': b'unsafe'})
            with self.assertRaises(RuntimeError):
                unpack(archive, root / 'out', export.digest(archive))
            self.assertFalse((root / 'escaped.txt').exists())


if __name__ == '__main__':
    unittest.main()
