from models.db_config import Base
from sqlalchemy import CHAR, Column, DateTime, String, Boolean
from datetime import datetime
import uuid
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from sqlalchemy import event

class User(Base):
    __tablename__ = "users"

    @staticmethod
    def _update_updated_at(mapper, connection, target):
        target.updated_at = datetime.now()

    id = Column(CHAR(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    username = Column(String(50), unique=True, nullable=False, index=True)
    password = Column(String(255), nullable=False)
    role = Column(String(50), nullable=False, default="user")
    created_at = Column(DateTime(timezone=True), default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True), default=func.now(), onupdate=func.now(), nullable=False
    )
    is_deleted = Column(Boolean, default=False)

    def set_password(self, password):
        self.password = generate_password_hash(password)

    def check_password(self, password: str):
        return check_password_hash(str(self.password), password)

    # Relationships
    actions = relationship("Action", back_populates="user")
    generated_emails = relationship("GeneratedEmail", back_populates="user")
    email_records = relationship("EmailRecord", back_populates="user")

    def to_dict(self):
        return {
            "id": self.id,
            "username": self.username,
            "role": self.role,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "is_deleted": self.is_deleted,
        }

event.listen(User, 'before_update', User._update_updated_at)
