"""Business-level administration; never expose hashes or raw database writes."""
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field, SecretStr, field_validator
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, defer

import models
import schemas
from auth import hash_password, require_superadmin, verify_delete_password
from database import get_db
from routers import study
from routers.posts import remove_post
from study_models import StudyDay, StudyProgress, StudyRound


def private_response(response: Response):
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Vary"] = "Authorization"


router = APIRouter(prefix="/api/admin", tags=["admin"],
                   dependencies=[Depends(require_superadmin), Depends(private_response)])


def get_user(db, user_id):
    user = db.get(models.User, user_id)
    if not user:
        raise HTTPException(404, "用户不存在")
    return user


def page_json(query, page, page_size, serialize):
    total = query.order_by(None).count()
    return {"items": [serialize(row) for row in query.offset((page - 1) * page_size).limit(page_size).all()],
            "total": total, "page": page, "page_size": page_size}


@router.get("/posts", response_model=schemas.PostPage)
def posts(page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=50), search: str = "",
          db: Session = Depends(get_db)):
    query = db.query(models.Post).options(defer(models.Post.content)).order_by(models.Post.id.desc())
    if search:
        query = query.filter(models.Post.title.contains(search))
    return page_json(query, page, page_size, schemas.PostListItem.model_validate)


@router.get("/users")
def users(page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=50), search: str = "",
          db: Session = Depends(get_db)):
    query = db.query(models.User).order_by(models.User.id)
    if search:
        query = query.filter(or_(models.User.username.contains(search), models.User.nickname.contains(search)))
    return page_json(query, page, page_size, schemas.UserOut.model_validate)


class UserCreate(schemas.RegisterIn):
    password: SecretStr = Field(min_length=6, max_length=100)
    model_config = {"extra": "forbid"}

    @field_validator("username")
    @classmethod
    def username_required(cls, value):
        if value != value.strip() or not value.strip():
            raise ValueError("用户名请勿包含首尾空格")
        return value


@router.post("/users", response_model=schemas.UserOut, status_code=201)
def create_user(body: UserCreate, db: Session = Depends(get_db)):
    password = body.password.get_secret_value()
    if len(password.encode("utf-8")) > 72:
        raise HTTPException(400, "密码长度请控制在 72 字节内")
    user = models.User(username=body.username, nickname=body.nickname or body.username,
                       password_hash=hash_password(password))
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "用户名已存在")
    return user


class UserEdit(schemas.UserUpdate):
    model_config = {"extra": "forbid"}


@router.put("/users/{user_id}", response_model=schemas.UserOut)
def edit_user(user_id: int, body: UserEdit, db: Session = Depends(get_db)):
    user = get_user(db, user_id)
    for key, value in body.model_dump(exclude_none=True).items():
        setattr(user, key, value)
    db.commit()
    return user


def clear_study(db, user_id):
    round_ids = db.query(StudyRound.id).filter_by(user_id=user_id)
    db.query(StudyProgress).filter(StudyProgress.round_id.in_(round_ids)).delete(synchronize_session=False)
    db.query(StudyDay).filter_by(user_id=user_id).delete(synchronize_session=False)
    db.query(StudyRound).filter_by(user_id=user_id).delete(synchronize_session=False)


@router.delete("/users/{user_id}")
def delete_user(user_id: int, body: schemas.PostDeleteIn, db: Session = Depends(get_db),
                current=Depends(require_superadmin)):
    user = get_user(db, user_id)
    if user.username == "jackfei":
        raise HTTPException(409, "请保留 jackfei 超级管理员账户")
    verify_delete_password(current, body.password.get_secret_value())
    # Remove owned posts first; clean remaining interactions and repair counters.
    for post in list(db.query(models.Post).filter_by(user_id=user.id).all()):
        remove_post(db, post)
    comment_ids = [row.id for row in db.query(models.Comment.id).filter_by(user_id=user.id).all()]
    affected = {row.post_id for row in db.query(models.Comment.post_id).filter(
        or_(models.Comment.user_id == user.id, models.Comment.parent_id.in_(comment_ids))).all()}
    for model, counter in ((models.Like, "like_count"), (models.Favorite, "favorite_count")):
        ids = [r.post_id for r in db.query(model.post_id).filter_by(user_id=user.id).all()]
        db.query(model).filter_by(user_id=user.id).delete(synchronize_session=False)
        for post_id in ids:
            db.query(models.Post).filter_by(id=post_id).update({counter: db.query(func.count(model.id)).filter_by(post_id=post_id).scalar()})
    db.query(models.Comment).filter(or_(models.Comment.user_id == user.id, models.Comment.parent_id.in_(comment_ids))).delete(synchronize_session=False)
    for post_id in affected:
        db.query(models.Post).filter_by(id=post_id).update({"comment_count": db.query(func.count(models.Comment.id)).filter_by(post_id=post_id).scalar()})
    db.query(models.Follow).filter(or_(models.Follow.follower_id == user.id, models.Follow.followed_id == user.id)).delete(synchronize_session=False)
    db.query(models.Notification).filter(or_(models.Notification.user_id == user.id, models.Notification.sender_id == user.id)).delete(synchronize_session=False)
    db.query(models.VisitLog).filter_by(user_id=user.id).update({"user_id": None}, synchronize_session=False)
    clear_study(db, user.id)
    from music_models import clear_music
    clear_music(db, user.id)
    db.query(models.PasswordState).filter_by(user_id=user.id).delete(synchronize_session=False)
    db.query(models.User).filter_by(id=user.id).delete(synchronize_session=False)
    db.commit()
    return {"ok": True}


