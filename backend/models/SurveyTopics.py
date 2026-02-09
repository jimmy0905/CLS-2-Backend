from utils.database import Base
from sqlalchemy import Column, Integer, ForeignKey, Enum
from sqlalchemy.orm import relationship
from models.enum.Sentiment import Sentiment


class SurveyTopics(Base):
    __tablename__ = "survey_topics"

    id = Column (Integer, primary_key=True)
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


from sqlalchemy import event


@event.listens_for(SurveyTopics, "after_insert")
@event.listens_for(SurveyTopics, "after_update")
@event.listens_for(SurveyTopics, "after_delete")
def update_survey_sentiment_on_topic_change(mapper, connection, target):
    """Triggered when a survey topic is created, updated, or deleted."""
    from models.Survey import _recalculate_survey_sentiment
    
    # Access the survey through the relationship
    survey = target.survey
    if survey:
        _recalculate_survey_sentiment(connection, target.survey_id, survey)
