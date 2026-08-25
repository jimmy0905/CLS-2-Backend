import uuid

from sqlalchemy import BigInteger, CHAR, Column, DateTime, ForeignKey, Index, Integer, JSON, String, Text
from sqlalchemy.orm import relationship

from utils.database import Base
from utils.utc import utc_isoformat, utc_now


class AnalyticsExportJob(Base):
    """An audited asynchronous CSV/XLSX export request."""

    __tablename__ = "analytics_export_jobs"

    id = Column(CHAR(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    requested_by_id = Column(CHAR(36), ForeignKey("users.id"), nullable=False)
    query_log_id = Column(
        CHAR(36), ForeignKey("analytics_query_logs.id"), nullable=True
    )
    model_version_id = Column(
        Integer, ForeignKey("analytics_model_versions.id"), nullable=True
    )
    request = Column(JSON, nullable=False, default=dict)
    export_format = Column(String(8), nullable=False)
    status = Column(String(16), nullable=False, default="queued")
    row_count = Column(BigInteger, nullable=True)
    storage_path = Column(String(500), nullable=True)
    content_type = Column(String(120), nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    downloaded_at = Column(DateTime(timezone=True), nullable=True)

    requested_by = relationship("User")
    query_log = relationship("AnalyticsQueryLog")
    model_version = relationship("AnalyticsModelVersion")

    __table_args__ = (
        Index("idx_analytics_export_jobs_status_created", status, created_at),
        Index("idx_analytics_export_jobs_expires_at", expires_at),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "requested_by_id": self.requested_by_id,
            "query_log_id": self.query_log_id,
            "model_version_id": self.model_version_id,
            "export_format": self.export_format,
            "status": self.status,
            "row_count": self.row_count,
            "content_type": self.content_type,
            "error_message": self.error_message,
            "created_at": utc_isoformat(self.created_at),
            "started_at": utc_isoformat(self.started_at),
            "completed_at": utc_isoformat(self.completed_at),
            "expires_at": utc_isoformat(self.expires_at),
            "downloaded_at": utc_isoformat(self.downloaded_at),
        }
