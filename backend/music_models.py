from datetime import datetime
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from database import Base


class MusicSource(Base):
    __tablename__ = 'music_sources'
    id = Column(Integer, primary_key=True)
    name = Column(String(80), nullable=False)
    digest = Column(String(64), unique=True, nullable=False)
    script = Column(Text, nullable=False)
    enabled = Column(Boolean, default=False, nullable=False)
    position = Column(Integer, default=50, nullable=False)
    status = Column(String(100), default='待测试', nullable=False)
    capabilities = Column(Text, default='{}', nullable=False)


class MusicList(Base):
    __tablename__ = 'music_lists'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), index=True, nullable=False)
    name = Column(String(60), nullable=False)
    kind = Column(String(20), default='playlist', nullable=False)


class MusicEntry(Base):
    __tablename__ = 'music_entries'
    __table_args__ = (UniqueConstraint('list_id', 'song_key'),)
    id = Column(Integer, primary_key=True)
    list_id = Column(Integer, ForeignKey('music_lists.id', ondelete='CASCADE'), index=True, nullable=False)
    song_key = Column(String(220), nullable=False)
    song = Column(Text, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)


def clear_music(db, user_id):
    ids = db.query(MusicList.id).filter_by(user_id=user_id)
    db.query(MusicEntry).filter(MusicEntry.list_id.in_(ids)).delete(synchronize_session=False)
    db.query(MusicList).filter_by(user_id=user_id).delete(synchronize_session=False)
