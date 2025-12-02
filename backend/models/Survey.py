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
    Float,
    cast,
    case,
    select,
    text,
)
import enum
import datetime
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from sqlalchemy import event


class DepartmentSentiment(str, enum.Enum):
    POSITIVE = "POSITIVE"
    NEGATIVE = "NEGATIVE"
    NEUTRAL = "NEUTRAL"


# DO $$ BEGIN CREATE TYPE topic_sentiment_enum AS ENUM ('POSITIVE', 'NEGATIVE', 'NEUTRAL', 'MIXED'); EXCEPTION WHEN duplicate_object THEN null; END $$;
class TopicSentiment(str, enum.Enum):
    POSITIVE = "POSITIVE"
    NEGATIVE = "NEGATIVE"
    NEUTRAL = "NEUTRAL"
    MIXED = "MIXED"


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
    sentiment = Column(Enum(DepartmentSentiment, name="sentiment_enum"))
    reported_at = Column(DateTime(timezone=True), default=func.now(), nullable=False)
    created_at = Column(DateTime(timezone=True), default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True), default=func.now(), onupdate=func.now(), nullable=False
    )
    is_deleted = Column(Boolean, default=False)
    topic_sentiment = Column(
        Enum(TopicSentiment, name="topic_sentiment_enum")
    )  # Insert this column in the database, sql commands for PostgreSQL:
    # ALTER TABLE surveys ADD COLUMN IF NOT EXISTS topic_sentiment topic_sentiment_enum;
    topic_sentiment_score = Column(
        Float, default=0.0
    )  # Insert this column in the database, sql commands for PostgreSQL:
    # ALTER TABLE surveys ADD COLUMN IF NOT EXISTS topic_sentiment_score FLOAT DEFAULT 0.0;
    # Relationships
    store = relationship("Store", back_populates="surveys")
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
                    "hierarchy_level_1": (
                        {
                            "id": self.store.hierarchy_level_1.id,
                            "name": self.store.hierarchy_level_1.name,
                            "level": self.store.hierarchy_level_1.level,
                        }
                        if self.store.hierarchy_level_1
                        else None
                    ),
                    "hierarchy_level_2": (
                        {
                            "id": self.store.hierarchy_level_2.id,
                            "name": self.store.hierarchy_level_2.name,
                            "level": self.store.hierarchy_level_2.level,
                        }
                        if self.store.hierarchy_level_2
                        else None
                    ),
                    "hierarchy_level_3": (
                        {
                            "id": self.store.hierarchy_level_3.id,
                            "name": self.store.hierarchy_level_3.name,
                            "level": self.store.hierarchy_level_3.level,
                        }
                        if self.store.hierarchy_level_3
                        else None
                    ),
                    "hierarchy_level_4": (
                        {
                            "id": self.store.hierarchy_level_4.id,
                            "name": self.store.hierarchy_level_4.name,
                            "level": self.store.hierarchy_level_4.level,
                        }
                        if self.store.hierarchy_level_4
                        else None
                    ),
                    "hierarchy_level_5": (
                        {
                            "id": self.store.hierarchy_level_5.id,
                            "name": self.store.hierarchy_level_5.name,
                            "level": self.store.hierarchy_level_5.level,
                        }
                        if self.store.hierarchy_level_5
                        else None
                    ),
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
            "topic_sentiment": self.topic_sentiment,
            "topic_sentiment_score": self.topic_sentiment_score,
            "reported_at": (
                self.reported_at.astimezone(datetime.timezone.utc).isoformat()
                if self.reported_at
                else None
            ),
            "created_at": (
                self.created_at.astimezone(datetime.timezone.utc).isoformat()
                if self.created_at
                else None
            ),
            "updated_at": (
                self.updated_at.astimezone(datetime.timezone.utc).isoformat()
                if self.updated_at
                else None
            ),
            "is_deleted": self.is_deleted,
        }

    def to_csv(self):
        return {
            "id": self.id,
            "store_id": self.store.id,
            "store_name": self.store.name,
            "hierarchy_level_1_name": (
                self.store.hierarchy_level_1.name
                if self.store.hierarchy_level_1
                else None
            ),
            "hierarchy_level_2_name": (
                self.store.hierarchy_level_2.name
                if self.store.hierarchy_level_2
                else None
            ),
            "hierarchy_level_3_name": (
                self.store.hierarchy_level_3.name
                if self.store.hierarchy_level_3
                else None
            ),
            "hierarchy_level_4_name": (
                self.store.hierarchy_level_4.name
                if self.store.hierarchy_level_4
                else None
            ),
            "hierarchy_level_5_name": (
                self.store.hierarchy_level_5.name
                if self.store.hierarchy_level_5
                else None
            ),
            "comment": self.comment,
            "reported_at": self.reported_at,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "topic_sentiment": self.topic_sentiment,
            "topic_sentiment_score": self.topic_sentiment_score,
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


@event.listens_for(Survey, "before_update")
def update_topic_sentiment(mapper, connection, target):
    from models.SurveyTopics import SurveyTopics

    # Query the database to get counts for each sentiment type
    total_count = (
        connection.execute(
            select(func.count(SurveyTopics.id)).where(
                SurveyTopics.survey_id == target.id
            )
        ).scalar()
        or 0
    )

    positive_count = (
        connection.execute(
            select(func.count(SurveyTopics.id)).where(
                SurveyTopics.survey_id == target.id,
                SurveyTopics.sentiment == "positive",
            )
        ).scalar()
        or 0
    )

    negative_count = (
        connection.execute(
            select(func.count(SurveyTopics.id)).where(
                SurveyTopics.survey_id == target.id,
                SurveyTopics.sentiment == "negative",
            )
        ).scalar()
        or 0
    )

    # Calculate sentiment score
    if total_count == 0:
        # If survey has no topics, return 1.0
        topic_sentiment_score = 1.0
        topic_sentiment_value = TopicSentiment.POSITIVE
    elif positive_count == 0 and negative_count == 0:
        # If only neutral topics, return 1.0
        topic_sentiment_score = 1.0
        topic_sentiment_value = TopicSentiment.POSITIVE
    elif positive_count > 0 and negative_count == 0:
        # If only positive and neutral (no negative), return 1.0
        topic_sentiment_score = 1.0
        topic_sentiment_value = TopicSentiment.POSITIVE
    elif positive_count == 0 and negative_count > 0:
        # If only negative and neutral (no positive), return -1.0
        topic_sentiment_score = -1.0
        topic_sentiment_value = TopicSentiment.NEGATIVE
    else:
        # Otherwise, calculate (Positive - Negative) / Total
        topic_sentiment_score = (positive_count - negative_count) / total_count
        # Determine sentiment category based on score and presence of both positive and negative
        if positive_count > 0 and negative_count > 0:
            # If both positive and negative topics exist, it's mixed
            topic_sentiment_value = TopicSentiment.MIXED
        elif topic_sentiment_score > 0:
            topic_sentiment_value = TopicSentiment.POSITIVE
        elif topic_sentiment_score < 0:
            topic_sentiment_value = TopicSentiment.NEGATIVE
        else:
            topic_sentiment_value = TopicSentiment.NEUTRAL

    # Update the survey with calculated values using raw SQL
    # Map enum member to uppercase string to match database enum definition
    sentiment_map = {
        TopicSentiment.POSITIVE: "POSITIVE",
        TopicSentiment.NEGATIVE: "NEGATIVE",
        TopicSentiment.NEUTRAL: "NEUTRAL",
        TopicSentiment.MIXED: "MIXED",
    }

    # Get uppercase enum name for database
    enum_name = sentiment_map[topic_sentiment_value]

    # Update via raw SQL with enum value embedded directly to avoid any parameter conversion
    # This ensures we use uppercase values that match the database enum
    # enum_name is safe to embed as it's always one of the 4 controlled uppercase strings
    connection.execute(
        text(
            f"""
            UPDATE surveys 
            SET topic_sentiment = '{enum_name}'::topic_sentiment_enum,
                topic_sentiment_score = :topic_sentiment_score,
                updated_at = now()
            WHERE id = :survey_id
        """
        ),
        {"topic_sentiment_score": topic_sentiment_score, "survey_id": target.id},
    )

    # Update target object's score attribute
    target.topic_sentiment_score = topic_sentiment_score

    # Prevent SQLAlchemy from trying to update topic_sentiment in its generated UPDATE
    # by expiring the attribute - this tells SQLAlchemy to reload it from DB on next access
    from sqlalchemy.orm import object_session

    session = object_session(target)
    if session:
        # Expire the attribute so SQLAlchemy doesn't try to validate/update it
        # The value we set via raw SQL will be loaded on next access
        session.expire(target, ["topic_sentiment"])
