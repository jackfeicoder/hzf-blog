from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

import models
import schemas
from auth import get_current_user, get_current_user_optional
from database import get_db

router = APIRouter(prefix="/api/users", tags=["users"])


def _get_user_or_404(db: Session, username: str) -> models.User:
    user = db.query(models.User).filter(models.User.username == username).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    return user


@router.get("/{username}", response_model=schemas.UserProfile)
def profile(
    username: str,
    db: Session = Depends(get_db),
    viewer: Optional[models.User] = Depends(get_current_user_optional),
):
    user = _get_user_or_404(db, username)
    stats = (
        db.query(
            func.count(models.Post.id),
            func.coalesce(func.sum(models.Post.like_count), 0),
            func.coalesce(func.sum(models.Post.views), 0),
        )
        .filter(models.Post.user_id == user.id, models.Post.published == True)  # noqa: E712
        .first()
    )
    out = schemas.UserProfile.model_validate(user)
    out.post_count, out.total_likes, out.total_views = stats
    out.follower_count = (
        db.query(models.Follow).filter(models.Follow.followed_id == user.id).count()
    )
    out.following_count = (
        db.query(models.Follow).filter(models.Follow.follower_id == user.id).count()
    )
    if viewer:
        out.is_following = (
            db.query(models.Follow)
            .filter_by(follower_id=viewer.id, followed_id=user.id)
            .first()
            is not None
        )
    return out


@router.post("/{username}/follow", response_model=schemas.ToggleOut)
def toggle_follow(
    username: str,
    current: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    target = _get_user_or_404(db, username)
    if target.id == current.id:
        raise HTTPException(status_code=400, detail="不能关注自己")
    row = (
        db.query(models.Follow)
        .filter_by(follower_id=current.id, followed_id=target.id)
        .first()
    )
    if row:
        db.delete(row)
        active = False
    else:
        db.add(models.Follow(follower_id=current.id, followed_id=target.id))
        active = True
    db.commit()
    count = db.query(models.Follow).filter(models.Follow.followed_id == target.id).count()
    return schemas.ToggleOut(active=active, count=count)


@router.get("/{username}/following", response_model=list[schemas.UserBrief])
def following(username: str, db: Session = Depends(get_db)):
    user = _get_user_or_404(db, username)
    rows = (
        db.query(models.User)
        .join(models.Follow, models.Follow.followed_id == models.User.id)
        .filter(models.Follow.follower_id == user.id)
        .all()
    )
    return rows


@router.get("/{username}/followers", response_model=list[schemas.UserBrief])
def followers(username: str, db: Session = Depends(get_db)):
    user = _get_user_or_404(db, username)
    rows = (
        db.query(models.User)
        .join(models.Follow, models.Follow.follower_id == models.User.id)
        .filter(models.Follow.followed_id == user.id)
        .all()
    )
    return rows


@router.get("/{username}/favorites", response_model=schemas.PostPage)
def favorites(
    username: str,
    page: int = 1,
    page_size: int = 10,
    db: Session = Depends(get_db),
):
    user = _get_user_or_404(db, username)
    q = (
        db.query(models.Post)
        .join(models.Favorite, models.Favorite.post_id == models.Post.id)
        .filter(models.Favorite.user_id == user.id, models.Post.published == True)  # noqa: E712
        .order_by(models.Favorite.created_at.desc())
    )
    total = q.count()
    items = q.offset((page - 1) * page_size).limit(page_size).all()
    return schemas.PostPage(items=items, total=total, page=page, page_size=page_size)
