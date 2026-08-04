from utils.database import Base
from sqlalchemy import Column, Integer, ForeignKey, Text, JSON, DateTime, CHAR
from sqlalchemy.orm import relationship
from utils.utc import utc_now


class Action(Base):
    __tablename__ = "actions"

    id = Column(Integer, primary_key=True)
    user_id = Column(CHAR(36), ForeignKey("users.id"))
    summary = Column(Text)
    actions_items = Column(JSON)
    survey_data = Column(JSON)
    created_at = Column(DateTime(timezone=False), default=utc_now)
    updated_at = Column(DateTime(timezone=False), default=utc_now, onupdate=utc_now)

    # Relationships
    user = relationship("User", back_populates="actions")
