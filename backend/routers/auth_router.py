from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from datetime import datetime
from sqlalchemy.orm import Session

import models
import schemas
from auth import create_access_token, get_current_user, hash_password, verify_password, consume_security_attempt, clear_security_attempt
from database import get_db

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


@router.post("/register", response_model=schemas.TokenOut)
def register(data: schemas.RegisterIn, db: Session = Depends(get_db)):
    if len(data.password.encode("utf-8")) > 72:
        raise HTTPException(400, "密码长度请控制在 72 字节内")
    if db.query(models.User).filter(models.User.username == data.username).first():
        raise HTTPException(status_code=400, detail="用户名已存在")
    user = models.User(
        username=data.username,
        password_hash=hash_password(data.password),
        nickname=data.nickname or data.username,
    )
    db.add(user)
    db.commit()
    return schemas.TokenOut(access_token=create_access_token(user.username, user))


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
