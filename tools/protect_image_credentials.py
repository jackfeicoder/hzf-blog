"""Ignore the deployed runtime secret without replacing server Git preferences."""
from pathlib import Path
import shutil
import subprocess
import sys

root = Path("/www/wwwroot/blog.120115.xyz")
backup = Path(sys.argv[1]).resolve(strict=True)
assert backup.parent == root / ".deploy-backups" and backup.name.startswith("r2-images-")
ignored = subprocess.run(["git", "check-ignore", "--quiet", "backend/r2-images.env"], cwd=root)
if ignored.returncode != 0:
    target = root / ".gitignore"
    saved = backup / "gitignore.before"
    if saved.exists():
        raise RuntimeError("An ignore-file backup already exists; inspect it first")
    if target.exists():
        shutil.copy2(target, saved)
    old = target.read_text() if target.exists() else ""
    target.write_text(old.rstrip() + "\n\n# Deployed server-side R2 credentials\n/backend/r2-images.env\n")
    subprocess.run(["git", "check-ignore", "--quiet", "backend/r2-images.env"], cwd=root, check=True)
print("RUNTIME_CREDENTIALS_GIT_IGNORED")
