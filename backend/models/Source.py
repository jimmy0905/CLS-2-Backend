from utils.database import Base
from sqlalchemy import Column, Integer, String, Index


class Source(Base):
    __tablename__ = "sources"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), unique=True)

    # Indexes for filtered columns
    __table_args__ = (Index("idx_source_name", name),)

    def to_dict(self):
        return {"id": self.id, "name": self.name}
