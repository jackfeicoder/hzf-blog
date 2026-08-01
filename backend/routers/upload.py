import os
import uuid
from datetime import datetime
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from auth import get_current_user
from database import get_db
import models

router = APIRouter(prefix="/api/upload", tags=["upload"])

UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "uploads")
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB


def _ensure_dir(path: str):
    if not os.path.exists(path):
        os.makedirs(path, exist_ok=True)


@router.post("/image")
async def upload_image(file: UploadFile = File(...)):
    """上传文章图片或通用图片"""
    ext = os.path.splitext(file.filename)[1].lower() if file.filename else ""
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的图片格式: {ext}，仅支持 jpg, png, gif, webp",
        )

    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="文件大小不能超过 5MB")

    month_str = datetime.utcnow().strftime("%Y%m")
    sub_dir = os.path.join(UPLOAD_DIR, "images", month_str)
    _ensure_dir(sub_dir)

    filename = f"{uuid.uuid4().hex}{ext or '.png'}"
    filepath = os.path.join(sub_dir, filename)

    with open(filepath, "wb") as f:
        f.write(content)

    url = f"/uploads/images/{month_str}/{filename}"
    return {"url": url}


@router.post("/avatar")
async def upload_avatar(
    file: UploadFile = File(...),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """上传并更改当前用户头像"""
    ext = os.path.splitext(file.filename)[1].lower() if file.filename else ""
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的图片格式: {ext}，仅支持 jpg, png, gif, webp",
        )

    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="文件大小不能超过 5MB")

    sub_dir = os.path.join(UPLOAD_DIR, "avatars")
    _ensure_dir(sub_dir)

    filename = f"avatar_{current_user.id}_{uuid.uuid4().hex[:8]}{ext or '.png'}"
    filepath = os.path.join(sub_dir, filename)

    with open(filepath, "wb") as f:
        f.write(content)

    url = f"/uploads/avatars/{filename}"
    current_user.avatar_url = url
    db.commit()
    db.refresh(current_user)

    return {"url": url, "user": current_user}
