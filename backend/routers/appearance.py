"""Public site appearance with administrator-only writes."""
import os
import re
from typing import Literal

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from auth import require_superadmin
from database import get_db
from models import User, UserAppearance, SiteAppearance

router = APIRouter(prefix="/api/appearance", tags=["appearance"])


class AppearanceIn(BaseModel):
    theme: Literal["light", "dark"] = "light"
    palette: Literal["warm", "ocean", "forest", "violet"] = "warm"
    background: Literal["none", "aurora", "dawn", "custom"] = "aurora"
    background_url: str = Field(default="", max_length=500)
    cursor: Literal["system", "accent"] = "system"
    click_effect: Literal["ripple", "stars", "none"] = "ripple"
    motion: bool = True
    glass_transparency: int = Field(default=11, ge=0, le=80, strict=True)
    model_config = {"extra": "forbid", "from_attributes": True}

    @field_validator("background_url")
    @classmethod
    def uploaded_image_only(cls, value):
        if not value:
            return value
        base = os.getenv("R2_PUBLIC_BASE_URL", "").rstrip("/")
        pattern = r"images/\d{6}/[a-f0-9]{32}\.(webp|png|jpe?g|gif)"
        if re.fullmatch(r"/uploads/" + pattern, value):
            return value
        if base.startswith("https://") and re.fullmatch(re.escape(base) + "/" + pattern, value):
            return value
        raise ValueError("请使用本站上传的背景图片")

    @model_validator(mode="after")
    def custom_requires_image(self):
        if self.background == "custom" and not self.background_url:
            raise ValueError("请先上传背景图片")
        return self


class AppearanceUpdate(AppearanceIn):
    # Old clients autosaved personal preferences to this URL. Require an
    # explicit new-client scope so an old administrator tab cannot publish them.
    scope: Literal["site"]


def site_settings(db: Session):
    row = db.get(SiteAppearance, 1)
    if row:
        return AppearanceIn.model_validate(row)
    # Only the designated administrator's legacy preferences become public.
    # GET stays read-only, and other accounts' personal rows remain untouched.
    admin = db.query(User).filter_by(username="jackfei").first()
    legacy = db.get(UserAppearance, admin.id) if admin else None
    if legacy:
        values = {name: getattr(legacy, name) for name in AppearanceIn.model_fields if hasattr(legacy, name)}
        if values.get("theme") == "system":
            values["theme"] = "light"
        return AppearanceIn.model_validate(values)
    return AppearanceIn()


@router.get("", response_model=AppearanceIn)
def get_appearance(response: Response, db: Session = Depends(get_db)):
    response.headers["Cache-Control"] = "no-store"
    return site_settings(db)


@router.put("", response_model=AppearanceIn)
def save_appearance(data: AppearanceUpdate, response: Response, user: User = Depends(require_superadmin), db: Session = Depends(get_db)):
    response.headers["Cache-Control"] = "private, no-store"
    row = db.get(SiteAppearance, 1)
    if row is None:
        row = SiteAppearance(id=1)
        db.add(row)
    for key, value in data.model_dump(exclude={"scope"}).items():
        setattr(row, key, value)
    try:
        db.commit()
    except IntegrityError:
        # Concurrent first publishes still update the same singleton.
        db.rollback()
        row = db.get(SiteAppearance, 1)
        if row is None:
            raise
        for key, value in data.model_dump(exclude={"scope"}).items():
            setattr(row, key, value)
        db.commit()
    return data
