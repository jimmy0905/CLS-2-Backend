import uuid

from sqlalchemy import CHAR, Column, DateTime, ForeignKey, Index, Integer, JSON, String, Text
from sqlalchemy.orm import relationship

from infrastructure.database.base import Base
from core.time import utc_isoformat, utc_now


class AnalyticsQueryLog(Base):
    """Governance and operational record for every semantic query."""

    __tablename__ = "analytics_query_logs"

    id = Column(CHAR(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    requested_by_id = Column(CHAR(36), ForeignKey("users.id"), nullable=True)
    model_version_id = Column(
        Integer, ForeignKey("analytics_model_versions.id"), nullable=True
    )
    semantic_view = Column(String(32), nullable=False)
    request = Column(JSON, nullable=False, default=dict)
    cube_query = Column(JSON, nullable=True)
    status = Column(String(16), nullable=False, default="pending")
    row_count = Column(Integer, nullable=True)
    duration_ms = Column(Integer, nullable=True)
    error_message = Column(Text, nullable=True)
    freshness_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    requested_by = relationship("User")
    model_version = relationship("AnalyticsModelVersion")

    __table_args__ = (
        Index("idx_analytics_query_logs_created_at", created_at),
        Index("idx_analytics_query_logs_status_created", status, created_at),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "requested_by_id": self.requested_by_id,
            "model_version_id": self.model_version_id,
            "semantic_view": self.semantic_view,
            "request": self.request or {},
            "status": self.status,
            "row_count": self.row_count,
            "duration_ms": self.duration_ms,
            "error_message": self.error_message,
            "freshness_at": utc_isoformat(self.freshness_at),
            "created_at": utc_isoformat(self.created_at),
            "completed_at": utc_isoformat(self.completed_at),
        }
