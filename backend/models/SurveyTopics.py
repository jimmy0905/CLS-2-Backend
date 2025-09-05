from utils.database import Base
from sqlalchemy import Column, Integer, ForeignKey, Enum
from sqlalchemy.orm import relationship
import enum

class Sentiment(str, enum.Enum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"

class SurveyTopics(Base):
    __tablename__ = "survey_topics"

    id = Column(Integer, primary_key=True)
    survey_id = Column(Integer, ForeignKey("surveys.id"))
    topic_id = Column(Integer, ForeignKey("topics.id"))
    sentiment = Column(Enum(Sentiment, name="sentiment_enum"), nullable=False)
    
    # Relationships
    survey = relationship("Survey", back_populates="survey_topics")
    topic = relationship("Topic", back_populates="survey_topics")

    def to_dict(self):
        return {
            "id": self.id,
            "topic": self.topic.to_dict(),
            "sentiment": self.sentiment,
        }
