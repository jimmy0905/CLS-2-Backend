from sqlalchemy import Column, Integer, String, Index, ForeignKey
from sqlalchemy.orm import relationship
from utils.database import Base


class Hierarchy(Base):
    __tablename__ = "hierarchies"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), unique=True)
    level = Column(Integer, nullable=False)  # 1-5 representing hierarchy level
    parent_id = Column(Integer, ForeignKey("hierarchies.id"), nullable=True)

    # Relationships
    parent = relationship("Hierarchy", remote_side=[id], backref="children")
    
    # Stores that reference this hierarchy at different levels
    stores_level_1 = relationship("Store", foreign_keys="Store.hierarchy_level_1_id", back_populates="hierarchy_level_1")
    stores_level_2 = relationship("Store", foreign_keys="Store.hierarchy_level_2_id", back_populates="hierarchy_level_2")
    stores_level_3 = relationship("Store", foreign_keys="Store.hierarchy_level_3_id", back_populates="hierarchy_level_3")
    stores_level_4 = relationship("Store", foreign_keys="Store.hierarchy_level_4_id", back_populates="hierarchy_level_4")
    stores_level_5 = relationship("Store", foreign_keys="Store.hierarchy_level_5_id", back_populates="hierarchy_level_5")

    # Indexes for filtered columns
    __table_args__ = (
        Index("idx_hierarchy_name", name),
        Index("idx_hierarchy_level", level),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "level": self.level,
            "parent_id": self.parent_id,
        }

