from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


# ---------- 用户 ----------
class RegisterIn(BaseModel):
    username: str = Field(min_length=2, max_length=50)
    password: str = Field(min_length=6, max_length=100)
    nickname: str = Field(default="", max_length=50)


class LoginIn(BaseModel):
    username: str
    password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserBrief(BaseModel):
    id: int
    username: str
    nickname: str

    model_config = {"from_attributes": True}


class UserOut(UserBrief):
    bio: str
    is_admin: bool
    created_at: datetime


class UserProfile(UserOut):
    """个人主页：带统计"""

    post_count: int = 0
    follower_count: int = 0
    following_count: int = 0
    total_likes: int = 0
    total_views: int = 0
    is_following: bool = False


class UserUpdate(BaseModel):
    nickname: Optional[str] = Field(default=None, max_length=50)
    bio: Optional[str] = Field(default=None, max_length=200)


# ---------- 分类 ----------
class CategoryOut(BaseModel):
    id: int
    name: str
    post_count: int = 0

    model_config = {"from_attributes": True}


# ---------- 文章 ----------
class PostIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1)
    summary: str = Field(default="", max_length=500)
    category_id: Optional[int] = None
    tags: list[str] = []
    published: bool = True


class TagOut(BaseModel):
    id: int
    name: str

    model_config = {"from_attributes": True}


class PostListItem(BaseModel):
    id: int
    title: str
    summary: str
    published: bool
    views: int
    like_count: int
    favorite_count: int
    comment_count: int
    created_at: datetime
    author: UserBrief
    category: Optional[CategoryOut] = None
    tags: list[TagOut] = []

    model_config = {"from_attributes": True}


class PostDetail(PostListItem):
    content: str
    updated_at: datetime
    liked: bool = False
    favorited: bool = False


class PostPage(BaseModel):
    items: list[PostListItem]
    total: int
    page: int
    page_size: int


class ToggleOut(BaseModel):
    active: bool
    count: int


# ---------- 评论 ----------
class CommentIn(BaseModel):
    content: str = Field(min_length=1, max_length=2000)
    parent_id: Optional[int] = None
    reply_to: str = ""


class CommentOut(BaseModel):
    id: int
    post_id: int
    parent_id: Optional[int]
    reply_to: str
    content: str
    created_at: datetime
    author: UserBrief

    model_config = {"from_attributes": True}


# ---------- 排行榜 ----------
class AuthorRankItem(BaseModel):
    user: UserBrief
    post_count: int
    total_views: int
    total_likes: int
