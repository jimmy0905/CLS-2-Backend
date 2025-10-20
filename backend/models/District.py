from sqlalchemy import Column, Integer, String, Index
from utils.database import Base


class District(Base):
    __tablename__ = "districts"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), unique=True)

    # Indexes for filtered columns
    __table_args__ = (Index("idx_district_name", name),)

    def to_dict(self):
        return {"id": self.id, "name": self.name}
