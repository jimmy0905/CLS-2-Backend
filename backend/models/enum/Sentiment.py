import enum


class Sentiment(str, enum.Enum):
    POSITIVE = "POSITIVE"
    NEGATIVE = "NEGATIVE"
    NEUTRAL = "NEUTRAL"


# DO $$ BEGIN CREATE TYPE topic_sentiment_enum AS ENUM ('POSITIVE', 'NEGATIVE', 'NEUTRAL', 'MIXED'); EXCEPTION WHEN duplicate_object THEN null; END $$;
class TopicSentiment(str, enum.Enum):
    POSITIVE = "POSITIVE"
    NEGATIVE = "NEGATIVE"
    NEUTRAL = "NEUTRAL"
    MIXED = "MIXED"
