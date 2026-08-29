from infrastructure.database.base import Base
from sqlalchemy import Column, Integer, ForeignKey, Enum    
from sqlalchemy.orm import relationship
from features.feedback.model.sentiment import Sentiment


class SurveyDepartments(Base):
    __tablename__ = "survey_departments"

    id = Column(Integer, primary_key=True)
    survey_id = Column(Integer, ForeignKey("surveys.id"))
    department_id = Column(Integer, ForeignKey("departments.id"))
    sentiment = Column(Enum(Sentiment, name="sentiment_enum"), nullable=False)

    # Relationships
    survey = relationship("Survey", back_populates="survey_departments")
    department = relationship("Department", back_populates="survey_departments")

    def to_dict(self):
        return {
            "id": self.id,
            "department": self.department.to_dict(),
            "sentiment": self.sentiment,
        }
