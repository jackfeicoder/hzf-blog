from fastapi import APIRouter, Depends, File, Response, UploadFile
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
from sqlalchemy.orm import Session

from auth import get_current_user
from database import get_db
from image_storage import MAX_FILE_SIZE, check_upload_rate, store_image
from schemas import UserOut
import models

router = APIRouter(prefix="/api/upload", tags=["upload"])

class ImageOut(BaseModel):
    url: str
    width: int
    height: int
    bytes: int


class AvatarOut(ImageOut):
    user: UserOut


async def save_upload(file, kind, user):
    check_upload_rate(user.id)
    try:
        content = await file.read(MAX_FILE_SIZE + 1)
        return await run_in_threadpool(store_image, content, kind, user.id)
    finally:
        await file.close()


@router.post("/image", response_model=ImageOut)
async def upload_image(response: Response, file: UploadFile = File(...),
                       current_user: models.User = Depends(get_current_user)):
    response.headers["Cache-Control"] = "private, no-store"
    return await save_upload(file, "images", current_user)


@router.post("/avatar", response_model=AvatarOut)
async def upload_avatar(
    response: Response,
    file: UploadFile = File(...),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    response.headers["Cache-Control"] = "private, no-store"
    result = await save_upload(file, "avatars", current_user)
    current_user.avatar_url = result["url"]
    db.commit()
    db.refresh(current_user)

    return {**result, "user": UserOut.model_validate(current_user)}
