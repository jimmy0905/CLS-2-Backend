from sqlalchemy import CHAR, Column, DateTime, ForeignKey, Index, Integer, JSON, String
from sqlalchemy.orm import relationship

from infrastructure.database.base import Base
from core.time import utc_isoformat, utc_now


class AnalyticsAuditLog(Base):
    __tablename__ = "analytics_audit_logs"
    __table_args__ = (Index("idx_analytics_audit_logs_created_at", "created_at"),)

    id = Column(Integer, primary_key=True)
    actor_id = Column(CHAR(36), ForeignKey("users.id"), nullable=True)
    action = Column(String(64), nullable=False, index=True)
    resource_type = Column(String(32), nullable=False)
    resource_id = Column(String(64), nullable=False)
    payload = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)

    actor = relationship("User")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "actor_id": self.actor_id,
            "action": self.action,
            "resource_type": self.resource_type,
            "resource_id": self.resource_id,
            "payload": self.payload or {},
            "created_at": utc_isoformat(self.created_at),
        }
