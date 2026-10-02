"""Learning data is separate from articles; daily task text is an immutable snapshot."""
from sqlalchemy import Boolean, Column, ForeignKey, Integer, String, Text, UniqueConstraint
from database import Base


class StudyItem(Base):
    __tablename__ = "study_items"
    id = Column(Integer, primary_key=True)
    kind = Column(String(16), nullable=False, index=True)
    title = Column(String(500), nullable=False)
    answer = Column(Text, nullable=False, default="")
    source_url = Column(String(500), nullable=False, default="")
    position = Column(Integer, nullable=False, default=0)
    active = Column(Boolean, nullable=False, default=True)


class StudyRound(Base):
    __tablename__ = "study_rounds"
    __table_args__ = (UniqueConstraint("user_id", "kind", "number"),)
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    kind = Column(String(16), nullable=False)
    number = Column(Integer, nullable=False, default=1)
    finished = Column(Boolean, nullable=False, default=False)


class StudyProgress(Base):
    __tablename__ = "study_progress"
    __table_args__ = (UniqueConstraint("round_id", "item_id"),)
    id = Column(Integer, primary_key=True)
    round_id = Column(Integer, ForeignKey("study_rounds.id"), nullable=False, index=True)
    item_id = Column(Integer, ForeignKey("study_items.id"), nullable=False)
    done = Column(Boolean, nullable=False, default=False)
    weak = Column(Boolean, nullable=False, default=False)
    included = Column(Boolean, nullable=False, default=True)


class StudyDay(Base):
    __tablename__ = "study_days"
    __table_args__ = (UniqueConstraint("user_id", "date"),)
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    date = Column(String(10), nullable=False)
    # Snapshot includes progress row IDs; bank edits never rewrite old tasks.
    tasks_json = Column(Text, nullable=False, default="[]")
