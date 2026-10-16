"""Versioned public images; blocking validation/storage run off the event loop."""
import io
import os
import re
import threading
import time
import uuid
import warnings
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import HTTPException
from PIL import Image, ImageOps, UnidentifiedImageError

MAX_FILE_SIZE = 2 * 1024 * 1024
CACHE_CONTROL = "public, max-age=2592000, immutable"
UPLOAD_DIR = Path(__file__).resolve().parent / "uploads"
FORMATS = {"JPEG": ("jpg", "image/jpeg"), "PNG": ("png", "image/png"),
           "GIF": ("gif", "image/gif"), "WEBP": ("webp", "image/webp")}
_upload_slots = threading.BoundedSemaphore(3)
_rate_lock = threading.Lock()
_attempts = {}


def check_upload_rate(user_id):
    """Per-process admission control, not a hard billing quota."""
    now = time.monotonic()
    with _rate_lock:
        for key in list(_attempts):
            if now - _attempts[key][0] >= 3600:
                del _attempts[key]
        started, count = _attempts.get(user_id, (now, 0))
        if count >= 20 or (len(_attempts) >= 4096 and user_id not in _attempts):
            raise HTTPException(429, "图片上传较频繁，请稍后再试", headers={"Retry-After": str(max(1, int(3600 - now + started)))})
        _attempts[user_id] = (started, count + 1)


def normalize_image(content, kind):
    if not content:
        raise HTTPException(400, "请选择非空图片")
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(413, "图片大小请控制在 2MB 以内")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(content)) as check:
                if check.format not in FORMATS:
                    raise HTTPException(400, "仅支持 JPG、PNG、GIF、WebP 图片")
                if check.width * check.height > 16_000_000:
                    raise HTTPException(400, "图片分辨率过大，请先缩小图片")
                check.verify()
            with Image.open(io.BytesIO(content)) as image:
                if getattr(image, "is_animated", False):
                    frames = getattr(image, "n_frames", 1)
                    if frames > 120 or frames * image.width * image.height > 40_000_000:
                        raise HTTPException(400, "动态图帧数或分辨率过大，请压缩后上传")
                    for frame in range(frames):
                        image.seek(frame)
                        image.load()
                    ext, mime = FORMATS[image.format]
                    return content, ext, mime, image.size
                image.load()
                image = ImageOps.exif_transpose(image)
                limit = 512 if kind == "avatars" else 1920
                image.thumbnail((limit, limit), Image.Resampling.LANCZOS)
                image = image.convert("RGBA" if "A" in image.getbands() or "transparency" in image.info else "RGB")
                output = io.BytesIO()
                image.save(output, "WEBP", quality=85, method=4)
                body = output.getvalue()
                if len(body) > MAX_FILE_SIZE:
                    raise HTTPException(413, "压缩后的图片仍超过 2MB，请先缩小图片")
                return body, "webp", "image/webp", image.size
    except HTTPException:
        raise
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise HTTPException(400, "图片内容无效或已损坏，请重新选择图片") from None


@lru_cache(maxsize=2)
def r2_client(account, access_key, secret_key):
    import boto3
    from botocore.config import Config
    return boto3.client("s3", endpoint_url=f"https://{account}.r2.cloudflarestorage.com",
                        aws_access_key_id=access_key, aws_secret_access_key=secret_key,
                        region_name="auto", config=Config(signature_version="s3v4",
                            connect_timeout=5, read_timeout=15,
                            retries={"total_max_attempts": 2, "mode": "standard"},
                            max_pool_connections=3))


def store_image(content, kind, user_id):
    if not _upload_slots.acquire(blocking=False):
        raise HTTPException(503, "图片上传繁忙，请稍后再试", headers={"Retry-After": "5"})
    try:
        body, ext, mime, (width, height) = normalize_image(content, kind)
        # Fresh opaque URLs avoid both stale replacements and login-name leaks.
        key = f"{kind}/{datetime.now(timezone.utc):%Y%m}/{uuid.uuid4().hex}.{ext}"
        provider = os.getenv("IMAGE_STORAGE", "local").lower()
        if provider == "r2":
            account = os.getenv("R2_ACCOUNT_ID", "")
            bucket = os.getenv("R2_BUCKET", "")
            access_key = os.getenv("R2_ACCESS_KEY_ID", "")
            secret_key = os.getenv("R2_SECRET_ACCESS_KEY", "")
            base = os.getenv("R2_PUBLIC_BASE_URL", "").rstrip("/")
            parsed = urlsplit(base)
            if (not re.fullmatch(r"[a-fA-F0-9]{32}", account) or not bucket or not access_key or not secret_key
                    or parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
                    or parsed.query or parsed.fragment):
                raise HTTPException(503, "图片存储配置尚未完成，请联系管理员")
            try:
                r2_client(account, access_key, secret_key).put_object(
                    Bucket=bucket, Key=key, Body=body, ContentType=mime,
                    CacheControl=CACHE_CONTROL)
            except Exception:
                # Never expose SDK failures containing signed request metadata.
                raise HTTPException(502, "图片存储暂时没有响应，请稍后重试") from None
            url = base + "/" + key
        elif provider == "local":
            target = UPLOAD_DIR / key
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(body)
            url = "/uploads/" + key
        else:
            raise HTTPException(503, "图片存储配置无效，请联系管理员")
        return {"url": url, "width": width, "height": height, "bytes": len(body)}
    finally:
        _upload_slots.release()
