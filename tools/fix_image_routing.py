"""Back up and restore legacy images in this blog vhost only."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

target = Path("/www/server/panel/vhost/nginx/blog.120115.xyz.conf")
backup = Path(sys.argv[1]).resolve(strict=True)
assert backup.parent == Path("/www/wwwroot/blog.120115.xyz/.deploy-backups")
assert backup.name.startswith("r2-images-") and not target.is_symlink()
text = target.read_text()
marker = "    location /docs {"
if "location ^~ /uploads/" in text:
    raise RuntimeError("Uploads route already present; inspect before applying")
if text.count(marker) != 2 or text.count("server_name blog.120115.xyz;") != 2:
    raise RuntimeError("Unexpected vhost structure; no configuration changed")
route = """    # Legacy disk images remain readable; ^~ prevents the static-extension rule
    # from serving /uploads from frontend/dist instead of the API image directory.
    location ^~ /uploads/ {
        proxy_pass http://127.0.0.1:8001;
        proxy_set_header Host $host;
    }
"""
saved = backup / "nginx-blog.conf"
if saved.exists():
    raise RuntimeError("Backup already exists; do not overwrite it")
shutil.copy2(target, saved)
mode = target.stat().st_mode & 0o777
try:
    with tempfile.NamedTemporaryFile(mode="w", dir=target.parent, prefix=".blog-images-", delete=False) as output:
        output.write(text.replace(marker, route + marker))
        temporary = Path(output.name)
    os.chmod(temporary, mode)
    os.replace(temporary, target)
    subprocess.run(["nginx", "-t"], check=True)
    subprocess.run(["nginx", "-s", "reload"], check=True)
    print("LEGACY_IMAGE_ROUTE_RELOADED; BACKUP=" + str(saved))
except Exception:
    shutil.copy2(saved, target)
    subprocess.run(["nginx", "-t"], check=False)
    subprocess.run(["nginx", "-s", "reload"], check=False)
    print("NGINX_CONFIGURATION_RESTORED")
    raise
