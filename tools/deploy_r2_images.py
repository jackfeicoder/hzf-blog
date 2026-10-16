"""Targeted image release with code/DB/uploads/config backup and rollback.

Windows: python tools/deploy_r2_images.py pack
Linux:   backend/venv/bin/python tools/deploy_r2_images.py release /tmp/hzf-images-<mktemp-id>
No credentials are put in the release archive. Runtime .r2.env is staged via SSH.
"""
import argparse
import io
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import time
from datetime import datetime, timezone
from urllib.request import Request, urlopen

ROOT = Path("/www/wwwroot/blog.120115.xyz")
FILES = ["backend/main.py", "backend/routers/upload.py", "backend/image_storage.py",
         "backend/image_static.py", "backend/requirements.txt", "frontend/src/api.js",
         "frontend/src/components/Layout.jsx", "frontend/src/index.css", "frontend/src/pages/Profile.jsx",
         "frontend/src/pages/Editor.jsx", "frontend/src/utils.js", "frontend/src/imageAssets.js"]
DROPIN = Path("/etc/systemd/system/hzf-blog.service.d/95-r2-images.conf")
RUNTIME_ENV = ROOT / "backend/r2-images.env"


def pack():
    local = Path(__file__).resolve().parents[1]
    archive = local / ".local-history/r2-images-release.tar.gz"
    with tarfile.open(archive, "w:gz") as bundle:
        # Complete Python sources permit isolated staging tests without reading
        # a real production DB or shipping unrelated backend files to production.
        paths = list((local / "backend").glob("*.py")) + list((local / "backend/routers").glob("*.py"))
        paths += list((local / "backend/tests").glob("test_*.py"))
        paths += [local / name for name in FILES]
        paths += list((local / "frontend/dist").rglob("*"))
        paths += [Path(__file__).resolve()]
        for path in sorted(set(paths)):
            if path.is_file():
                bundle.add(path, arcname=path.relative_to(local), recursive=False)
    print(archive)


def copy_atomic(source, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".r2-release-tmp")
    shutil.copy2(source, temporary)
    os.replace(temporary, destination)


def health():
    for _ in range(30):
        try:
            with urlopen("http://127.0.0.1:8001/api/health", timeout=2) as response:
                if json.load(response).get("status") == "ok":
                    return
        except Exception:
            pass
        time.sleep(0.5)
    raise RuntimeError("Backend health check failed")


