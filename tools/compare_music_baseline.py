"""Compare normalized text against the inspected production archive; no overwrite."""
import hashlib
from pathlib import Path
import tarfile

root = Path(__file__).resolve().parents[1]
with tarfile.open(root/'.local-history/music-online-20261007.tar.gz') as bundle:
    differences = []
    for member in bundle.getmembers():
        if not member.isfile():
            continue
        remote = bundle.extractfile(member).read().replace(b'\r\n', b'\n')
        local = root / member.name
        if not local.is_file() or local.read_bytes().replace(b'\r\n', b'\n') != remote:
            differences.append(member.name)
    print('BASELINE_DIFFERENCES='+repr(differences))
