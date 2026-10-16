from datetime import datetime, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from auth import require_superadmin
from database import get_db
import models
import schemas
from schemas import PublicUserBrief as UserBrief
from public_identity import public_name, ADMIN_LOGIN, ADMIN_ALIAS


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


def visit_day_start(now=None):
    """UTC storage boundary for the current Asia/Shanghai calendar day."""
    now = now or datetime.utcnow()
    return (now + timedelta(hours=8)).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(hours=8)


def record_visit(request: Request, db: Session, user: Optional[models.User] = None, path: str = None):
    """同 IP 每个北京时间自然日仅记录一次，保留七天滚动清理。"""
    try:
        now = datetime.utcnow()
        day_start = visit_day_start(now)
        ip = get_client_ip(request)
        target_path = path or request.url.path
        user_agent = request.headers.get("User-Agent", "")[:500]

        # Unique DB claim serializes concurrent requests, including other workers.
        if db.get_bind().dialect.name == 'sqlite':
            # Starts a real write transaction even in SQLite legacy mode;
            # claim and log commit together, without rolling back pending views.
            claimed = db.execute(sqlite_insert(models.VisitDay).values(ip=ip, day_start=day_start)
                                 .on_conflict_do_nothing(index_elements=['ip', 'day_start']))
            if claimed.rowcount == 0:
                return
        else:
            try:
                with db.begin_nested():
                    db.add(models.VisitDay(ip=ip, day_start=day_start))
                    db.flush()
            except IntegrityError:
                return
        # Honor records written earlier today, before this rule was deployed.
        recent_exists = (
            db.query(models.VisitLog.id)
            .filter(
                models.VisitLog.ip == ip,
                models.VisitLog.created_at >= day_start,
                models.VisitLog.created_at < day_start + timedelta(days=1),
            )
            .first()
        )
        if recent_exists:
            db.commit()
            return

        # 2. 写入新访问日志
        log = models.VisitLog(
            ip=ip,
            user_id=user.id if user else None,
            path=target_path[:200],
            user_agent=user_agent,
            created_at=now,
        )
        db.add(log)

        # 3. 自动滚动清理：删除 7 天前的旧日志，保持数据库轻量化
        seven_days_ago = now - timedelta(days=7)
        db.query(models.VisitLog).filter(models.VisitLog.created_at < seven_days_ago).delete(
            synchronize_session=False
        )
        db.query(models.VisitDay).filter(models.VisitDay.day_start < day_start - timedelta(days=7)).delete(synchronize_session=False)

        db.commit()
    except Exception:
        db.rollback()



@router.get("", response_model=VisitorsSummaryOut)
@router.get("/", response_model=VisitorsSummaryOut, include_in_schema=False)
def get_visitors(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_superadmin),
):
    """仅站点管理员可查看访客数据，访问日志继续正常收集。"""
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Vary"] = "Authorization"
    # 记录当前查询访客页面的访问行为
    record_visit(request, db, user, path="/visitors")

    total_visits = db.query(models.VisitLog).count()

    today_start = visit_day_start()
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
            disp_name = public_name(log.user) if log.user else f"游客 ({log.ip})"

        user_brief = UserBrief.model_validate(log.user) if log.user else None

        items.append(
            VisitorItemOut(
                id=log.id,
                ip=log.ip,
                display_name=disp_name,
                is_guest=is_guest,
                path=log.path.replace(f"/u/{ADMIN_LOGIN}", f"/u/{ADMIN_ALIAS}"),
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
