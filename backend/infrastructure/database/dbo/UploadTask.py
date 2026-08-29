from infrastructure.database.base import Base
from sqlalchemy import Column, Integer, String, DateTime, CHAR, JSON
import uuid
from sqlalchemy.orm import relationship
from core.time import utc_isoformat, utc_now


class UploadTask(Base):
    __tablename__ = "upload_tasks"

    id = Column(CHAR(36), default=lambda: str(uuid.uuid4()), primary_key=True)
    file_name = Column(String)
    file_path = Column(String)
    status = Column(String)
    total_rows = Column(Integer)
    processed_rows = Column(Integer)
    created_at = Column(DateTime(timezone=True), default=utc_now)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)
    analytics_affected_months = Column(JSON, nullable=True)
    analytics_refresh_status = Column(String(32), nullable=True)

    # Relationships
    errors = relationship("UploadTaskError", back_populates="upload_task")

    def to_dict(self):
        return {
            "id": self.id,
            "file_name": self.file_name,
            "file_path": self.file_path,
            "status": self.status,
            "total_rows": self.total_rows,
            "processed_rows": self.processed_rows,
            "created_at": utc_isoformat(self.created_at),
            "updated_at": utc_isoformat(self.updated_at),
            "analytics_affected_months": self.analytics_affected_months,
            "analytics_refresh_status": self.analytics_refresh_status,
            "errors": [error.to_dict() for error in self.errors],
        }
