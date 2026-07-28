import os

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

# 默认 SQLite；切换 MySQL 时设置环境变量，例如：
# DATABASE_URL="mysql+pymysql://user:password@localhost:3306/blog?charset=utf8mb4"
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./blog.db")

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(DATABASE_URL, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
