from utils.database import Base
from sqlalchemy import Column, Integer, ForeignKey, Index
from sqlalchemy.orm import relationship


class SurveyTopics(Base):
    __tablename__ = "survey_topics"

    id = Column(Integer, primary_key=True)
    survey_id = Column(Integer, ForeignKey("surveys.id"))
    topic_id = Column(Integer, ForeignKey("topics.id"))

    # Add indexes for foreign keys
    __table_args__ = (
        Index("idx_survey_topics_survey_id", survey_id),
        Index("idx_survey_topics_topic_id", topic_id),
    )

    # Relationships
    survey = relationship("Survey", back_populates="survey_topics")
    topic = relationship("Topic", back_populates="survey_topics")

    def to_dict(self):
        return {
            "id": self.id,
            "survey_id": self.survey_id,
            "topic_id": self.topic_id,
        }
