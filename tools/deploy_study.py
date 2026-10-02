"""Targeted, backed-up study release. Run on the existing Linux blog host.

python deploy_study.py /tmp/verified-staging-directory
Only the listed application files and built frontend are published.
"""
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone
from urllib.request import urlopen

ROOT = Path("/www/wwwroot/blog.120115.xyz")
FILES = [
    "backend/main.py", "backend/study_models.py", "backend/routers/study.py",
    "frontend/src/App.jsx", "frontend/src/api.js",
    "frontend/src/components/Layout.jsx", "frontend/src/pages/Study.jsx",
    "frontend/src/pages/study.css",
    "backend/routers/posts.py", "backend/routers/users.py",
    "frontend/src/AuthContext.jsx", "frontend/src/queryCache.js",
    "frontend/src/format.js", "frontend/src/utils.js", "frontend/package.json",
    "frontend/src/components/PostCard.jsx", "frontend/src/pages/Home.jsx",
    "frontend/src/pages/PostPage.jsx", "frontend/src/pages/Editor.jsx",
    "frontend/src/pages/Rank.jsx", "frontend/src/pages/Profile.jsx",
    "frontend/src/pages/Visitors.jsx",
]


def atomic_copy(source, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".study-release-tmp")
    shutil.copy2(source, temporary)
    os.replace(temporary, destination)


def health(required_paths):
    for _ in range(30):
        try:
            with urlopen("http://127.0.0.1:8001/api/health", timeout=2) as response:
                if json.load(response).get("status") == "ok":
                    with urlopen("http://127.0.0.1:8001/openapi.json", timeout=2) as schema:
                        if set(required_paths).issubset(json.load(schema)["paths"]):
                            return
        except Exception:
            pass
        time.sleep(0.5)
    raise RuntimeError("New backend did not pass health and route checks")


def release(stage, files=None, required_paths=("/api/study/today",)):
    files = FILES if files is None else files
    stage = stage.resolve(strict=True)
    if not ROOT.is_dir() or not str(stage).startswith("/tmp/hzf-study-"):
        raise RuntimeError("Unexpected deployment directory")
    for name in files + ["frontend/dist/index.html"]:
        if not (stage / name).is_file():
            raise RuntimeError(f"Missing release file: {name}")
    pid = subprocess.check_output(["systemctl", "show", "hzf-blog.service", "-p", "MainPID", "--value"], text=True).strip()
    env = dict(entry.split(b"=", 1) for entry in Path(f"/proc/{pid}/environ").read_bytes().split(b"\0") if b"=" in entry)
    database_url = env.get(b"DATABASE_URL", b"sqlite:///./blog.db").decode()
    if database_url not in ("sqlite:///./blog.db", "sqlite:///blog.db", f"sqlite:///{ROOT}/backend/blog.db"):
        raise RuntimeError("Database location differs from the inspected SQLite file")
    db_path = ROOT / "backend/blog.db"
    if not db_path.is_file():
        raise RuntimeError("Existing database missing")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = ROOT / ".deploy-backups" / f"study-{stamp}"
    backup.mkdir(parents=True, mode=0o700)
    os.chmod(backup.parent, 0o700)
    existed = {}
    for name in files:
        target = ROOT / name
        existed[name] = target.exists()
        if target.exists():
            saved = backup / name
            saved.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, saved)
    shutil.copytree(ROOT / "frontend/dist", backup / "frontend/dist")
    with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as source:
        with sqlite3.connect(backup / "blog.db") as destination:
            source.backup(destination)
    print(f"BACKUP={backup}", flush=True)
    try:
        for name in files:
            atomic_copy(stage / name, ROOT / name)
        subprocess.run([
            str(ROOT / "backend/venv/bin/python"), "-m", "unittest", "discover",
            "-s", str(stage / "backend/tests"), "-p", "test_*.py", "-v",
        ], cwd=ROOT / "backend", check=True)
        subprocess.run(["systemctl", "restart", "hzf-blog.service"], check=True)
        health(required_paths)
        # Publish content-addressed assets first; index.html is the final switch.
        for source in (stage / "frontend/dist").rglob("*"):
            if source.is_file() and source.name != "index.html":
                atomic_copy(source, ROOT / "frontend/dist" / source.relative_to(stage / "frontend/dist"))
        atomic_copy(stage / "frontend/dist/index.html", ROOT / "frontend/dist/index.html")
        print("RELEASE_OK", flush=True)
    except Exception:
        for name, present in existed.items():
            if present:
                atomic_copy(backup / name, ROOT / name)
            elif (ROOT / name).is_file():
                (ROOT / name).unlink()
        atomic_copy(backup / "frontend/dist/index.html", ROOT / "frontend/dist/index.html")
        # Keep additive study tables in place; never overwrite live user data
        # during application rollback. A coherent pre-release DB is backed up.
        subprocess.run(["systemctl", "restart", "hzf-blog.service"], check=False)
        print("APPLICATION_ROLLED_BACK; database backup retained", flush=True)
        raise


if __name__ == "__main__":
    release(Path(sys.argv[1]))
