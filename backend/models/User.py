from utils.database import Base
from sqlalchemy import CHAR, Column, DateTime, String, Boolean, UniqueConstraint
import uuid
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy.orm import relationship
from sqlalchemy import event
from utils.utc import utc_isoformat, utc_now


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("oauth_provider", "oauth_id", name="uq_oauth_provider_id"),
    )
    
    id = Column(CHAR(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    username = Column(String(50), unique=True, nullable=False, index=True)
    password = Column(String(255), nullable=True)
    role = Column(String(50), nullable=False, default="user")
    oauth_provider = Column(String(50), nullable=True)
    oauth_id = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=False), default=utc_now, nullable=False)
    updated_at = Column(
        DateTime(timezone=False), default=utc_now, onupdate=utc_now, nullable=False
    )
    is_deleted = Column(Boolean, default=False)

    def set_password(self, password):
        self.password = generate_password_hash(password)

    def check_password(self, password: str):
        return check_password_hash(str(self.password), password)

    def check_oauth_identity(self, id: str, provider: str):
        return self.oauth_id == id and self.oauth_provider == provider

    # Relationships
    actions = relationship("Action", back_populates="user")
    generated_emails = relationship("GeneratedEmail", back_populates="user")
    email_records = relationship("EmailRecord", back_populates="user")

    def to_dict(self):
        return {
            "id": self.id,
            "username": self.username,
            "role": self.role,
            "oauth_provider": self.oauth_provider,
            "created_at": utc_isoformat(self.created_at),
            "updated_at": utc_isoformat(self.updated_at),
            "is_deleted": self.is_deleted,
        }


@event.listens_for(User, "after_update")
def update_updated_at(mapper, connection, target):
    connection.execute(
        User.__table__.update()
        .where(User.id == target.id)
        .values(updated_at=utc_now())
    )
