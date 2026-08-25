from sqlalchemy import (
    CHAR,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from utils.database import Base
from utils.utc import utc_isoformat, utc_now


class AnalyticsMetric(Base):
    """A validated aggregate definition exposed to analytics consumers."""

    __tablename__ = "analytics_metrics"

    id = Column(Integer, primary_key=True)
    slug = Column(String(64), nullable=False)
    label = Column(String(120), nullable=False)
    description = Column(Text, nullable=True)
    semantic_view = Column(String(32), nullable=False, default="survey_responses")
    field_id = Column(Integer, ForeignKey("analytics_fields.id"), nullable=True)
    source_member = Column(String(64), nullable=True)
    operation = Column(String(32), nullable=False)
    weight_field_id = Column(Integer, ForeignKey("analytics_fields.id"), nullable=True)
    weight_member = Column(String(64), nullable=True)
    confidence_level = Column(Float, nullable=True)
    definition = Column(JSON, nullable=False, default=dict)
    visibility = Column(String(16), nullable=False, default="viewer")
    status = Column(String(16), nullable=False, default="draft")
    created_by_id = Column(CHAR(36), ForeignKey("users.id"), nullable=False)
    published_model_version_id = Column(
        Integer, ForeignKey("analytics_model_versions.id"), nullable=True
    )
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = Column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )
    published_at = Column(DateTime(timezone=True), nullable=True)
    archived_at = Column(DateTime(timezone=True), nullable=True)

    field = relationship("AnalyticsField", foreign_keys=[field_id])
    weight_field = relationship("AnalyticsField", foreign_keys=[weight_field_id])
    created_by = relationship("User")
    published_model_version = relationship("AnalyticsModelVersion")

    __table_args__ = (
        UniqueConstraint("slug", name="uq_analytics_metrics_slug"),
        Index("ix_analytics_metrics_status", status),
        Index(
            "idx_analytics_metrics_view_visibility_status",
            semantic_view,
            visibility,
            status,
        ),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "slug": self.slug,
            "label": self.label,
            "description": self.description,
            "semantic_view": self.semantic_view,
            "field_id": self.field_id,
            "source_member": self.source_member,
            "operation": self.operation,
            "weight_field_id": self.weight_field_id,
            "weight_member": self.weight_member,
            "confidence_level": self.confidence_level,
            "definition": self.definition or {},
            "visibility": self.visibility,
            "status": self.status,
            "published_model_version_id": self.published_model_version_id,
            "published_at": utc_isoformat(self.published_at),
            "archived_at": utc_isoformat(self.archived_at),
            "created_at": utc_isoformat(self.created_at),
            "updated_at": utc_isoformat(self.updated_at),
        }
