from sqlalchemy import Column, Date, DateTime, Float, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import relationship

from utils.database import Base
from utils.utc import utc_now


class AnalyticsFieldValue(Base):
    """Deprecated EAV cache retained only for migration compatibility.

    New semantic queries extract promoted fields from ``raw_row_data`` and must
    not write to this table. It remains mapped so existing installations and
    downgrades keep a faithful schema.
    """

    __tablename__ = "analytics_field_values"
    __deprecated__ = True

    id = Column(Integer, primary_key=True)
    field_id = Column(
        Integer,
        ForeignKey("analytics_fields.id", ondelete="CASCADE"),
        nullable=False,
    )
    survey_id = Column(
        Integer, ForeignKey("surveys.id", ondelete="CASCADE"), nullable=False
    )
    value_text = Column(String(500), nullable=True)
    value_number = Column(Float, nullable=True)
    value_date = Column(Date, nullable=True)
    refreshed_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)

    field = relationship("AnalyticsField", back_populates="values")

    __table_args__ = (
        UniqueConstraint("field_id", "survey_id", name="uq_analytics_field_value"),
        Index("idx_analytics_field_values_text", field_id, value_text),
        Index("idx_analytics_field_values_number", field_id, value_number),
        Index("idx_analytics_field_values_date", field_id, value_date),
    )
