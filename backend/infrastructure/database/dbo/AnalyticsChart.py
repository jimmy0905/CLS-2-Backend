from sqlalchemy import (
    CHAR,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from infrastructure.database.base import Base
from core.time import utc_isoformat, utc_now


class AnalyticsChart(Base):
    __tablename__ = "analytics_charts"

    id = Column(Integer, primary_key=True)
    slug = Column(String(64), nullable=True)
    title = Column(String(160), nullable=False)
    description = Column(Text, nullable=True)
    chart_type = Column(String(16), nullable=False)
    semantic_view = Column(String(32), nullable=True)
    definition = Column(JSON, nullable=False, default=dict)
    visibility = Column(String(16), nullable=False, default="viewer")
    status = Column(String(16), nullable=False, default="draft", index=True)
    validation_errors = Column(JSON, nullable=False, default=list)
    created_by_id = Column(CHAR(36), ForeignKey("users.id"), nullable=False)
    published_model_version_id = Column(
        Integer, ForeignKey("analytics_model_versions.id"), nullable=True
    )
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = Column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )
    validated_at = Column(DateTime(timezone=True), nullable=True)
    published_at = Column(DateTime(timezone=True), nullable=True)
    archived_at = Column(DateTime(timezone=True), nullable=True)

    created_by = relationship("User")
    published_model_version = relationship("AnalyticsModelVersion")

    __table_args__ = (
        Index("idx_analytics_charts_status_updated", status, updated_at),
        Index("uq_analytics_charts_slug", slug, unique=True),
        Index(
            "idx_analytics_charts_visibility_status", visibility, status
        ),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "slug": self.slug,
            "title": self.title,
            "description": self.description,
            "chart_type": self.chart_type,
            "semantic_view": self.semantic_view,
            "definition": self.definition or {},
            "visibility": self.visibility,
            "status": self.status,
            "validation_errors": self.validation_errors or [],
            "published_model_version_id": self.published_model_version_id,
            "validated_at": utc_isoformat(self.validated_at),
            "published_at": utc_isoformat(self.published_at),
            "archived_at": utc_isoformat(self.archived_at),
            "created_at": utc_isoformat(self.created_at),
            "updated_at": utc_isoformat(self.updated_at),
        }
