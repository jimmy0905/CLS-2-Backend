from models.db_config import Base
from sqlalchemy import Column, Integer, String, Index
from sqlalchemy.orm import relationship


class Department(Base):
    __tablename__ = "departments"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), unique=True)

    # Relationships
    surveys = relationship("Survey", back_populates="department")

    # Indexes for filtered columns
    __table_args__ = (Index("idx_department_name", name),)

    def to_dict(self):
        return {"id": self.id, "name": self.name}
