from utils.database import Base
from sqlalchemy import (
    Column,
    DateTime,
    String,
    Text,
    Integer,
    Boolean,
    Enum,
    Index,
    ForeignKey,
    Float,
)
from datetime import datetime
import enum
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func


class Sentiment(str, enum.Enum):
    POSITIVE = "Positive"
    NEGATIVE = "Negative"
    NEUTRAL = "Neutral"


class Survey(Base):
    __tablename__ = "surveys"

    id = Column(Integer, primary_key=True)
    # Foreign keys
    store_id = Column(Integer, ForeignKey("stores.id"))
    department_id = Column(Integer, ForeignKey("departments.id"))
    # Columns
    comment = Column(Text)
    sentiment = Column(Enum(Sentiment, name="sentiment_enum"))
    cls_score = Column(Float, nullable=True)
    wish_list = Column(Text, nullable=True)
    reported_at = Column(DateTime(timezone=True), default=func.now(), nullable=False)
    created_at = Column(DateTime(timezone=True), default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True), default=func.now(), onupdate=func.now(), nullable=False
    )
    is_deleted = Column(Boolean, default=False)

    # Relationships
    store = relationship("Store", back_populates="surveys", overlaps="source")
    department = relationship("Department", back_populates="surveys")
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
            "department": (
                {
                    "id": self.department.id,
                    "name": self.department.name,
                }
                if self.department
                else None
            ),
            "topics": [topic.topic for topic in self.topics],
            "keywords": [keyword.keyword for keyword in self.keywords],
            # Columns
            "comment": self.comment,
            "sentiment": self.sentiment,
            "cls_score": self.cls_score,
            "wish_list": self.wish_list,
            "reported_at": (
                self.reported_at.isoformat() if self.reported_at is not None else None
            ),
            "created_at": (
                self.created_at.isoformat() if self.created_at is not None else None
            ),
            "updated_at": (
                self.updated_at.isoformat() if self.updated_at is not None else None
            ),
        }