def load_env(path):
    values = dict(line.split("=", 1) for line in path.read_text().splitlines() if "=" in line)
    expected = {"IMAGE_STORAGE", "R2_ACCOUNT_ID", "R2_BUCKET", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_PUBLIC_BASE_URL"}
    if set(values) != expected or any(not value for value in values.values()):
        raise RuntimeError("Incomplete image runtime configuration")
    if values["R2_PUBLIC_BASE_URL"] != "https://img.120115.xyz" or values["R2_BUCKET"] != "hzf-blog-images":
        raise RuntimeError("Unexpected image destination")
    return values


def release(stage):
    stage = stage.resolve(strict=True)
    if stage.parent != Path("/tmp") or not stage.name.startswith("hzf-images-") or not ROOT.is_dir():
        raise RuntimeError("Unexpected staging/application path")
    for name in FILES + ["frontend/dist/index.html", ".r2.env"]:
        if not (stage / name).is_file():
            raise RuntimeError(f"Missing release input: {name}")
    config = load_env(stage / ".r2.env")
    python = str(ROOT / "backend/venv/bin/python")
    pid = subprocess.check_output(["systemctl", "show", "hzf-blog.service", "-p", "MainPID", "--value"], text=True).strip()
    existing_env = dict(entry.split(b"=", 1) for entry in Path(f"/proc/{pid}/environ").read_bytes().split(b"\0") if b"=" in entry)
    if existing_env.get(b"DATABASE_URL", b"sqlite:///./blog.db").decode() not in ("sqlite:///./blog.db", "sqlite:///blog.db", f"sqlite:///{ROOT}/backend/blog.db"):
        raise RuntimeError("Unexpected production database location")
    health()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = ROOT / ".deploy-backups" / ("r2-images-" + stamp)
    backup.mkdir(parents=True, mode=0o700)
    os.chmod(backup.parent, 0o700)
    existed = {}
    for name in FILES:
        target = ROOT / name
        existed[name] = target.exists()
        if target.is_file():
            saved = backup / name
            saved.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, saved)
    shutil.copytree(ROOT / "frontend/dist", backup / "frontend/dist")
    shutil.copytree(ROOT / "backend/uploads", backup / "uploads")
    for key, target in (("runtime.env", RUNTIME_ENV), ("dropin.conf", DROPIN)):
        existed[key] = target.exists()
        if target.exists():
            shutil.copy2(target, backup / key)
    with sqlite3.connect(f"file:{ROOT / 'backend/blog.db'}?mode=ro", uri=True) as source:
        with sqlite3.connect(backup / "blog.db") as destination:
            source.backup(destination)
    freeze = subprocess.check_output([python, "-m", "pip", "freeze"], text=True)
    (backup / "dependencies.txt").write_text(freeze)
    (backup / "manifest.json").write_text(json.dumps({"files": FILES, "existed": existed, "stage": str(stage)}, indent=2))
    print(f"BACKUP={backup}", flush=True)
    switched = False
    try:
        subprocess.run([python, "-m", "pip", "install", "Pillow>=11.3,<13", "boto3>=1.40,<2"], check=True)
        subprocess.run([python, "-W", "ignore::DeprecationWarning", "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py", "-q"],
            cwd=stage / "backend", check=True, env={**os.environ, "IMAGE_STORAGE": "local"})
        # Prove SDK upload/public HTTPS/cache headers before switching live code.
        sys.path.insert(0, str(stage / "backend"))
        os.environ.update(config)
        import image_storage
        from PIL import Image
        fixture = io.BytesIO()
        Image.new("RGB", (32, 24), "#ff5733").save(fixture, "PNG")
        image = image_storage.store_image(fixture.getvalue(), "images", 0)
        # The zone's Browser Integrity Check rejects Python's default UA (1010).
        # Check the real browser access path without changing zone security.
        with urlopen(Request(image["url"], headers={"User-Agent": "Mozilla/5.0"}), timeout=20) as response:
            if response.status != 200 or response.headers.get("Cache-Control") != image_storage.CACHE_CONTROL or response.read(4) != b"RIFF":
                raise RuntimeError("R2 public object/cache smoke check failed")
        print(json.dumps({"R2_SMOKE": "ok", "url": image["url"], "browser_cache_days": 30}), flush=True)
        switched = True
        for name in FILES:
            copy_atomic(stage / name, ROOT / name)
        copy_atomic(stage / ".r2.env", RUNTIME_ENV)
        os.chmod(RUNTIME_ENV, 0o600)
        DROPIN.parent.mkdir(parents=True, exist_ok=True)
        DROPIN.write_text(f"[Service]\nEnvironmentFile={RUNTIME_ENV}\n")
        os.chmod(DROPIN, 0o644)
        subprocess.run(["systemctl", "daemon-reload"], check=True)
        subprocess.run(["systemctl", "restart", "hzf-blog.service"], check=True)
        health()
        for path in (stage / "frontend/dist").rglob("*"):
            if path.is_file() and path.name != "index.html":
                copy_atomic(path, ROOT / "frontend/dist" / path.relative_to(stage / "frontend/dist"))
        copy_atomic(stage / "frontend/dist/index.html", ROOT / "frontend/dist/index.html")
        (backup / "result.json").write_text(json.dumps({"status": "RELEASE_OK", "smoke_url": image["url"]}))
        print("RELEASE_OK", flush=True)
    except Exception:
        if switched:
            for name in FILES:
                if existed[name]:
                    copy_atomic(backup / name, ROOT / name)
                elif (ROOT / name).is_file():
                    (ROOT / name).unlink()
            for key, target in (("runtime.env", RUNTIME_ENV), ("dropin.conf", DROPIN)):
                if existed[key]:
                    copy_atomic(backup / key, target)
                elif target.exists():
                    target.unlink()
            copy_atomic(backup / "frontend/dist/index.html", ROOT / "frontend/dist/index.html")
            subprocess.run(["systemctl", "daemon-reload"], check=False)
            subprocess.run(["systemctl", "restart", "hzf-blog.service"], check=False)
            print("APPLICATION_ROLLED_BACK; live database preserved", flush=True)
        else:
            print("PREFLIGHT_FAILED; live application was not switched", flush=True)
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["pack", "release"])
    parser.add_argument("stage", nargs="?")
    args = parser.parse_args()
    if args.mode == "pack":
        pack()
    else:
        release(Path(args.stage))
