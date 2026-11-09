import secrets

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

import models
import schemas
from auth import create_access_token, get_current_user, hash_password, verify_password, consume_security_attempt, clear_security_attempt, require_superadmin
from database import get_db
from routers.visitors import get_client_ip

class PrivateAuthRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()
        async def handle(request):
            try:
                response = await original(request)
            except RequestValidationError as error:
                response = JSONResponse(status_code=422, content={"detail": [
                    {k: v for k, v in item.items() if k in ("loc", "msg", "type")}
                    for item in error.errors()
                ]})
            except HTTPException as error:
                error.headers = {**(error.headers or {}), "Cache-Control": "private, no-store"}
                raise
            response.headers["Cache-Control"] = "private, no-store"
            return response
        return handle


router = APIRouter(prefix="/api/auth", tags=["auth"], route_class=PrivateAuthRoute)
_dummy_hash = hash_password("authentication-timing-placeholder")


def invitation_required(db):
    settings = db.get(models.RegistrationSettings, 1)
    return settings.invite_required if settings is not None else True


@router.get("/registration-settings")
def registration_settings(db: Session = Depends(get_db)):
    return {"invite_required": invitation_required(db)}


@router.put("/registration-settings")
def update_registration_settings(data: schemas.RegistrationSettingsIn, db: Session = Depends(get_db),
                                 current: models.User = Depends(require_superadmin)):
    settings = db.get(models.RegistrationSettings, 1)
    if settings is None:
        db.add(models.RegistrationSettings(id=1, invite_required=data.invite_required))
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            db.query(models.RegistrationSettings).filter_by(id=1).update({"invite_required": data.invite_required})
            db.commit()
    else:
        settings.invite_required = data.invite_required
        db.commit()
    return {"invite_required": data.invite_required}


@router.post("/register", response_model=schemas.TokenOut)
def register(data: schemas.InvitedRegisterIn, request: Request, db: Session = Depends(get_db)):
    consume_security_attempt(("register-ip", get_client_ip(request)), limit=10)
    if len(data.password.encode("utf-8")) > 72:
        raise HTTPException(400, "密码长度请控制在 72 字节内")
    if db.query(models.User).filter(models.User.username == data.username).first():
        raise HTTPException(status_code=409, detail="用户名已存在，请登录或使用其他用户名")
    invite = None
    if invitation_required(db):
        code = data.invite_code.upper()
        invite = db.query(models.RegistrationInvite).filter_by(code=code, revoked=False, used_at=None).first()
        if invite is None:
            raise HTTPException(400, "邀请码无效、已使用或已作废，请联系管理员")
    user = models.User(
        username=data.username,
        password_hash=hash_password(data.password),
        nickname=data.nickname or data.username,
    )
    db.add(user)
    try:
        db.flush()
        # Claim in the same transaction as account creation, across workers.
        if invite is not None:
            claimed = db.query(models.RegistrationInvite).filter_by(
                id=invite.id, revoked=False, used_at=None,
            ).update({"used_at": datetime.utcnow(), "used_by": user.username}, synchronize_session=False)
            if claimed != 1:
                db.rollback()
                raise HTTPException(400, "邀请码无效、已使用或已作废，请联系管理员")
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "用户名已存在或邀请码已使用，请重试")
    return schemas.TokenOut(access_token=create_access_token(user.username, user))


@router.get("/welcome-author")
def welcome_author(db: Session = Depends(get_db)):
    author = db.query(models.User).filter_by(username='jackfei').first()
    if author is None:
        raise HTTPException(404, '作者信息尚未配置')
    return {**schemas.PublicUserBrief.model_validate(author).model_dump(), 'bio': author.bio or ''}


def invitation_out(invite):
    return {"id": invite.id, "code": invite.code, "created_at": invite.created_at,
            "used_at": invite.used_at, "used_by": invite.used_by,
            "status": "used" if invite.used_at else "revoked" if invite.revoked else "available"}


