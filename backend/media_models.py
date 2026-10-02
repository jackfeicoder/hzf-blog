from sqlalchemy import Column, Integer, String

from database import Base


class VideoLink(Base):
    __tablename__ = "video_links"

    id = Column(Integer, primary_key=True)
    title = Column(String(80), nullable=False)
    url = Column(String(2000), nullable=False)
    description = Column(String(300), nullable=False, default="")
    position = Column(Integer, nullable=False, default=0)
