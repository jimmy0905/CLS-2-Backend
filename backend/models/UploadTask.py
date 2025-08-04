from models.db_config import Base
from sqlalchemy import Column, Integer, String, DateTime, CHAR
import uuid
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func



class UploadTask(Base):
    __tablename__ = "upload_tasks"

    id = Column(CHAR(36), default=lambda: str(uuid.uuid4()), primary_key=True)
    file_name = Column(String)
    file_path = Column(String)
    status = Column(String)
    total_rows = Column(Integer)
    processed_rows = Column(Integer)
    created_at = Column(DateTime(timezone=True), default=func.now())
    updated_at = Column(DateTime(timezone=True), default=func.now())

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
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "errors": [error.to_dict() for error in self.errors],
        }
