from utils.database import Base
from sqlalchemy import Column, DateTime, Integer, ForeignKey, Text, JSON, CHAR
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func


class GeneratedEmail(Base):
    __tablename__ = "generated_emails"

    id = Column(Integer, primary_key=True)
    user_id = Column(CHAR(36), ForeignKey("users.id"))
    input_data = Column(JSON)
    subject_line = Column(Text)
    email_body = Column(Text)
    created_at = Column(DateTime(timezone=True), default=func.now())
    updated_at = Column(DateTime(timezone=True), default=func.now())

    # Relationships
    user = relationship("User", back_populates="generated_emails")
