from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from auth import get_current_user
from database import get_db
from media_models import VideoLink

router = APIRouter(prefix="/api/media/videos", tags=["media"])


def video_admin(user=Depends(get_current_user)):
    if user.username != "jackfei":
        raise HTTPException(403, "仅管理员可以管理视频链接")
    return user


class VideoInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    title: str = Field(min_length=1, max_length=80)
    url: str = Field(min_length=1, max_length=2000)
    description: str = Field(default="", max_length=300)
    position: int = Field(default=0, ge=0, le=1000000)

    @field_validator("url")
    @classmethod
    def validate_url(cls, value):
        try:
            parts = urlsplit(value)
            port = parts.port  # Also reject malformed ports.
            valid = parts.scheme.lower() in ("http", "https") and parts.hostname
            valid = valid and not parts.username and not parts.password
            valid = valid and not any(char.isspace() or ord(char) < 32 for char in value)
            valid = valid and "\\" not in value and (port is None or port > 0)
        except ValueError:
            valid = False
        if not valid:
            raise ValueError("请输入完整的 http:// 或 https:// 网站链接")
        return value


class VideoOut(VideoInput):
    model_config = ConfigDict(from_attributes=True)
    id: int


def get_link(db, link_id):
    row = db.get(VideoLink, link_id)
    if row is None:
        raise HTTPException(404, "该链接已被删除，请刷新列表")
    return row


@router.get("", response_model=list[VideoOut])
def list_links(response: Response, db: Session = Depends(get_db)):
    # Clients keep a short memory cache; avoid persistent stale HTTP responses
    # after administrators edit the public directory.
    response.headers["Cache-Control"] = "no-store"
    return db.query(VideoLink).order_by(VideoLink.position, VideoLink.id).all()


@router.post("", response_model=VideoOut, status_code=201)
def create_link(data: VideoInput, db: Session = Depends(get_db), user=Depends(video_admin)):
    row = VideoLink(**data.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.put("/{link_id}", response_model=VideoOut)
def update_link(link_id: int, data: VideoInput, db: Session = Depends(get_db), user=Depends(video_admin)):
    row = get_link(db, link_id)
    for name, value in data.model_dump().items():
        setattr(row, name, value)
    db.commit()
    db.refresh(row)
    return row


@router.delete("/{link_id}", status_code=204)
def delete_link(link_id: int, db: Session = Depends(get_db), user=Depends(video_admin)):
    db.delete(get_link(db, link_id))
    db.commit()
    return Response(status_code=204)