@router.get("/invitations")
def invitations(page: int = Query(1, ge=1), db: Session = Depends(get_db),
                current: models.User = Depends(require_superadmin)):
    query = db.query(models.RegistrationInvite)
    return {"items": [invitation_out(row) for row in query.order_by(models.RegistrationInvite.id.desc()).offset((page - 1) * 20).limit(20)],
            "total": query.count()}


@router.post("/invitations", status_code=201)
def create_invitation(db: Session = Depends(get_db), current: models.User = Depends(require_superadmin)):
    consume_security_attempt(("invite-create", current.id), limit=20)
    for _ in range(10):
        code = "".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(6))
        invite = models.RegistrationInvite(code=code, created_by=current.id)
        db.add(invite)
        try:
            db.commit()
            return invitation_out(invite)
        except IntegrityError:
            db.rollback()
    raise HTTPException(503, "邀请码生成繁忙，请重试")


@router.delete("/invitations/{invite_id}", status_code=204)
def revoke_invitation(invite_id: int, db: Session = Depends(get_db),
                      current: models.User = Depends(require_superadmin)):
    changed = db.query(models.RegistrationInvite).filter_by(id=invite_id, used_at=None, revoked=False).update(
        {"revoked": True}, synchronize_session=False)
    if changed != 1:
        db.rollback()
        raise HTTPException(409, "邀请码不存在、已使用或已作废")
    db.commit()
    return Response(status_code=204, headers={"Cache-Control": "private, no-store"})


@router.post("/login", response_model=schemas.TokenOut)
def login(data: schemas.LoginIn, request: Request, db: Session = Depends(get_db)):
    account_key = ("login", data.username)
    ip_key = ("login-ip", request.client.host if request.client else "unknown")
    consume_security_attempt(ip_key, limit=20)
    consume_security_attempt(account_key)
    user = db.query(models.User).filter(models.User.username == data.username).first()
    try:
        valid = verify_password(data.password.get_secret_value(), user.password_hash if user else _dummy_hash)
    except (ValueError, TypeError):
        valid = False
    if not user or not valid:
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    clear_security_attempt(account_key)
    clear_security_attempt(ip_key)
    return schemas.TokenOut(access_token=create_access_token(user.username, user))


@router.put("/password", status_code=204)
def change_password(data: schemas.PasswordChangeIn, current: models.User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    key = ("password", current.id)
    consume_security_attempt(key)
    old = data.current_password.get_secret_value()
    new = data.new_password.get_secret_value()
    if len(new) < 8 or len(new.encode("utf-8")) > 72:
        raise HTTPException(400, "新密码至少 8 个字符，UTF-8 长度不超过 72 字节")
    if new != data.confirm_password.get_secret_value():
        raise HTTPException(400, "两次输入的新密码不一致")
    if len(old.encode("utf-8")) > 1000:
        raise HTTPException(403, "当前密码错误")
    try:
        valid = verify_password(old, current.password_hash)
    except (ValueError, TypeError):
        valid = False
    if not valid:
        raise HTTPException(403, "当前密码错误")
    if verify_password(new, current.password_hash):
        raise HTTPException(400, "新密码应与当前密码不同")
    changed = db.query(models.User).filter_by(id=current.id, password_hash=current.password_hash).update(
        {"password_hash": hash_password(new)}, synchronize_session=False)
    if changed != 1:
        db.rollback()
        raise HTTPException(409, "密码已发生变化，请重新登录")
    state = db.get(models.PasswordState, current.id)
    if state is None:
        db.add(models.PasswordState(user_id=current.id))
    else:
        state.changed_at = datetime.utcnow()
    db.commit()
    clear_security_attempt(key)
    return Response(status_code=204, headers={"Cache-Control": "private, no-store"})


@router.get("/me", response_model=schemas.UserOut)
def me(current: models.User = Depends(get_current_user)):
    return current


@router.put("/me", response_model=schemas.UserOut)
def update_me(
    data: schemas.UserUpdate,
    current: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if data.nickname is not None:
        current.nickname = data.nickname
    if data.bio is not None:
        current.bio = data.bio
    db.commit()
    db.refresh(current)
    return current
