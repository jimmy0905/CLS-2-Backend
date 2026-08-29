from infrastructure.database.base import Base
from sqlalchemy import Column, String, Integer, Index
from sqlalchemy.orm import relationship


class Topic(Base):
    __tablename__ = "topics"

    id = Column(Integer, primary_key=True)
    topic = Column(String(200), unique=True)

    # Index for the topic column
    __table_args__ = (Index("idx_topic_name", topic),)

    # Relationships
    survey_topics = relationship("SurveyTopics", back_populates="topic")
    surveys = relationship(
        "Survey", secondary="survey_topics", back_populates="topics", viewonly=True
    )

    def to_dict(self):
        return {"id": self.id, "topic": self.topic}
