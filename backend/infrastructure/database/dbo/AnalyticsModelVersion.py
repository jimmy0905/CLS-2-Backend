from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Index,
    Integer,
    Sequence,
    String,
    UniqueConstraint,
    text,
)

from core.time import utc_isoformat, utc_now
from infrastructure.database.base import Base

analytics_catalog_version_sequence = Sequence("analytics_catalog_version_seq")


class AnalyticsModelVersion(Base):
    """An immutable snapshot of a validated local semantic catalog."""

    __tablename__ = "analytics_model_versions"

    id = Column(Integer, primary_key=True)
    catalog_version = Column(
        BigInteger,
        analytics_catalog_version_sequence,
        nullable=False,
        server_default=analytics_catalog_version_sequence.next_value(),
    )
    status = Column(String(16), nullable=False, default="draft")
    definition_hash = Column(String(64), nullable=False)
    catalog_snapshot = Column(JSON, nullable=False, default=dict)
    validation_errors = Column(JSON, nullable=False, default=list)
    is_active = Column(Boolean, nullable=False, default=False)
    created_by_subject = Column(String(255), nullable=False)
    created_by_label = Column(String(255), nullable=False)
    created_by_role = Column(String(16), nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    published_at = Column(DateTime(timezone=True), nullable=True)
    activated_at = Column(DateTime(timezone=True), nullable=True)
    archived_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "catalog_version", name="uq_analytics_model_versions_catalog_version"
        ),
        Index("ix_analytics_model_versions_status", status),
        Index(
            "uq_analytics_model_versions_one_active",
            is_active,
            unique=True,
            postgresql_where=text("is_active"),
        ),
    )

    def to_dict(self, include_snapshot: bool = False) -> dict:
        result = {
            "id": self.id,
            "catalog_version": self.catalog_version,
            "status": self.status,
            "definition_hash": self.definition_hash,
            "validation_errors": self.validation_errors or [],
            "is_active": self.is_active,
            "created_by_subject": self.created_by_subject,
            "created_by_label": self.created_by_label,
            "created_by_role": self.created_by_role,
            "created_at": utc_isoformat(self.created_at),
            "published_at": utc_isoformat(self.published_at),
            "activated_at": utc_isoformat(self.activated_at),
            "archived_at": utc_isoformat(self.archived_at),
        }
        if include_snapshot:
            result["catalog_snapshot"] = self.catalog_snapshot or {}
        return result
