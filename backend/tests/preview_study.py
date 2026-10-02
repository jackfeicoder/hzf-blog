"""Optional local UI fixture. Never reads or writes the real blog database.

From backend: python -m uvicorn preview_study:app --app-dir tests --port 8000
Demo login: study-demo / demo-study-123 (local development only).
"""
import tempfile
from pathlib import Path

from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from auth import hash_password
from database import Base, get_db
from models import Post, User
from routers import auth_router, posts, study, comments, media, admin, music
from media_models import VideoLink
from study_models import StudyItem
from music_models import MusicList, MusicEntry
import json

workspace = tempfile.TemporaryDirectory(prefix="blog-study-preview-")
engine = create_engine(f"sqlite:///{Path(workspace.name) / 'preview.db'}", connect_args={"check_same_thread": False})
Base.metadata.create_all(engine)
sessions = sessionmaker(bind=engine, autoflush=False)
with sessions() as db:
    user = User(username="study-demo", nickname="学习体验", password_hash=hash_password("demo-study-123"), is_admin=True)
    db.add(user)
    db.add(User(username="jackfei", nickname="jackfei", password_hash=hash_password("demo-media-123"), is_admin=True))
    db.add(VideoLink(title="示例视频站", url="https://example.com", description="仅用于本地页面验证的示例链接。", position=0))
    db.flush()
    db.add(Post(id=1, title="Java八股", content="# Java 基础\n## 集合\n1. HashMap 的扩容机制是什么？\n数组容量翻倍，并重新分配桶位置。\n2. ArrayList 与 LinkedList 有什么区别？\n分别基于动态数组与链表。", user_id=user.id))
    db.add(Post(id=5, title="Hot100", content="# Hot100\n1. 两数之和\n使用哈希表。\n2. 字母异位词分组\n以字符频次作为分组键。", user_id=user.id))
    for n, title in enumerate(["HashMap 的扩容机制", "ArrayList 与 LinkedList 的区别", "String 为什么不可变", "线程池的核心参数", "JVM 的垃圾回收机制", "volatile 的内存可见性"]):
        db.add(StudyItem(kind="java", title=title, source_url="/post/1", answer="示例参考内容，可由管理员修改。", position=n))
    for n, title in enumerate(["两数之和", "字母异位词分组", "最长连续序列"]):
        db.add(StudyItem(kind="hot100", title=title, source_url="/post/5", position=n))
    study.seed_bank(db)
    jackfei = db.query(User).filter_by(username='jackfei').one()
    favorites = MusicList(user_id=jackfei.id, name='我喜欢', kind='favorites'); db.add(favorites); db.flush()
    for i, name in enumerate(['晴天 · 测试音频', '代码与旋律', '慢慢听'], 1):
        db.add(MusicEntry(list_id=favorites.id, song_key=f'wy:{i}', song=json.dumps(dict(source='wy', id=str(i), name=name, singer='本地测试音频', album='交互测试', pic_id='', lyric_id=str(i), duration=60))))
    db.commit()


def database_override():
    with sessions() as db:
        yield db


app = FastAPI()
app.dependency_overrides[get_db] = database_override
app.include_router(auth_router.router)
app.include_router(posts.router)
app.include_router(study.router)
app.include_router(comments.router)
app.include_router(media.router)
app.include_router(admin.router)

# Deterministic music fixture: generated tone, never touches live accounts/music.
import io
import math
import struct
import wave
from fastapi import Response, Request
from music_models import MusicSource
buffer = io.BytesIO()
with wave.open(buffer, 'wb') as tone:
    tone.setnchannels(1); tone.setsampwidth(2); tone.setframerate(8000)
    tone.writeframes(b''.join(struct.pack('<h', int(800 * math.sin(2 * math.pi * 220 * n / 8000))) for n in range(8000 * 60)))
tone_bytes = buffer.getvalue()


async def fixture_upstream(url, options=None):
    from urllib.parse import urlsplit, parse_qs
    q = parse_qs(urlsplit(url).query)
    if q.get('types') == ['search']:
        return [dict(id=str(i), name=name, artist=['本地测试音频'], album='交互测试', pic_id='', lyric_id=str(i)) for i, name in enumerate(['晴天 · 测试音频', '代码与旋律', '慢慢听'], 1)]
    if q.get('types') == ['lyric']:
        return {'lyric': '[00:00]这是播放器交互测试\n[00:03]点击歌词可跳转\n[00:10]切换文章页面继续播放\n[00:20]收藏按账号保存', 'tlyric': ''}
    return {}
music.upstream = fixture_upstream


@app.post('/api/music/resolve')
async def fixture_resolve(body: music.Resolve):
    return {'url': '/api/music/fixture-audio', 'source_id': 1, 'source_name': '本地测试音频', 'expires_in': 1800}


@app.get('/api/music/fixture-audio')
def fixture_audio(request: Request):
    import re
    match = re.fullmatch(r'bytes=(\d+)-(\d*)', request.headers.get('range', ''))
    if match:
        start = int(match[1]); end = min(int(match[2]) if match[2] else len(tone_bytes) - 1, len(tone_bytes) - 1)
        return Response(tone_bytes[start:end + 1], status_code=206, media_type='audio/wav', headers={'Content-Range': f'bytes {start}-{end}/{len(tone_bytes)}', 'Accept-Ranges': 'bytes'})
    return Response(tone_bytes, media_type='audio/wav', headers={'Accept-Ranges': 'bytes'})


app.include_router(music.router)


@app.get("/api/notifications")
def preview_notifications():
    return {"items": [], "unread_count": 0}
