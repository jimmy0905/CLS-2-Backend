from utils.database import Base
from sqlalchemy import Column, Integer, String, ForeignKey, Index, Boolean
from sqlalchemy.orm import relationship

class Store(Base):
    __tablename__ = "stores"

    id = Column(Integer, primary_key=True)
    name = Column(String(100))
    hierarchy_level_1_id = Column(Integer, ForeignKey("hierarchies.id"), nullable=True)
    hierarchy_level_2_id = Column(Integer, ForeignKey("hierarchies.id"), nullable=True)
    hierarchy_level_3_id = Column(Integer, ForeignKey("hierarchies.id"), nullable=True)
    hierarchy_level_4_id = Column(Integer, ForeignKey("hierarchies.id"), nullable=True)
    hierarchy_level_5_id = Column(Integer, ForeignKey("hierarchies.id"), nullable=True)
    is_active = Column(Boolean, default=True)

    # Relationships
    hierarchy_level_1 = relationship("Hierarchy", foreign_keys=[hierarchy_level_1_id], back_populates="stores_level_1")
    hierarchy_level_2 = relationship("Hierarchy", foreign_keys=[hierarchy_level_2_id], back_populates="stores_level_2")
    hierarchy_level_3 = relationship("Hierarchy", foreign_keys=[hierarchy_level_3_id], back_populates="stores_level_3")
    hierarchy_level_4 = relationship("Hierarchy", foreign_keys=[hierarchy_level_4_id], back_populates="stores_level_4")
    hierarchy_level_5 = relationship("Hierarchy", foreign_keys=[hierarchy_level_5_id], back_populates="stores_level_5")
    surveys = relationship("Survey", back_populates="store")

    # Indexes for filtered columns
    __table_args__ = (Index("idx_store_name", name),)

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "hierarchy_level_1": self.hierarchy_level_1.to_dict() if self.hierarchy_level_1 else None,
            "hierarchy_level_2": self.hierarchy_level_2.to_dict() if self.hierarchy_level_2 else None,
            "hierarchy_level_3": self.hierarchy_level_3.to_dict() if self.hierarchy_level_3 else None,
            "hierarchy_level_4": self.hierarchy_level_4.to_dict() if self.hierarchy_level_4 else None,
            "hierarchy_level_5": self.hierarchy_level_5.to_dict() if self.hierarchy_level_5 else None,
            "is_active": self.is_active,
        }
