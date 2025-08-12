from models.db_config import Base
from sqlalchemy import Column, Integer, String, ForeignKey, Index, Boolean
from sqlalchemy.orm import relationship

class Store(Base):
    __tablename__ = "stores"

    id = Column(Integer, primary_key=True)
    name = Column(String(100))
    district_id = Column(Integer, ForeignKey("districts.id"))
    source_id = Column(Integer, ForeignKey("sources.id"))
    region_id = Column(Integer, ForeignKey("regions.id"))
    is_active = Column(Boolean, default=True)

    # Relationships
    district = relationship("District", back_populates="stores")
    source = relationship("Source", back_populates="stores", overlaps="surveys")
    surveys = relationship("Survey", back_populates="store", overlaps="source")
    region = relationship("Region", back_populates="stores")

    # Indexes for filtered columns
    __table_args__ = (Index("idx_store_name", name),)

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "district": self.district.to_dict(),
            "source": self.source.to_dict(),
            "region": self.region.to_dict(),
            "is_active": self.is_active,
        }
