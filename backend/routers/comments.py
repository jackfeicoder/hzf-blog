from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

import models
import schemas
from auth import get_current_user
from database import get_db

router = APIRouter(prefix="/api", tags=["comments"])


@router.get("/posts/{post_id}/comments", response_model=list[schemas.CommentOut])
def list_comments(post_id: int, db: Session = Depends(get_db)):
    if not db.get(models.Post, post_id):
        raise HTTPException(status_code=404, detail="文章不存在")
    return (
        db.query(models.Comment)
        .filter(models.Comment.post_id == post_id)
        .order_by(models.Comment.created_at.asc())
        .all()
    )


@router.post("/posts/{post_id}/comments", response_model=schemas.CommentOut)
def create_comment(
    post_id: int,
    data: schemas.CommentIn,
    current: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    post = db.get(models.Post, post_id)
    if not post:
        raise HTTPException(status_code=404, detail="文章不存在")
    parent_id = None
    if data.parent_id:
        parent = db.get(models.Comment, data.parent_id)
        if not parent or parent.post_id != post_id:
            raise HTTPException(status_code=400, detail="被回复的评论不存在")
        # 统一挂到顶层评论下（两级结构）
        parent_id = parent.parent_id or parent.id
    comment = models.Comment(
        post_id=post_id,
        user_id=current.id,
        parent_id=parent_id,
        reply_to=data.reply_to,
        content=data.content,
    )
    post.comment_count += 1
    db.add(comment)
    db.commit()
    db.refresh(comment)
    return comment


@router.delete("/comments/{comment_id}")
def delete_comment(
    comment_id: int,
    current: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    comment = db.get(models.Comment, comment_id)
    if not comment:
        raise HTTPException(status_code=404, detail="评论不存在")
    post = db.get(models.Post, comment.post_id)
    allowed = current.is_admin or comment.user_id == current.id or (post and post.user_id == current.id)
    if not allowed:
        raise HTTPException(status_code=403, detail="无权删除此评论")
    # 删除顶层评论时连同回复一起删
    replies = db.query(models.Comment).filter(models.Comment.parent_id == comment.id).all()
    removed = 1 + len(replies)
    for r in replies:
        db.delete(r)
    db.delete(comment)
    if post:
        post.comment_count = max(0, post.comment_count - removed)
    db.commit()
    return {"ok": True}
