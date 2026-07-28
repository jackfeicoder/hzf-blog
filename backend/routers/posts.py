from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

import models
import schemas
from auth import get_current_user, get_current_user_optional
from database import get_db

router = APIRouter(prefix="/api", tags=["posts"])

# 热度 = 浏览 + 点赞*5 + 收藏*5 + 评论*3
HOT_SCORE = (
    models.Post.views
    + models.Post.like_count * 5
    + models.Post.favorite_count * 5
    + models.Post.comment_count * 3
)


def _get_or_create_tags(db: Session, names: list[str]) -> list[models.Tag]:
    tags = []
    for name in {n.strip() for n in names if n.strip()}:
        tag = db.query(models.Tag).filter(models.Tag.name == name).first()
        if not tag:
            tag = models.Tag(name=name)
            db.add(tag)
        tags.append(tag)
    return tags


def _post_detail(post: models.Post, db: Session, user: Optional[models.User]) -> schemas.PostDetail:
    detail = schemas.PostDetail.model_validate(post)
    if user:
        detail.liked = (
            db.query(models.Like).filter_by(user_id=user.id, post_id=post.id).first() is not None
        )
        detail.favorited = (
            db.query(models.Favorite).filter_by(user_id=user.id, post_id=post.id).first()
            is not None
        )
    return detail


# ---------- 分类 ----------
@router.get("/categories", response_model=list[schemas.CategoryOut])
def list_categories(db: Session = Depends(get_db)):
    rows = (
        db.query(models.Category, func.count(models.Post.id))
        .outerjoin(
            models.Post,
            (models.Post.category_id == models.Category.id) & (models.Post.published == True),  # noqa: E712
        )
        .group_by(models.Category.id)
        .order_by(models.Category.id)
        .all()
    )
    return [
        schemas.CategoryOut(id=c.id, name=c.name, post_count=count) for c, count in rows
    ]


# ---------- 文章列表 ----------
@router.get("/posts", response_model=schemas.PostPage)
def list_posts(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=50),
    category_id: Optional[int] = None,
    tag: Optional[str] = None,
    search: Optional[str] = None,
    author: Optional[str] = None,
    sort: str = Query("new", pattern="^(new|hot)$"),
    db: Session = Depends(get_db),
    user: Optional[models.User] = Depends(get_current_user_optional),
):
    q = db.query(models.Post)
    if author:
        q = q.join(models.User, models.Post.user_id == models.User.id).filter(
            models.User.username == author
        )
        # 自己的主页可以看到草稿
        if not (user and user.username == author):
            q = q.filter(models.Post.published == True)  # noqa: E712
    else:
        q = q.filter(models.Post.published == True)  # noqa: E712
    if category_id:
        q = q.filter(models.Post.category_id == category_id)
    if tag:
        q = q.join(models.Post.tags).filter(models.Tag.name == tag)
    if search:
        like = f"%{search}%"
        q = q.filter(or_(models.Post.title.like(like), models.Post.content.like(like)))

    total = q.count()
    order = HOT_SCORE.desc() if sort == "hot" else models.Post.created_at.desc()
    posts = q.order_by(order).offset((page - 1) * page_size).limit(page_size).all()
    return schemas.PostPage(items=posts, total=total, page=page, page_size=page_size)


# ---------- 排行榜 ----------
@router.get("/rankings/posts", response_model=list[schemas.PostListItem])
def hot_posts(limit: int = Query(10, ge=1, le=30), db: Session = Depends(get_db)):
    return (
        db.query(models.Post)
        .filter(models.Post.published == True)  # noqa: E712
        .order_by(HOT_SCORE.desc(), models.Post.created_at.desc())
        .limit(limit)
        .all()
    )


