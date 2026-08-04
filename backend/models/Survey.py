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
    JSON,
)
import enum
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from sqlalchemy import event
from models.enum.Sentiment import Sentiment, TopicSentiment
from utils.utc import utc_isoformat, utc_now


class Survey(Base):
    __tablename__ = "surveys"

    id = Column(Integer, primary_key=True)
    # Source ID
    survey_id=Column(Text, nullable=False)
    respondent_id=Column(Text, nullable=False)
    # Foreign keys
    store_key = Column(Integer, ForeignKey("stores.store_key"), nullable=False)
    channel_id = Column(Integer, ForeignKey("channels.id"), nullable=True)
    delivery_service_id = Column(
        Integer, ForeignKey("delivery_services.id"), nullable=True
    )
    # Columns
    comment = Column(Text)
    sentiment = Column(Enum(Sentiment, name="sentiment_enum"))
    reported_at = Column(DateTime(timezone=False), default=utc_now, nullable=False)
    created_at = Column(DateTime(timezone=False), default=utc_now, nullable=False)
    updated_at = Column(
        DateTime(timezone=False), default=utc_now, onupdate=utc_now, nullable=False
    )
    is_deleted = Column(Boolean, default=False)
    topic_sentiment = Column(Enum(TopicSentiment, name="topic_sentiment_enum"))
    # Insert this column in the database, sql commands for PostgreSQL:
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
    raw_row_data = Column(JSON, nullable=True)
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
                    "store_key": self.store.store_key,
                    "store_name_english": self.store.store_name_english,
                    "store_name_local": self.store.store_name_local,
                    "bu_key": self.store.bu_key,
                    "area_manager": self.store.area_manager,
                    "store_format": self.store.store_format,
                    "store_type": self.store.store_type,
                    "operations_controller": self.store.operations_controller,
                    "regional_manager": self.store.regional_manager,
                    "px": self.store.px,
                    "csr": self.store.csr,
                    "dr": self.store.dr,
                    "mag_type": self.store.mag_type,
                    "cf_grouping": self.store.cf_grouping,
                    "store_brand": self.store.store_brand,
                    "competitor": self.store.competitor,
                    "region": self.store.region,
                    "area": self.store.area,
                    "province": self.store.province,
                    "territory": self.store.territory,
                    "toh": self.store.toh,
                    "district": self.store.district,
                    "city": self.store.city,
                    "operations_manager": self.store.operations_manager,
                    "district_manager": self.store.district_manager,
                    "sic": self.store.sic,
                    "soc": self.store.soc,
                    "tech_life_type": self.store.tech_life_type,
                    "operation_manager_tl": self.store.operation_manager_tl,
                    "region_manager_tl": self.store.region_manager_tl,
                    "relocation": self.store.relocation,
                    "latitude": self.store.latitude,
                    "longitude": self.store.longitude,
                    "store_open_date": self.store.store_open_date.isoformat() if self.store.store_open_date else None,
                    "store_close_date": self.store.store_close_date.isoformat() if self.store.store_close_date else None,
                    "is_closed": self.store.is_closed,
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
            "reported_at": utc_isoformat(self.reported_at),
            "created_at": utc_isoformat(self.created_at),
            "updated_at": utc_isoformat(self.updated_at),
            "is_deleted": self.is_deleted,
        }

    @staticmethod
    def _format_sentiment_value(sentiment):
        """Helper function to format sentiment enum values for CSV export."""
        if not sentiment:
            return "N/A"
        if hasattr(sentiment, "value"):
            return sentiment.value.title()  # "POSITIVE" -> "Positive"
        # Fallback: extract value from string representation like "Sentiment.NEUTRAL"
        sentiment_str = str(sentiment)
        if "." in sentiment_str:
            return sentiment_str.split(".")[-1].title()
        return sentiment_str.title()

    def to_csv(self):
        return {
            "id": self.id,
            "survey_id": self.survey_id,
            "respondent_id": self.respondent_id,
            "store_key": self.store.store_key,
            "store_id": self.store.store_key,  # Alias for store_key
            "store_name": self.store.store_name_english if self.store.store_name_english else self.store.store_name_local,  # Fallback to local name if English name is missing
            "store_english_name": self.store.store_name_english,
            "store_local_name": self.store.store_name_local,
            "store_name_english": self.store.store_name_english,
            "store_name_local": self.store.store_name_local,
            "bu_key": self.store.bu_key,
            "area_manager": self.store.area_manager,
            "store_format": self.store.store_format,
            "store_type": self.store.store_type,
            "operations_controller": self.store.operations_controller,
            "regional_manager": self.store.regional_manager,
            "px": self.store.px,
            "csr": self.store.csr,
            "dr": self.store.dr,
            "mag_type": self.store.mag_type,
            "cf_grouping": self.store.cf_grouping,
            "store_brand": self.store.store_brand,
            "competitor": self.store.competitor,
            "region": self.store.region,
            "area": self.store.area,
            "province": self.store.province,
            "territory": self.store.territory,
            "toh": self.store.toh,
            "district": self.store.district,
            "city": self.store.city,
            "operations_manager": self.store.operations_manager,
            "district_manager": self.store.district_manager,
            "sic": self.store.sic,
            "soc": self.store.soc,
            "tech_life_type": self.store.tech_life_type,
            "operation_manager_tl": self.store.operation_manager_tl,
            "region_manager_tl": self.store.region_manager_tl,
            "relocation": self.store.relocation,
            "latitude": self.store.latitude,
            "longitude": self.store.longitude,
            "store_open_date": self.store.store_open_date,
            "store_close_date": self.store.store_close_date,
            "is_closed": self.store.is_closed,
            "department_id": ", ".join([str(survey_department.department_id) for survey_department in self.survey_departments]) if self.survey_departments else None,
            "department_name": ", ".join([survey_department.department.name for survey_department in self.survey_departments]) if self.survey_departments else None,
            "channel_id": self.channel_id if self.channel else None,
            "channel_name": self.channel.name if self.channel else None,
            "departments": [
                f"{survey_department.department.name} ({self._format_sentiment_value(survey_department.sentiment)})"
                for survey_department in self.survey_departments
            ],
            "topics": [
                f"{survey_topic.topic.topic} ({self._format_sentiment_value(survey_topic.sentiment)})"
                for survey_topic in self.survey_topics
            ],
            "keywords": [
                f"{survey_keyword.keyword.keyword} ({self._format_sentiment_value(survey_keyword.sentiment)})"
                for survey_keyword in self.survey_keywords
            ],
            "comment": self.comment,
            "channel": self.channel.name if self.channel else None,
            "delivery_service": (
                self.delivery_service.name if self.delivery_service else None
            ),
            "sentiment": self._format_sentiment_value(
                self.topic_sentiment
            ),  # use topic_sentiment instead of sentiment
            "sentiment_score": self.topic_sentiment_score,
            "reported_at": self.reported_at,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@event.listens_for(Survey, "before_update")
def update_topic_sentiment(mapper, connection, target):
    """Triggered when the survey itself is updated (not on insert)."""
    _recalculate_survey_sentiment(connection, target.id, target)


def _recalculate_survey_sentiment(connection, survey_id, target):
    """Helper function to calculate and update survey sentiment based on its topics."""
    from models.SurveyTopics import SurveyTopics
    from models.enum.Sentiment import Sentiment, TopicSentiment

    # Query the database to get counts for each sentiment type
    total_count = (
        connection.execute(
            select(func.count(SurveyTopics.id)).where(
                SurveyTopics.survey_id == survey_id
            )
        ).scalar()
        or 0
    )

    if total_count == 0:
        # If survey has no topics, we don't need to update or can set to default
        return

    positive_count = (
        connection.execute(
            select(func.count(SurveyTopics.id)).where(
                SurveyTopics.survey_id == survey_id,
                SurveyTopics.sentiment == Sentiment.POSITIVE,
            )
        ).scalar()
        or 0
    )

    negative_count = (
        connection.execute(
            select(func.count(SurveyTopics.id)).where(
                SurveyTopics.survey_id == survey_id,
                SurveyTopics.sentiment == Sentiment.NEGATIVE,
            )
        ).scalar()
        or 0
    )

    neutral_count = (
        connection.execute(
            select(func.count(SurveyTopics.id)).where(
                SurveyTopics.survey_id == survey_id,
                SurveyTopics.sentiment == Sentiment.NEUTRAL,
            )
        ).scalar()
        or 0
    )

    # Calculate sentiment score
    if total_count == 0:
        topic_sentiment_score = 0.0
        topic_sentiment_value = TopicSentiment.NEUTRAL
    elif positive_count == total_count:
        topic_sentiment_score = 1.0
        topic_sentiment_value = TopicSentiment.POSITIVE
    elif negative_count == total_count:
        topic_sentiment_score = -1.0
        topic_sentiment_value = TopicSentiment.NEGATIVE
    elif neutral_count == total_count:
        topic_sentiment_score = 0.0
        topic_sentiment_value = TopicSentiment.NEUTRAL
    elif positive_count > 0 and neutral_count > 0 and negative_count == 0:
        topic_sentiment_score = 1.0
        topic_sentiment_value = TopicSentiment.POSITIVE
    elif negative_count > 0 and neutral_count > 0 and positive_count == 0:
        topic_sentiment_score = -1.0
        topic_sentiment_value = TopicSentiment.NEGATIVE
    else:
        topic_sentiment_score = (positive_count - negative_count) / total_count
        topic_sentiment_value = TopicSentiment.MIXED

    sentiment_map = {
        TopicSentiment.POSITIVE: "POSITIVE",
        TopicSentiment.NEGATIVE: "NEGATIVE",
        TopicSentiment.NEUTRAL: "NEUTRAL",
        TopicSentiment.MIXED: "MIXED",
    }

    enum_name = sentiment_map[topic_sentiment_value]

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
        {"topic_sentiment_score": topic_sentiment_score, "survey_id": survey_id},
    )

    # Use set_committed_value to reflect the raw SQL changes back onto the ORM instance
    # without creating dirty-tracking history (avoids SAWarning in flush event handlers)
    from sqlalchemy.orm.attributes import set_committed_value

    set_committed_value(target, "topic_sentiment_score", topic_sentiment_score)
    set_committed_value(target, "topic_sentiment", topic_sentiment_value)
