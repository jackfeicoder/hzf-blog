"""Guarded targeted release based on the inspected production snapshot."""
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import tarfile

FILES = ['backend/routers/music.py','backend/music_routing.py','frontend/src/music/api.js',
         'frontend/src/music/controller.js','frontend/src/music/store.js','frontend/src/music/Sources.jsx']
ROOT = Path('/www/wwwroot/blog.120115.xyz')


def normalized_hash(blob):
    return hashlib.sha256(blob.replace(b'\r\n',b'\n')).hexdigest()


def state_fingerprint():
    with sqlite3.connect('file:'+str(ROOT/'backend/blog.db')+'?mode=ro',uri=True) as db:
        sources = db.execute('SELECT id,digest,enabled,position,status,capabilities FROM music_sources ORDER BY id').fetchall()
        appearance = db.execute('SELECT * FROM site_appearance ORDER BY id').fetchall()
        counts = {table:db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0] for table in ('music_sources','music_lists','music_entries')}
    return {'sources': normalized_hash(json.dumps(sources).encode()),'appearance':normalized_hash(json.dumps(appearance,default=str).encode()), 'counts':counts}


def pack():
    local = Path(__file__).resolve().parents[1]
    archive = local/'.local-history/music-reliability-release.tar.gz'
    with tarfile.open(local/'.local-history/music-online-20261007.tar.gz') as original:
        expected = {member.name:normalized_hash(original.extractfile(member).read()) for member in original.getmembers() if member.isfile()}
    paths = [local/name for name in FILES]
    paths += list((local/'backend').glob('*.py'))+list((local/'backend/routers').glob('*.py'))+list((local/'backend/tests').glob('test_*.py'))
    paths += list((local/'frontend/dist').rglob('*'))
    paths += [Path(__file__).resolve(),local/'tools/deploy_study.py',local/'tools/verify_music_reliability.py']
    import io
    with tarfile.open(archive,'w:gz') as bundle:
        for path in sorted(set(paths)):
            if path.is_file(): bundle.add(path,arcname=path.relative_to(local),recursive=False)
        payload=json.dumps(expected).encode()
        info=tarfile.TarInfo('baseline.json');info.size=len(payload)
        bundle.addfile(info,io.BytesIO(payload))
    print(archive)


def release(stage):
    from deploy_study import release as publish
    stage=stage.resolve(strict=True)
    if stage.parent != Path('/tmp') or not stage.name.startswith('hzf-study-music-reliable-'):
        raise RuntimeError('Unexpected staging directory')
    for name,digest in json.loads((stage/'baseline.json').read_text()).items():
        if not (ROOT/name).is_file() or normalized_hash((ROOT/name).read_bytes()) != digest:
            raise RuntimeError('Production source differs from inspected baseline: '+name)
    before=state_fingerprint()
    print('PRESERVED_BEFORE='+json.dumps(before),flush=True)
    backup=publish(stage,files=FILES,required_paths=('/api/music/resolve','/api/music/lyrics/resolve','/api/music/diagnostics','/api/music/feedback','/api/appearance'))
    after=state_fingerprint()
    assert before['sources']==after['sources'] and before['appearance']==after['appearance'], 'Runtime configuration changed during release; inspect before further action'
    print('RUNTIME_CONFIG_PRESERVED='+json.dumps(after),flush=True)
    print('MUSIC_RELIABILITY_RELEASE_OK; BACKUP='+str(backup),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('mode',choices=['pack','release']);parser.add_argument('stage',nargs='?')
    args=parser.parse_args()
    pack() if args.mode=='pack' else release(Path(args.stage))
