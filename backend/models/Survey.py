from utils.database import Base
from sqlalchemy import (
    Column,
    DateTime,
    Text,
    Integer,
    Boolean,
    Enum,
    Index,
    ForeignKey,
)
import enum
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func


class Sentiment(str, enum.Enum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"


class Survey(Base):
    __tablename__ = "surveys"

    id = Column(Integer, primary_key=True)
    # Foreign keys
    store_id = Column(Integer, ForeignKey("stores.id"), nullable=False)
    channel_id = Column(Integer, ForeignKey("channels.id"), nullable=True)
    delivery_service_id = Column(
        Integer, ForeignKey("delivery_services.id"), nullable=True
    )
    # Columns
    comment = Column(Text)
    sentiment = Column(Enum(Sentiment, name="sentiment_enum"))
    reported_at = Column(DateTime(timezone=True), default=func.now(), nullable=False)
    created_at = Column(DateTime(timezone=True), default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True), default=func.now(), onupdate=func.now(), nullable=False
    )
    is_deleted = Column(Boolean, default=False)

    # Relationships
    store = relationship("Store", back_populates="surveys", overlaps="source")
    district = relationship(
        "District", secondary="stores", back_populates="surveys", viewonly=True
    )
    region = relationship(
        "Region", secondary="stores", back_populates="surveys", viewonly=True
    )
    source = relationship(
        "Source",
        secondary="stores",
        back_populates="surveys",
        viewonly=True,
        overlaps="store",
    )
    survey_topics = relationship("SurveyTopics", back_populates="survey")
    topics = relationship(
        "Topic",
        secondary="survey_topics",
        back_populates="surveys",
        viewonly=True,
    )
    survey_keywords = relationship("SurveyKeywords", back_populates="survey")
    keywords = relationship(
        "Keyword", secondary="survey_keywords", back_populates="surveys", viewonly=True
    )
    survey_departments = relationship("SurveyDepartments", back_populates="survey")
    departments = relationship(
        "Department",
        secondary="survey_departments",
        back_populates="surveys",
        viewonly=True,
    )
    channel = relationship("Channel", back_populates="surveys")
    delivery_service = relationship("DeliveryService", back_populates="surveys")
    # Indexes for filtered columns
    __table_args__ = (
        Index("idx_survey_reported_at", reported_at),
        Index("idx_survey_sentiment", sentiment),
    )

    def to_dict(self):
        return {
            "id": self.id,
            # Foreign keys
            "store": (
                {
                    "id": self.store.id,
                    "name": self.store.name,
                    "district": {
                        "id": self.store.district.id,
                        "name": self.store.district.name,
                    },
                    "region": {
                        "id": self.store.region.id,
                        "name": self.store.region.name,
                    },
                    "source": {
                        "id": self.store.source.id,
                        "name": self.store.source.name,
                    },
                }
                if self.store
                else None
            ),
            "channel": self.channel.to_dict() if self.channel else None,
            "delivery_service": (
                self.delivery_service.to_dict() if self.delivery_service else None
            ),
            # Relationships
            "departments": [
                {
                    "department_id": survey_department.department_id,
                    "name": survey_department.department.name,
                    "sentiment": survey_department.sentiment,
                }
                for survey_department in self.survey_departments
            ],
            "topics": [
                {
                    "topic_id": survey_topic.topic_id,
                    "topic": survey_topic.topic.topic,
                    "sentiment": survey_topic.sentiment,
                }
                for survey_topic in self.survey_topics
            ],
            "keywords": [
                {
                    "keyword_id": survey_keyword.keyword_id,
                    "keyword": survey_keyword.keyword.keyword,
                    "sentiment": survey_keyword.sentiment,
                }
                for survey_keyword in self.survey_keywords
            ],
            # Columns
            "comment": self.comment,
            "sentiment": self.sentiment,
            "reported_at": (
                self.reported_at
            ),
            "created_at": (
                self.created_at
            ),
            "updated_at": (
                self.updated_at
            ),
        }

    def to_csv(self):
        return {
            "id": self.id,
            "store_id": self.store.id,
            "store_name": self.store.name,
            "district_name": self.store.district.name,
            "region_name": self.store.region.name,
            "source_name": self.store.source.name,
            "comment": self.comment,
            "sentiment": self.sentiment,
            "reported_at": self.reported_at,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            # department1 (positive), department2 (negative), department3 (neutral)
            "departments": [
                f"{survey_department.department.name} ({survey_department.sentiment})"
                for survey_department in self.survey_departments
            ],
            # topic1 (positive), topic2 (negative), topic3 (neutral)
            "topics": [
                f"{survey_topic.topic.topic} ({survey_topic.sentiment})"
                for survey_topic in self.survey_topics
            ],
            # keyword1 (positive), keyword2 (negative), keyword3 (neutral)
            "keywords": [
                f"{survey_keyword.keyword.keyword} ({survey_keyword.sentiment})"
                for survey_keyword in self.survey_keywords
            ],
            "channel": self.channel.name if self.channel else None,
            "delivery_service": (
                self.delivery_service.name if self.delivery_service else None
            ),
        }
