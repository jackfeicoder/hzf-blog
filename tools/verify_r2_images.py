"""Post-release smoke check; run in the Linux application virtual environment.

Only adds one tiny public test image. Never changes an avatar/account or prints
credentials. Private app settings and the short-lived probe token stay in memory.
"""
import io
import json
import os
from pathlib import Path
import subprocess
import sys

import httpx
from PIL import Image

ROOT = Path("/www/wwwroot/blog.120115.xyz")
pid = subprocess.check_output(["systemctl", "show", "hzf-blog.service", "-p", "MainPID", "--value"], text=True).strip()
for entry in Path(f"/proc/{pid}/environ").read_bytes().split(b"\0"):
    if b"=" in entry:
        key, value = entry.split(b"=", 1)
        os.environ[key.decode()] = value.decode()
if os.getenv("IMAGE_STORAGE") != "r2" or os.getenv("R2_PUBLIC_BASE_URL") != "https://img.120115.xyz":
    raise RuntimeError("Running service did not load R2 configuration")
sys.path.insert(0, str(ROOT / "backend"))
os.chdir(ROOT / "backend")
from auth import create_access_token
from database import SessionLocal
from models import User

with SessionLocal() as db:
    user = db.query(User).filter_by(username="jackfei").one()
    token = create_access_token(user.username, user)
out = io.BytesIO()
Image.new("RGB", (40, 30), "#ff8058").save(out, "PNG")
with httpx.Client(trust_env=False, timeout=35, headers={"User-Agent": "Mozilla/5.0"}) as client:
    before = client.get("http://127.0.0.1:8001/api/health")
    assert before.status_code == 200
    upload = client.post("http://127.0.0.1:8001/api/upload/image", headers={"Authorization": "Bearer " + token},
        files={"file": ("r2-smoke.png", out.getvalue(), "image/png")})
    if upload.status_code != 200:
        raise RuntimeError(f"Live upload failed: HTTP {upload.status_code}")
    result = upload.json()
    assert result["url"].startswith("https://img.120115.xyz/images/")
    assert upload.headers["cache-control"] == "private, no-store"
    reads = []
    for _ in range(2):
        response = client.get(result["url"])
        assert response.status_code == 200 and response.content.startswith(b"RIFF")
        assert response.headers["cache-control"] == "public, max-age=2592000, immutable"
        reads.append({"status": response.status_code, "cache": response.headers.get("cf-cache-status"),
            "seconds": round(response.elapsed.total_seconds(), 3)})
    website = {}
    for path in ("/", "/music", "/api/health", "/api/posts?page=1&page_size=1"):
        response = client.get("https://blog.120115.xyz:8443" + path)
        website[path] = response.status_code
        assert response.status_code == 200
    anonymous = client.post("https://blog.120115.xyz:8443/api/upload/image",
        files={"file": ("r2-smoke.png", out.getvalue(), "image/png")})
    assert anonymous.status_code == 401
    old = next((path for path in (ROOT / "backend/uploads").rglob("*") if path.is_file()
                and path.suffix.lower() in {".png", ".webp", ".jpg", ".jpeg", ".gif"}), None)
    old_result = None
    if old:
        old_url = "https://blog.120115.xyz:8443/uploads/" + old.relative_to(ROOT / "backend/uploads").as_posix()
        response = client.get(old_url)
        old_result = {"status": response.status_code, "cache": response.headers.get("cache-control"), "url": old_url}
print(json.dumps({"live_upload": "ok", "image_url": result["url"], "dimensions": [result["width"], result["height"]],
    "public_reads": reads, "website": website, "anonymous_upload": anonymous.status_code,
    "legacy_image": old_result, "credentials_file_mode": oct((ROOT / "backend/r2-images.env").stat().st_mode & 0o777)}))
