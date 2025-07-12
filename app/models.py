from sqlalchemy import (
    Column, Integer, String, DateTime, ForeignKey, UniqueConstraint, func
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class Gym(Base):
    __tablename__ = "gyms"
    id = Column(Integer, primary_key=True)
    state = Column(String(8), index=True)
    name = Column(String(64), unique=True, index=True)

    counts = relationship("LiveCount", back_populates="gym")


class LiveCount(Base):
    __tablename__ = "live_counts"
    id = Column(Integer, primary_key=True)
    gym_id = Column(Integer, ForeignKey("gyms.id"), index=True)
    ts = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    count = Column(Integer)

    gym = relationship("Gym", back_populates="counts")

    __table_args__ = (UniqueConstraint("gym_id", "ts", name="uix_gym_ts"),)