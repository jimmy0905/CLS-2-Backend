from utils.database import Base
from sqlalchemy import Column, ForeignKey, DateTime, CHAR, Text, Integer, event
from datetime import datetime
import uuid
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func



class UploadTaskError(Base):
    __tablename__ = "upload_task_errors"

    @staticmethod
    def _update_updated_at(mapper, connection, target):
        target.updated_at = datetime.now()

    id = Column(CHAR(36), default=lambda: str(uuid.uuid4()), primary_key=True)
    upload_task_id = Column(CHAR(36), ForeignKey("upload_tasks.id"))
    error_message = Column(Text)
    input_store_id = Column(Integer)
    input_comment = Column(Text)
    input_reported_at = Column(Text)
    created_at = Column(DateTime(timezone=True), default=func.now())
    updated_at = Column(DateTime(timezone=True), default=func.now())

    # Relationships
    upload_task = relationship("UploadTask", back_populates="errors")

    def to_dict(self):
        return {
            "id": self.id,
            "upload_task_id": self.upload_task_id,
            "error_message": self.error_message,
            "input_store_id": self.input_store_id,
            "input_comment": self.input_comment,
            "input_reported_at": self.input_reported_at,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

# Register the event listener to automatically update updated_at
event.listen(UploadTaskError, 'before_update', UploadTaskError._update_updated_at)