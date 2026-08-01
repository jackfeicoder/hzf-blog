from typing import Optional
from datetime import datetime
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from auth import get_current_user
from database import get_db
import models
from schemas import UserBrief

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


class NotificationPostBrief(BaseModel):
    id: int
    title: str

    model_config = {"from_attributes": True}


class NotificationOut(BaseModel):
    id: int
    type: str
    content: str
    is_read: bool
    created_at: datetime
    sender: Optional[UserBrief] = None
    post: Optional[NotificationPostBrief] = None

    model_config = {"from_attributes": True}


class NotificationsResponse(BaseModel):
    items: list[NotificationOut]
    unread_count: int


@router.get("", response_model=NotificationsResponse)
def get_notifications(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取当前用户的消息通知列表"""
    notifications = (
        db.query(models.Notification)
        .filter(models.Notification.user_id == current_user.id)
        .order_by(models.Notification.created_at.desc())
        .limit(50)
        .all()
    )

    unread_count = (
        db.query(models.Notification)
        .filter(
            models.Notification.user_id == current_user.id,
            models.Notification.is_read == False,
        )
        .count()
    )

    return NotificationsResponse(items=notifications, unread_count=unread_count)


@router.post("/read-all")
def mark_read_all(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """将所有消息标记为已读"""
    db.query(models.Notification).filter(
        models.Notification.user_id == current_user.id,
        models.Notification.is_read == False,
    ).update({"is_read": True}, synchronize_session=False)
    db.commit()
    return {"message": "已全部标记为已读"}
