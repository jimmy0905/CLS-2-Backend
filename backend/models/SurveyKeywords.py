from models.db_config import Base
from sqlalchemy import Column, Integer, ForeignKey
from sqlalchemy.orm import relationship


class SurveyKeywords(Base):
    __tablename__ = "survey_keywords"

    id = Column(Integer, primary_key=True)
    survey_id = Column(Integer, ForeignKey("surveys.id"))
    keyword_id = Column(Integer, ForeignKey("keywords.id"))

    # Add relationships with proper back_populates
    survey = relationship("Survey", back_populates="survey_keywords")
    keyword = relationship("Keyword", back_populates="survey_keywords")

    def to_dict(self):
        return {
            "id": self.id,
            "survey_id": self.survey_id,
            "keyword_id": self.keyword_id,
        }
