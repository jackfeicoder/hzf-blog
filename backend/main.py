import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from fastapi.staticfiles import StaticFiles

import models  # noqa: F401  确保模型注册到 Base.metadata
from auth import hash_password
from database import Base, SessionLocal, engine
from routers import auth_router, comments, posts, users, upload, notifications, visitors
from routers.chat import router as chat_router

DEFAULT_CATEGORIES = ["后端", "前端", "移动开发", "人工智能", "数据库", "运维", "算法", "生活随笔"]

# 创建 uploads 目录
uploads_dir = os.path.join(os.path.dirname(__file__), "uploads")
os.makedirs(uploads_dir, exist_ok=True)

@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        # 首次启动创建管理员账户（可通过环境变量覆盖）
        if not db.query(models.User).first():
            username = os.getenv("ADMIN_USERNAME", "root")
            password = os.getenv("ADMIN_PASSWORD", "123456")
            db.add(
                models.User(
                    username=username,
                    password_hash=hash_password(password),
                    nickname=username,
                    is_admin=True,
                )
            )
            db.commit()
            print(f"[init] 已创建管理员账户: {username} / {password}（请尽快修改）")
        # 预置分类
        if not db.query(models.Category).first():
            for name in DEFAULT_CATEGORIES:
                db.add(models.Category(name=name))
            db.commit()
            print(f"[init] 已创建 {len(DEFAULT_CATEGORIES)} 个默认分类")
    yield


app = FastAPI(title="Personal Blog API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:5173").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/uploads", StaticFiles(directory=uploads_dir), name="uploads")

app.include_router(auth_router.router)
app.include_router(posts.router)
app.include_router(comments.router)
app.include_router(users.router)
app.include_router(chat_router)
app.include_router(upload.router)
app.include_router(notifications.router)
app.include_router(visitors.router)




@app.get("/api/health")
def health():
    return {"status": "ok"}

