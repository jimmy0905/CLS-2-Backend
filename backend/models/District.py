from sqlalchemy import Column, Integer, String, Index
from sqlalchemy.orm import relationship
from utils.database import Base


class District(Base):
    __tablename__ = "districts"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), unique=True)

    # Relationships
    stores = relationship("Store", back_populates="district")
    surveys = relationship(
        "Survey",
        secondary="stores",
        back_populates="district",
        viewonly=True
    )

    # Indexes for filtered columns
    __table_args__ = (Index("idx_district_name", name),)

    def to_dict(self):
        return {"id": self.id, "name": self.name}
