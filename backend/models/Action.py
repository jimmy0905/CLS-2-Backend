from models.db_config import Base
from sqlalchemy import Column, Integer, ForeignKey, Text, JSON, DateTime, CHAR
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func


class Action(Base):
    __tablename__ = "actions"

    id = Column(Integer, primary_key=True)
    user_id = Column(CHAR(36), ForeignKey("users.id"))
    summary = Column(Text)
    actions_items = Column(JSON)
    survey_data = Column(JSON)
    created_at = Column(DateTime(timezone=True), default=func.now())
    updated_at = Column(DateTime(timezone=True), default=func.now())

    # Relationships
    user = relationship("User", back_populates="actions")
