from utils.database import Base
from sqlalchemy import Column, Integer, ForeignKey, Enum
from sqlalchemy.orm import relationship
import enum


class Sentiment(str, enum.Enum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"


class SurveyKeywords(Base):
    __tablename__ = "survey_keywords"

    id = Column(Integer, primary_key=True)
    survey_id = Column(Integer, ForeignKey("surveys.id"))
    keyword_id = Column(Integer, ForeignKey("keywords.id"))
    sentiment = Column(Enum(Sentiment, name="sentiment_enum"), nullable=False)

    # Add relationships with proper back_populates
    survey = relationship("Survey", back_populates="survey_keywords")
    keyword = relationship("Keyword", back_populates="survey_keywords")

    def to_dict(self):
        return {
            "id": self.id,
            "keyword": self.keyword.to_dict(),
            "sentiment": self.sentiment,
        }
