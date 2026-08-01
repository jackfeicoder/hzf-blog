from datetime import datetime, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from auth import get_current_user_optional
from database import get_db
import models
from schemas import UserBrief

router = APIRouter(prefix="/api/visitors", tags=["visitors"])


class VisitorItemOut(BaseModel):
    id: int
    ip: str
    display_name: str
    is_guest: bool
    path: str
    user_agent: str
    created_at: datetime
    user: Optional[UserBrief] = None

    model_config = {"from_attributes": True}


class VisitorsSummaryOut(BaseModel):
    total_visits: int
    today_visit_count: int
    today_ip_count: int
    items: list[VisitorItemOut]


def get_client_ip(request: Request) -> str:
    """真实 IP 提取（支持 Nginx 反向代理 X-Forwarded-For）"""
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        # X-Forwarded-For 形式: client_ip, proxy1, proxy2
        client_ip = forwarded_for.split(",")[0].strip()
        if client_ip:
            return client_ip
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip.strip()
    if request.client:
        return request.client.host
    return "127.0.0.1"


def record_visit(request: Request, db: Session, user: Optional[models.User] = None, path: str = None):
    """记录访问日志辅助函数"""
    try:
        ip = get_client_ip(request)
        target_path = path or request.url.path
        user_agent = request.headers.get("User-Agent", "")[:500]

        # 过滤连刷，避免同一个 IP 1 秒内大量并发打爆日志
        log = models.VisitLog(
            ip=ip,
            user_id=user.id if user else None,
            path=target_path[:200],
            user_agent=user_agent,
        )
        db.add(log)
        db.commit()
    except Exception:
        db.rollback()


@router.get("", response_model=VisitorsSummaryOut)
def get_visitors(
    request: Request,
    db: Session = Depends(get_db),
    user: Optional[models.User] = Depends(get_current_user_optional),
):
    """获取实时访客数据与近期访问历史，同时记录本次访问看板"""
    # 记录当前查询访客页面的访问行为
    record_visit(request, db, user, path="/visitors")

    total_visits = db.query(models.VisitLog).count()

    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    today_visit_count = (
        db.query(models.VisitLog).filter(models.VisitLog.created_at >= today_start).count()
    )

    today_ip_count = (
        db.query(func.count(func.distinct(models.VisitLog.ip)))
        .filter(models.VisitLog.created_at >= today_start)
        .scalar()
        or 0
    )

    logs = (
        db.query(models.VisitLog)
        .order_by(models.VisitLog.created_at.desc())
        .limit(100)
        .all()
    )

    items = []
    for log in logs:
        is_guest = log.user_id is None
        if is_guest:
            disp_name = f"游客 ({log.ip})"
        else:
            disp_name = log.user.nickname or log.user.username if log.user else f"游客 ({log.ip})"

        user_brief = schemas.UserBrief.model_validate(log.user) if log.user else None

        items.append(
            VisitorItemOut(
                id=log.id,
                ip=log.ip,
                display_name=disp_name,
                is_guest=is_guest,
                path=log.path,
                user_agent=log.user_agent,
                created_at=log.created_at,
                user=user_brief,
            )
        )

    return VisitorsSummaryOut(
        total_visits=total_visits,
        today_visit_count=today_visit_count,
        today_ip_count=today_ip_count,
        items=items,
    )
