from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from core.time import utc_isoformat, utc_now
from infrastructure.database.base import Base


class AnalyticsField(Base):
    """A discovered or promoted survey field in the governed catalog.

    Imported headers are candidates until an administrator assigns a public data
    type, visibility, and published status. ``definition`` is declarative data;
    it must never contain executable SQL.
    """

    __tablename__ = "analytics_fields"

    id = Column(Integer, primary_key=True)
    slug = Column(String(64), nullable=False, unique=True, index=True)
    label = Column(String(120), nullable=False)
    description = Column(Text, nullable=True)
    data_type = Column(String(16), nullable=False)
    source_kind = Column(String(16), nullable=False)
    source_key = Column(String(128), nullable=True)
    semantic_view = Column(String(32), nullable=False, default="survey_responses")
    definition = Column(JSON, nullable=False, default=dict)
    status = Column(String(16), nullable=False, default="draft", index=True)
    is_promoted = Column(Boolean, nullable=False, default=False)
    # Discovery runs as a system process; promoted/admin-created fields retain
    # their actor while automatically discovered candidates may be actor-less.
    created_by_subject = Column(String(255), nullable=True)
    created_by_label = Column(String(255), nullable=True)
    created_by_role = Column(String(16), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = Column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )
    promoted_at = Column(DateTime(timezone=True), nullable=True)

    inferred_data_type = Column(String(16), nullable=True)
    type_conflicts = Column(JSON, nullable=False, default=list)
    sample_values = Column(JSON, nullable=False, default=list)
    visibility = Column(String(16), nullable=False, default="viewer")
    occurrence_count = Column(BigInteger, nullable=False, default=0)
    last_seen_at = Column(DateTime(timezone=True), nullable=True)
    published_at = Column(DateTime(timezone=True), nullable=True)
    archived_at = Column(DateTime(timezone=True), nullable=True)

    values = relationship("AnalyticsFieldValue", back_populates="field")

    __table_args__ = (
        Index("idx_analytics_fields_status_updated", status, updated_at),
        Index("idx_analytics_fields_source", source_kind, source_key),
        Index(
            "idx_analytics_fields_view_visibility_status",
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
            "data_type": self.data_type,
            "inferred_data_type": self.inferred_data_type,
            "source_kind": self.source_kind,
            "source_key": self.source_key,
            "semantic_view": self.semantic_view,
            "definition": self.definition or {},
            "type_conflicts": self.type_conflicts or [],
            "sample_values": self.sample_values or [],
            "visibility": self.visibility,
            "status": self.status,
            "is_promoted": self.is_promoted,
            "created_by_subject": self.created_by_subject,
            "created_by_label": self.created_by_label,
            "created_by_role": self.created_by_role,
            "occurrence_count": self.occurrence_count,
            "last_seen_at": utc_isoformat(self.last_seen_at),
            "promoted_at": utc_isoformat(self.promoted_at),
            "published_at": utc_isoformat(self.published_at),
            "archived_at": utc_isoformat(self.archived_at),
            "created_at": utc_isoformat(self.created_at),
            "updated_at": utc_isoformat(self.updated_at),
        }