@router.get("/rankings/authors", response_model=list[schemas.AuthorRankItem])
def top_authors(limit: int = Query(8, ge=1, le=30), db: Session = Depends(get_db)):
    rows = (
        db.query(
            models.User,
            func.count(models.Post.id).label("post_count"),
            func.coalesce(func.sum(models.Post.views), 0).label("total_views"),
            func.coalesce(func.sum(models.Post.like_count), 0).label("total_likes"),
        )
        .join(models.Post, models.Post.user_id == models.User.id)
        .filter(models.Post.published == True)  # noqa: E712
        .group_by(models.User.id)
        .order_by(
            (
                func.coalesce(func.sum(models.Post.views), 0)
                + func.coalesce(func.sum(models.Post.like_count), 0) * 5
            ).desc()
        )
        .limit(limit)
        .all()
    )
    return [
        schemas.AuthorRankItem(
            user=schemas.UserBrief.model_validate(u),
            post_count=pc,
            total_views=tv,
            total_likes=tl,
        )
        for u, pc, tv, tl in rows
    ]


# ---------- 文章 CRUD ----------
@router.post("/posts", response_model=schemas.PostDetail)
def create_post(
    data: schemas.PostIn,
    current: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    post = models.Post(
        title=data.title,
        content=data.content,
        summary=data.summary or data.content[:150],
        category_id=data.category_id,
        published=data.published,
        user_id=current.id,
        tags=_get_or_create_tags(db, data.tags),
    )
    db.add(post)
    db.commit()
    db.refresh(post)
    return _post_detail(post, db, current)


@router.get("/posts/{post_id}", response_model=schemas.PostDetail)
def get_post(
    post_id: int,
    inc_view: bool = True,
    db: Session = Depends(get_db),
    user: Optional[models.User] = Depends(get_current_user_optional),
):
    post = db.get(models.Post, post_id)
    if not post:
        raise HTTPException(status_code=404, detail="文章不存在")
    if not post.published and not (user and (user.id == post.user_id or user.is_admin)):
        raise HTTPException(status_code=404, detail="文章不存在")
    if inc_view:
        post.views += 1
        db.commit()
        db.refresh(post)
    return _post_detail(post, db, user)


@router.put("/posts/{post_id}", response_model=schemas.PostDetail)
def update_post(
    post_id: int,
    data: schemas.PostIn,
    current: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    post = db.get(models.Post, post_id)
    if not post:
        raise HTTPException(status_code=404, detail="文章不存在")
    if post.user_id != current.id and not current.is_admin:
        raise HTTPException(status_code=403, detail="无权修改此文章")
    post.title = data.title
    post.content = data.content
    post.summary = data.summary or data.content[:150]
    post.category_id = data.category_id
    post.published = data.published
    post.tags = _get_or_create_tags(db, data.tags)
    db.commit()
    db.refresh(post)
    return _post_detail(post, db, current)


@router.delete("/posts/{post_id}")
def delete_post(
    post_id: int,
    current: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    post = db.get(models.Post, post_id)
    if not post:
        raise HTTPException(status_code=404, detail="文章不存在")
    if post.user_id != current.id and not current.is_admin:
        raise HTTPException(status_code=403, detail="无权删除此文章")
    db.delete(post)
    db.commit()
    return {"ok": True}


# ---------- 点赞 / 收藏 ----------
def _toggle(db: Session, model, user_id: int, post: models.Post, counter: str) -> schemas.ToggleOut:
    row = db.query(model).filter_by(user_id=user_id, post_id=post.id).first()
    if row:
        db.delete(row)
        setattr(post, counter, max(0, getattr(post, counter) - 1))
        active = False
    else:
        db.add(model(user_id=user_id, post_id=post.id))
        setattr(post, counter, getattr(post, counter) + 1)
        active = True
    db.commit()
    return schemas.ToggleOut(active=active, count=getattr(post, counter))


@router.post("/posts/{post_id}/like", response_model=schemas.ToggleOut)
def toggle_like(
    post_id: int,
    current: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    post = db.get(models.Post, post_id)
    if not post:
        raise HTTPException(status_code=404, detail="文章不存在")
    return _toggle(db, models.Like, current.id, post, "like_count")


@router.post("/posts/{post_id}/favorite", response_model=schemas.ToggleOut)
def toggle_favorite(
    post_id: int,
    current: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    post = db.get(models.Post, post_id)
    if not post:
        raise HTTPException(status_code=404, detail="文章不存在")
    return _toggle(db, models.Favorite, current.id, post, "favorite_count")
