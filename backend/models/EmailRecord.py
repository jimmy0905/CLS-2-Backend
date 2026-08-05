from utils.database import Base
from sqlalchemy import Column, Integer, ForeignKey, Text, JSON, DateTime, CHAR
from sqlalchemy.orm import relationship
from utils.utc import utc_now


class EmailRecord(Base):
    __tablename__ = "email_records"

    id = Column(Integer, primary_key=True)
    user_id = Column(CHAR(36), ForeignKey("users.id"))
    subject_line = Column(Text)
    email_body = Column(Text)
    to = Column(JSON)
    cc = Column(JSON)
    created_at = Column(DateTime(timezone=True), default=utc_now)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    # Relationships
    user = relationship("User", back_populates="email_records")
