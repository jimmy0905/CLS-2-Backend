from infrastructure.database.base import Base
from sqlalchemy import Column, Integer, ForeignKey, DateTime, CHAR
from datetime import datetime
from core.time import utc_now

class LoginRecord(Base):
    __tablename__ = "login_records"
    id = Column[int](Integer, primary_key=True)  
    user_id = Column[str](CHAR(36), ForeignKey("users.id"))
    login_time = Column[datetime](DateTime(timezone=True), default=utc_now, nullable=False)
