from utils.database import Base
from sqlalchemy import Column, Integer, ForeignKey, String, DateTime, CHAR 
from datetime import datetime
from sqlalchemy.sql import func

class LoginRecord(Base):
    __tablename__ = "login_records"
    id = Column[int](Integer, primary_key=True)  
    user_id = Column[str](CHAR(36), ForeignKey("users.id"))
    login_time = Column[datetime](DateTime(timezone=True), default=func.now(), nullable=False)