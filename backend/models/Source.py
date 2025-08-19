from utils.database import Base
from sqlalchemy import Column, Integer, String, Index
from sqlalchemy.orm import relationship


class Source(Base):
    __tablename__ = "sources"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), unique=True)

    # Relationships
    stores = relationship("Store", back_populates="source", overlaps="surveys")
    surveys = relationship(
        "Survey",
        secondary="stores",
        back_populates="source",
        viewonly=True,
        overlaps="store",
    )

    # Indexes for filtered columns
    __table_args__ = (Index("idx_source_name", name),)

    def to_dict(self):
        return {"id": self.id, "name": self.name}
