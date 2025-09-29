from utils.database import Base
from sqlalchemy import Column, Integer, Text
from sqlalchemy.orm import relationship


class DeliveryService(Base):
    __tablename__ = "delivery_services"

    id = Column(Integer, primary_key=True)
    name = Column(Text, unique=True)

    # Relationships
    surveys = relationship("Survey", back_populates="delivery_service")

    def to_dict(self):
        return {"id": self.id, "name": self.name}
