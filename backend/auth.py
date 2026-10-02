import os
import threading
import time
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

import models
from database import get_db

SECRET_KEY = os.getenv("SECRET_KEY", "change-me-in-production")
ALGORITHM = "HS256"
TOKEN_EXPIRE_MINUTES = 60 * 24 * 30  # 30 天，配合前端 localStorage 持久登录

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
bearer_scheme = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def is_superadmin(user) -> bool:
    return bool(user and user.username == "jackfei")


_delete_attempts = {}
_delete_lock = threading.Lock()


def verify_delete_password(user, password):
    """Five confirmation attempts per five minutes, separate from login."""
    now = time.monotonic()
    with _delete_lock:
        expired = [key for key, (started, _) in _delete_attempts.items() if now - started >= 300]
        for key in expired:
            _delete_attempts.pop(key, None)
        started, count = _delete_attempts.get(user.id, (now, 0))
        if count >= 5:
            raise HTTPException(429, "密码确认次数过多，请 5 分钟后再试", headers={"Retry-After": str(max(1, int(300 - (now - started))))})
        if len(_delete_attempts) >= 4096 and user.id not in _delete_attempts:
            raise HTTPException(429, "确认请求较多，请稍后再试")
        _delete_attempts[user.id] = (started, count + 1)
    try:
        valid = verify_password(password, user.password_hash)
    except (ValueError, TypeError):
        valid = False
    if not valid:
        raise HTTPException(403, "密码错误，文章未删除")
    with _delete_lock:
        _delete_attempts.pop(user.id, None)


def create_access_token(username: str, user=None) -> str:
    payload = {
        "sub": username,
        "iat": datetime.utcnow(),
        "exp": datetime.utcnow() + timedelta(minutes=TOKEN_EXPIRE_MINUTES),
    }
    if user is not None:
        payload["uid"] = user.id
        payload["account_created"] = user.created_at.isoformat()
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def token_matches_account(payload, user):
    if user is None:
        return False
    if "uid" in payload and payload["uid"] != user.id:
        return False
    if "account_created" in payload and payload["account_created"] != user.created_at.isoformat():
        return False
    # Legacy tokens used a fixed 30-day expiry. Reject an old account's token
    # when its username is later reused, without logging out existing accounts.
    try:
        issued = int(payload.get("iat", int(payload["exp"]) - TOKEN_EXPIRE_MINUTES * 60))
        created = int(user.created_at.replace(tzinfo=timezone.utc).timestamp())
    except (KeyError, ValueError, TypeError):
        return False
    return issued >= created


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> models.User:
    exc = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未登录或登录已过期")
    if credentials is None:
        raise exc
    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        username = payload.get("sub")
    except JWTError:
        raise exc
    user = db.query(models.User).filter(models.User.username == username).first()
    if not token_matches_account(payload, user):
        raise exc
    return user


def get_current_user_optional(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> models.User | None:
    """未登录返回 None，不抛异常"""
    if credentials is None:
        return None
    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        username = payload.get("sub")
    except JWTError:
        return None
    user = db.query(models.User).filter(models.User.username == username).first()
    return user if token_matches_account(payload, user) else None


def require_superadmin(user=Depends(get_current_user)):
    if not is_superadmin(user):
        raise HTTPException(403, "仅 jackfei 可以使用管理功能")
    return user