class NameInput(BaseModel):
    name: str = Field(min_length=1, max_length=50)
    model_config = {"extra": "forbid"}

    @field_validator("name")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("请输入名称")
        return value.strip()


@router.get("/categories")
def categories(db: Session = Depends(get_db)):
    return [{"id": c.id, "name": c.name, "post_count": count} for c, count in db.query(
        models.Category, func.count(models.Post.id)).outerjoin(models.Post).group_by(models.Category.id).order_by(models.Category.id).all()]


def save_category(db, category, name):
    category.name = name
    db.add(category)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "分类名称已存在")
    return {"id": category.id, "name": category.name}


@router.post("/categories", status_code=201)
def add_category(body: NameInput, db: Session = Depends(get_db)):
    return save_category(db, models.Category(), body.name)


@router.put("/categories/{category_id}")
def edit_category(category_id: int, body: NameInput, db: Session = Depends(get_db)):
    category = db.get(models.Category, category_id)
    if not category:
        raise HTTPException(404, "分类不存在")
    return save_category(db, category, body.name)


@router.delete("/categories/{category_id}")
def delete_category(category_id: int, db: Session = Depends(get_db)):
    category = db.get(models.Category, category_id)
    if not category:
        raise HTTPException(404, "分类不存在")
    db.query(models.Post).filter_by(category_id=category_id).update({"category_id": None}, synchronize_session=False)
    db.delete(category)
    db.commit()
    return {"ok": True}


@router.get("/comments")
def comments(page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=50), search: str = "",
             db: Session = Depends(get_db)):
    query = db.query(models.Comment).order_by(models.Comment.id.desc())
    if search:
        query = query.filter(models.Comment.content.contains(search))
    return page_json(query, page, page_size, schemas.CommentOut.model_validate)


class CommentEdit(BaseModel):
    content: str = Field(min_length=1, max_length=2000)
    model_config = {"extra": "forbid"}

    @field_validator("content")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("评论内容为空")
        return value.strip()


@router.put("/comments/{comment_id}", response_model=schemas.CommentOut)
def edit_comment(comment_id: int, body: CommentEdit, db: Session = Depends(get_db)):
    comment = db.get(models.Comment, comment_id)
    if not comment:
        raise HTTPException(404, "评论不存在")
    comment.content = body.content
    db.commit()
    return comment


@router.get("/users/{user_id}/study/today")
def study_today(user_id: int, response: Response, db: Session = Depends(get_db)):
    return study.read_today(response, db, get_user(db, user_id))


@router.put("/users/{user_id}/study/tasks/{key}")
def study_task(user_id: int, key: str, body: study.TaskUpdate, response: Response, db: Session = Depends(get_db)):
    return study.update_task(key, body, response, db, get_user(db, user_id))


@router.get("/users/{user_id}/study/progress")
def study_progress(user_id: int, response: Response, db: Session = Depends(get_db)):
    return study.read_progress(response, db, get_user(db, user_id))


@router.get("/users/{user_id}/study/history")
def study_history(user_id: int, response: Response, month: str = "", db: Session = Depends(get_db)):
    return study.history(response, month, db, get_user(db, user_id))


@router.post("/users/{user_id}/study/rounds/{kind}/next")
def study_next(user_id: int, kind: study.Kind, body: study.NextRound, db: Session = Depends(get_db)):
    return study.next_round(kind, body, db, get_user(db, user_id))


@router.delete("/users/{user_id}/study")
def reset_study(user_id: int, body: schemas.PostDeleteIn, db: Session = Depends(get_db),
                current=Depends(require_superadmin)):
    get_user(db, user_id)
    verify_delete_password(current, body.password.get_secret_value())
    clear_study(db, user_id)
    db.commit()
    return {"ok": True}
