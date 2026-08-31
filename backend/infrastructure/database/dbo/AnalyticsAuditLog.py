from sqlalchemy import JSON, Column, DateTime, Index, Integer, String

from core.time import utc_isoformat, utc_now
from infrastructure.database.base import Base


class AnalyticsAuditLog(Base):
    __tablename__ = "analytics_audit_logs"
    __table_args__ = (Index("idx_analytics_audit_logs_created_at", "created_at"),)

    id = Column(Integer, primary_key=True)
    actor_subject = Column(String(255), nullable=True)
    actor_label = Column(String(255), nullable=True)
    actor_role = Column(String(16), nullable=True)
    action = Column(String(64), nullable=False, index=True)
    resource_type = Column(String(32), nullable=False)
    resource_id = Column(String(64), nullable=False)
    payload = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "actor_subject": self.actor_subject,
            "actor_label": self.actor_label,
            "actor_role": self.actor_role,
            "action": self.action,
            "resource_type": self.resource_type,
            "resource_id": self.resource_id,
            "payload": self.payload or {},
            "created_at": utc_isoformat(self.created_at),
        }
