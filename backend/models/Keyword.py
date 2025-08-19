from utils.database import Base
from sqlalchemy import Column, String, Integer
from sqlalchemy.orm import relationship


class Keyword(Base):
    __tablename__ = "keywords"

    id = Column(Integer, primary_key=True)
    keyword = Column(String(200), unique=True)

    # Relationships
    survey_keywords = relationship("SurveyKeywords", back_populates="keyword")
    surveys = relationship(
        "Survey", secondary="survey_keywords", back_populates="keywords", viewonly=True
    )

    def to_dict(self):
        return {"id": self.id, "keyword": self.keyword}
