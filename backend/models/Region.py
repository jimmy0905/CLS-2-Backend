from sqlalchemy import Column, Integer, String, Index
from sqlalchemy.orm import relationship
from models.db_config import Base


class Region(Base):
    __tablename__ = "regions"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), unique=True)

    # Relationships
    stores = relationship("Store", back_populates="region")
    surveys = relationship(
        "Survey", secondary="stores", back_populates="region", viewonly=True
    )

    # Indexes for filtered columns
    __table_args__ = (Index("idx_region_name", name),)

    def to_dict(self):
        return {"id": self.id, "name": self.name}
