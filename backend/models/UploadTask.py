from utils.database import Base
from sqlalchemy import Column, Integer, String, DateTime, CHAR, event
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
    completion_tokens = Column(Integer, default=0)
    prompt_tokens = Column(Integer, default=0)
    total_tokens = Column(Integer, default=0)
    cached_tokens = Column(Integer, default=0)

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
            "completion_tokens": self.completion_tokens,
            "prompt_tokens": self.prompt_tokens,
            "total_tokens": self.total_tokens,
            "cached_tokens": self.cached_tokens,
            "errors": [error.to_dict() for error in self.errors],
        }


# Register the event listener to automatically update updated_at
@event.listens_for(UploadTask, "before_update")
def update_updated_at(mapper, connection, target):
    connection.execute(
        UploadTask.__table__.update()
        .where(UploadTask.id == target.id)
        .values(updated_at=func.now())
    )
