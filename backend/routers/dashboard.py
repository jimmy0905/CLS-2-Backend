from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, or_, distinct, case, and_, cast, Float, extract
from models.Survey import Survey
from models.Topic import Topic
from models.Keyword import Keyword
from models.SurveyKeywords import SurveyKeywords
from models.SurveyDepartments import SurveyDepartments
from models.Store import Store
from models.Department import Department
from models.Hierarchy import Hierarchy
from models.SurveyTopics import SurveyTopics
from models.Channel import Channel
from models.DeliveryService import DeliveryService
from models.enum.Sentiment import Sentiment, TopicSentiment
from utils.database import get_db
from pydantic import BaseModel
from utils.conditionFilter import (
    build_optimized_query,
    build_Survey_sentiment_aggregation_query,
    build_SurveyKeywords_sentiment_aggregation_query,
    build_SurveyDepartments_sentiment_aggregation_query,
    build_SurveyTopics_sentiment_aggregation_query,
    FilterRequest,
    get_filter_params,
)
from typing import List, Optional
from utils.security import get_current_user
from datetime import timezone

router = APIRouter(
    prefix="/dashboard",
    tags=["dashboard"],
    dependencies=[Depends(get_db), Depends(get_current_user)],
)


class DepartmentDistributionResponse(BaseModel):
    department: str
    neutral_count: int
    positive_count: int
    negative_count: int
    total_count_for_option: int


@router.get("/department-distribution")
async def get_department_distribution(
    filter_params: FilterRequest = Depends(get_filter_params),
    db: Session = Depends(get_db),
) -> List[DepartmentDistributionResponse]:
    filter_dict = filter_params.model_dump()

    # Single query to get sentiment counts with department filter
    sentiment_query, sentiment_joins, _ = build_optimized_query(db, filter_dict)

    # Add department join if not already present
    if "department" not in sentiment_joins:
        sentiment_query = sentiment_query.join(
            SurveyDepartments, Survey.id == SurveyDepartments.survey_id
        )
        sentiment_query = sentiment_query.join(
            Department, SurveyDepartments.department_id == Department.id
        )

    sentiment_results = build_SurveyDepartments_sentiment_aggregation_query(
        sentiment_query, Department.name.label("department")
    ).all()

    # Total count query: Apply ALL filters EXCEPT department filters, but group by department
    total_query, total_joins, _ = build_optimized_query(
        db, filter_dict, exclude_filters=["department_ids", "department_names"]
    )

    # Always add department join for total counts since we need to group by department
    if "department" not in total_joins:
        total_query = total_query.join(
            SurveyDepartments, Survey.id == SurveyDepartments.survey_id
        )
        total_query = total_query.join(
            Department, SurveyDepartments.department_id == Department.id
        )

    total_results = (
        total_query.with_entities(
            Department.name.label("department"),
            func.count(func.distinct(SurveyDepartments.id)).label("total_count"),
        )
        .group_by(Department.id, Department.name)
        .all()
    )

    # Combine results
    sentiment_dict = {row.department: row for row in sentiment_results}
    total_dict = {row.department: row.total_count for row in total_results}

    department_distribution = []
    for dept_name in set(list(sentiment_dict.keys()) + list(total_dict.keys())):
        sentiment_row = sentiment_dict.get(dept_name)
        total_count = total_dict.get(dept_name, 0)

        department_distribution.append(
            DepartmentDistributionResponse(
                department=dept_name,
                neutral_count=sentiment_row.neutral_count if sentiment_row else 0,
                positive_count=sentiment_row.positive_count if sentiment_row else 0,
                negative_count=sentiment_row.negative_count if sentiment_row else 0,
                total_count_for_option=total_count,
            )
        )

    return department_distribution


class KeywordAnalysisResponse(BaseModel):
    keyword: str
    neutral_count: int
    positive_count: int
    negative_count: int


@router.get("/keyword-analysis")
async def get_keyword_analysis(
    filter_params: FilterRequest = Depends(get_filter_params),
    k: int = Query(
        default=10,
        description="The number of keywords to return",
    ),
    db: Session = Depends(get_db),
) -> List[KeywordAnalysisResponse]:
    filter_dict = filter_params.model_dump()

    # Build base query with filters
    base_query, joined_tables, _ = build_optimized_query(db, filter_dict)

    # Check if keyword joins are already present, if not add them
    if "keyword" not in joined_tables:
        base_query = base_query.join(
            SurveyKeywords, Survey.id == SurveyKeywords.survey_id
        )
        base_query = base_query.join(Keyword, SurveyKeywords.keyword_id == Keyword.id)

    # Single optimized query for keyword analysis
    keyword_query = build_SurveyKeywords_sentiment_aggregation_query(
        base_query, Keyword.keyword.label("keyword")
    )
    
    # Print the SQL query for debugging
    from sqlalchemy.dialects import postgresql
    print("Keyword Analysis Query:")
    print(keyword_query.statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
    
    keyword_results = keyword_query.all()
    
    # Sort by total count (sum of all sentiment counts) and take top k
    sorted_results = sorted(
        keyword_results,
        key=lambda row: row.neutral_count + row.positive_count + row.negative_count,
        reverse=True
    )[:k]

    return [
        KeywordAnalysisResponse(
            keyword=row.keyword,
            neutral_count=row.neutral_count,
            positive_count=row.positive_count,
            negative_count=row.negative_count,
        )
        for row in sorted_results
    ]


class HierarchyDistributionResponse(BaseModel):
    id: int
    name: str
    level: int
    positive_count: int
    negative_count: int
    neutral_count: int
    mixed_count: int
    sentiment_score: float
    total_count_for_option: int


@router.get("/hierarchy-distribution")
async def get_hierarchy_distribution(
    level: int = Query(..., ge=1, le=5, description="Hierarchy level (1-5)"),
    filter_params: FilterRequest = Depends(get_filter_params),
    db: Session = Depends(get_db),
) -> List[HierarchyDistributionResponse]:
    filter_dict = filter_params.model_dump()

    # Map level to Store hierarchy column
    hierarchy_columns = {
        1: Store.hierarchy_level_1_id,
        2: Store.hierarchy_level_2_id,
        3: Store.hierarchy_level_3_id,
        4: Store.hierarchy_level_4_id,
        5: Store.hierarchy_level_5_id,
    }

    hierarchy_col = hierarchy_columns[level]

    # Single query to get sentiment counts with hierarchy filter
    sentiment_query, sentiment_joins, sentiment_hierarchy_aliases = (
        build_optimized_query(db, filter_dict)
    )

    # Add necessary joins if not already present
    if "store" not in sentiment_joins:
        sentiment_query = sentiment_query.join(Store, Survey.store_id == Store.id)

    # Check if the requested level's hierarchy join exists, if not, create it
    sentiment_hierarchy_alias = sentiment_hierarchy_aliases.get(level)
    if f"hierarchy_level_{level}" not in sentiment_joins:
        from sqlalchemy.orm import aliased

        sentiment_hierarchy_alias = aliased(Hierarchy)
        sentiment_query = sentiment_query.join(
            sentiment_hierarchy_alias, hierarchy_col == sentiment_hierarchy_alias.id
        )

    # Use distinct to avoid counting the same survey multiple times after many-to-many joins
    # Get sentiment counts and score
    sentiment_results = build_SurveyTopics_sentiment_aggregation_query(
        sentiment_query,
        sentiment_hierarchy_alias.id.label("hierarchy_id"),
        sentiment_hierarchy_alias.name.label("hierarchy_name"),
    ).all()

    # Get sentiment scores separately to avoid double counting
    # Create subquery with distinct survey IDs and their hierarchy IDs
    distinct_surveys_subquery = (
        sentiment_query.with_entities(
            func.distinct(Survey.id).label("survey_id"),
            sentiment_hierarchy_alias.id.label("hierarchy_id"),
        )
        .subquery()
    )
    
    # Join back to Survey to get sentiment scores, grouped by hierarchy
    sentiment_score_results = (
        db.query(Survey)
        .join(
            distinct_surveys_subquery,
            Survey.id == distinct_surveys_subquery.c.survey_id,
        )
        .with_entities(
            distinct_surveys_subquery.c.hierarchy_id.label("hierarchy_id"),
            func.avg(Survey.topic_sentiment_score).label("sentiment_score"),
        )
        .group_by(distinct_surveys_subquery.c.hierarchy_id)
        .all()
    )

    # Total count query: Apply ALL filters EXCEPT hierarchy level filters for the requested level, but keep other hierarchy filters
    exclude_filters = [f"hierarchy_level_{level}_ids", f"hierarchy_level_{level}_names"]
    total_query, total_joins, total_hierarchy_aliases = build_optimized_query(
        db, filter_dict, exclude_filters=exclude_filters
    )

    # Always add necessary joins for total counts
    if "store" not in total_joins:
        total_query = total_query.join(Store, Survey.store_id == Store.id)

    # Check if the requested level's hierarchy join exists for total query
    total_hierarchy_alias = total_hierarchy_aliases.get(level)
    if f"hierarchy_level_{level}" not in total_joins:
        from sqlalchemy.orm import aliased

        total_hierarchy_alias = aliased(Hierarchy)
        total_query = total_query.join(
            total_hierarchy_alias, hierarchy_col == total_hierarchy_alias.id
        )

    total_results = (
        total_query.with_entities(
            total_hierarchy_alias.id.label("hierarchy_id"),
            total_hierarchy_alias.name.label("hierarchy_name"),
            func.count(func.distinct(Survey.id)).label("total_count"),
        )
        .group_by(total_hierarchy_alias.id, total_hierarchy_alias.name)
        .all()
    )

    # Combine results
    sentiment_dict = {
        row.hierarchy_id: {
            "positive_count": row.positive_count,
            "negative_count": row.negative_count,
            "neutral_count": row.neutral_count,
            "mixed_count": row.mixed_count,
            "hierarchy_name": row.hierarchy_name,
        }
        for row in sentiment_results
    }
    sentiment_score_dict = {
        row.hierarchy_id: row.sentiment_score for row in sentiment_score_results
    }
    total_dict = {row.hierarchy_id: row.total_count for row in total_results}
    hierarchy_name_dict = {
        row.hierarchy_id: row.hierarchy_name for row in sentiment_results
    }
    # Add hierarchy names from total results if not in sentiment results
    for row in total_results:
        if row.hierarchy_id not in hierarchy_name_dict:
            hierarchy_name_dict[row.hierarchy_id] = row.hierarchy_name

    hierarchy_distribution = []
    for hierarchy_id in set(
        list(sentiment_dict.keys())
        + list(sentiment_score_dict.keys())
        + list(total_dict.keys())
    ):
        sentiment_data = sentiment_dict.get(
            hierarchy_id,
            {
                "positive_count": 0,
                "negative_count": 0,
                "neutral_count": 0,
                "mixed_count": 0,
                "hierarchy_name": "",
            },
        )
        sentiment_score = sentiment_score_dict.get(hierarchy_id, 0.0)
        total_count = total_dict.get(hierarchy_id, 0)
        hierarchy_name = hierarchy_name_dict.get(hierarchy_id, "") or sentiment_data["hierarchy_name"]

        hierarchy_distribution.append(
            HierarchyDistributionResponse(
                id=hierarchy_id,
                name=hierarchy_name,
                level=level,
                positive_count=sentiment_data["positive_count"],
                negative_count=sentiment_data["negative_count"],
                neutral_count=sentiment_data["neutral_count"],
                mixed_count=sentiment_data["mixed_count"],
                sentiment_score=float(sentiment_score or 0.0),
                total_count_for_option=total_count,
            )
        )

    return hierarchy_distribution


class TopicDistributionResponse(BaseModel):
    topic: str
    neutral_count: int
    positive_count: int
    negative_count: int
    total_count_for_option: int


@router.get("/topic-distribution")
async def get_topic_distribution(
    filter_params: FilterRequest = Depends(get_filter_params),
    db: Session = Depends(get_db),
) -> List[TopicDistributionResponse]:
    filter_dict = filter_params.model_dump()

    # Single query to get sentiment counts with topic filter
    sentiment_query, sentiment_joins, _ = build_optimized_query(db, filter_dict)

    # Add topic joins if not already present
    if "topic" not in sentiment_joins:
        sentiment_query = sentiment_query.join(
            SurveyTopics, Survey.id == SurveyTopics.survey_id
        )
        sentiment_query = sentiment_query.join(Topic, SurveyTopics.topic_id == Topic.id)

    sentiment_results = build_SurveyTopics_sentiment_aggregation_query(
        sentiment_query, Topic.topic.label("topic")
    ).all()

    # Total count query: Apply ALL filters EXCEPT topic filters, but group by topic
    total_query, total_joins, _ = build_optimized_query(
        db, filter_dict, exclude_filters=["topics"]
    )

    # Always add topic joins for total counts since we need to group by topic
    if "topic" not in total_joins:
        total_query = total_query.join(
            SurveyTopics, Survey.id == SurveyTopics.survey_id
        )
        total_query = total_query.join(Topic, SurveyTopics.topic_id == Topic.id)

    total_results = (
        total_query.with_entities(
            Topic.topic.label("topic"), func.count(func.distinct(SurveyTopics.id)).label("total_count")
        )
        .group_by(Topic.id, Topic.topic)
        .all()
    )

    # Combine results
    sentiment_dict = {row.topic: row for row in sentiment_results}
    total_dict = {row.topic: row.total_count for row in total_results}

    topic_distribution = []
    for topic_name in set(list(sentiment_dict.keys()) + list(total_dict.keys())):
        sentiment_row = sentiment_dict.get(topic_name)
        total_count = total_dict.get(topic_name, 0)

        topic_distribution.append(
            TopicDistributionResponse(
                topic=topic_name,
                neutral_count=sentiment_row.neutral_count if sentiment_row else 0,
                positive_count=sentiment_row.positive_count if sentiment_row else 0,
                negative_count=sentiment_row.negative_count if sentiment_row else 0,
                total_count_for_option=total_count,
            )
        )

    return topic_distribution


class DailySentimentDistributionResponse(BaseModel):
    year: int
    month: int
    day: int
    positive_count: int
    negative_count: int
    neutral_count: int
    mixed_count: int
    sentiment_score: float


@router.get("/sentiment-distribution")
async def get_sentiment_distribution(
    filter_params: FilterRequest = Depends(get_filter_params),
    db: Session = Depends(get_db),
) -> List[DailySentimentDistributionResponse]:
    filter_dict = filter_params.model_dump()

    # Single query to get sentiment counts and score by date
    base_query, _joined_tables, _ = build_optimized_query(db, filter_dict)

    date_results = base_query.with_entities(
        extract('year', Survey.reported_at).label("year"),
        extract('month', Survey.reported_at).label("month"),
        extract('day', Survey.reported_at).label("day"),
        func.count(func.distinct(case((Survey.topic_sentiment == TopicSentiment.NEUTRAL, Survey.id)))).label(
            "neutral_count"
        ),
        func.count(func.distinct(case((Survey.topic_sentiment == TopicSentiment.POSITIVE, Survey.id)))).label(
            "positive_count"
        ),
        func.count(func.distinct(case((Survey.topic_sentiment == TopicSentiment.NEGATIVE, Survey.id)))).label(
            "negative_count"
        ),
        func.count(func.distinct(case((Survey.topic_sentiment == TopicSentiment.MIXED, Survey.id)))).label(
            "mixed_count"
        ),
        func.avg(Survey.topic_sentiment_score).label("sentiment_score"),
    ).group_by(
        extract('year', Survey.reported_at),
        extract('month', Survey.reported_at),
        extract('day', Survey.reported_at)
    ).all()

    return date_results


class StoreResponse(BaseModel):
    id: int
    name: str
    positive_count: int
    negative_count: int
    neutral_count: int
    mixed_count: int
    sentiment_score: float
    total_count_for_option: int


@router.get("/store-distribution")
async def get_store_distribution(
    filter_params: FilterRequest = Depends(get_filter_params),
    db: Session = Depends(get_db),
) -> List[StoreResponse]:
    filter_dict = filter_params.model_dump()

    # Single query to get sentiment score with store filter
    base_query, _joined_tables, _ = build_optimized_query(db, filter_dict)

    # Add store join if not already present
    if "store" not in _joined_tables:
        base_query = base_query.join(Store, Survey.store_id == Store.id)

    results_grouped_by_store=base_query.with_entities(
        Store.id.label("store_id"),
        Store.name.label("store"),
        func.count(func.distinct(case((Survey.topic_sentiment == TopicSentiment.NEUTRAL, Survey.id)))).label(
            "neutral_count"
        ),
        func.count(func.distinct(case((Survey.topic_sentiment == TopicSentiment.POSITIVE, Survey.id)))).label(
            "positive_count"
        ),
        func.count(func.distinct(case((Survey.topic_sentiment == TopicSentiment.NEGATIVE, Survey.id)))).label(
            "negative_count"
        ),
        func.count(func.distinct(case((Survey.topic_sentiment == TopicSentiment.MIXED, Survey.id)))).label(
            "mixed_count"
        ),
        func.avg(Survey.topic_sentiment_score).label("sentiment_score"),
    ).group_by(Store.id, Store.name).all()

    # Total count query: Apply ALL filters EXCEPT store filters, group by store
    total_count_query, total_count_joins, _ = build_optimized_query(db, filter_dict, exclude_filters=["store_ids", "store_names"])
    
    # Add store join if not already present
    if "store" not in total_count_joins:
        total_count_query = total_count_query.join(Store, Survey.store_id == Store.id)
    
    total_count_results = (
        total_count_query.with_entities(
            Store.id.label("store_id"),
            Store.name.label("store_name"),
            func.count(func.distinct(Survey.id)).label("total_count"),
        )
        .group_by(Store.id, Store.name)
        .all()
    )

    # Get all stores from database
    all_stores = db.query(Store).all()

    # Combine results
    # Create dictionaries keyed by store_id
    sentiment_dict = {row.store_id: row for row in results_grouped_by_store}
    total_count_dict = {row.store_id: row.total_count for row in total_count_results}

    store_distribution = []
    for store in all_stores:
        sentiment_row = sentiment_dict.get(store.id)
        
        if sentiment_row:
            neutral_count = sentiment_row.neutral_count
            positive_count = sentiment_row.positive_count
            negative_count = sentiment_row.negative_count
            mixed_count = sentiment_row.mixed_count
            sentiment_score = float(sentiment_row.sentiment_score or 0.0)
        else:
            neutral_count = 0
            positive_count = 0
            negative_count = 0
            mixed_count = 0
            sentiment_score = 0.0
        
        total_count = total_count_dict.get(store.id, 0)

        store_distribution.append(
            StoreResponse(
                id=store.id,
                name=store.name,
                neutral_count=neutral_count,
                positive_count=positive_count,
                negative_count=negative_count,
                mixed_count=mixed_count,
                sentiment_score=sentiment_score,
                total_count_for_option=total_count,
            )
        )

    return store_distribution


class ChannelAndDeliveryServiceDistributionResponse(BaseModel):
    channel: str
    delivery_service: str
    neutral_count: int
    positive_count: int
    negative_count: int
    mixed_count: int
    sentiment_score: float
    total_count_for_option: int


@router.get("/channel-and-delivery-service-distribution")
async def get_channel_and_delivery_service_distribution(
    filter_params: FilterRequest = Depends(get_filter_params),
    db: Session = Depends(get_db),
) -> List[ChannelAndDeliveryServiceDistributionResponse]:
    filter_dict = filter_params.model_dump()

    # Get all channels and delivery services
    all_channels = db.query(Channel).all()
    all_delivery_services = db.query(DeliveryService).all()

    # Single query to get sentiment counts with channel and delivery service filter
    base_query, _joined_tables, _ = build_optimized_query(db, filter_dict)

    # Add necessary joins if not already present
    if "channel" not in _joined_tables:
        base_query = base_query.join(Channel, Survey.channel_id == Channel.id)
    if "delivery_service" not in _joined_tables:
        base_query = base_query.join(
            DeliveryService, Survey.delivery_service_id == DeliveryService.id
        )
    # Get sentiment counts grouped by channel and delivery service
    results_grouped_by_channel_and_delivery_service=base_query.with_entities(
        Channel.id.label("channel_id"),
        Channel.name.label("channel"),
        DeliveryService.id.label("delivery_service_id"),
        DeliveryService.name.label("delivery_service"),
        func.count(func.distinct(case((Survey.topic_sentiment == TopicSentiment.NEUTRAL, Survey.id)))).label(
            "neutral_count"
        ), 
        func.count(func.distinct(case((Survey.topic_sentiment == TopicSentiment.POSITIVE, Survey.id)))).label(
            "positive_count"
        ),
        func.count(func.distinct(case((Survey.topic_sentiment == TopicSentiment.NEGATIVE, Survey.id)))).label(
            "negative_count"
        ),
        func.count(func.distinct(case((Survey.topic_sentiment == TopicSentiment.MIXED, Survey.id)))).label(
            "mixed_count"
        ),
        func.avg(Survey.topic_sentiment_score).label("sentiment_score"),
    ).group_by(Channel.id, DeliveryService.id).all()

    # Total count query: Apply ALL filters EXCEPT channel and delivery service filters, group by channel and delivery service
    total_count_query, total_count_joins, _ = build_optimized_query(db, filter_dict, exclude_filters=["channel_ids", "channel_names", "delivery_service_ids", "delivery_service_names"])
    
    # Add necessary joins if not already present
    if "channel" not in total_count_joins:
        total_count_query = total_count_query.join(Channel, Survey.channel_id == Channel.id)
    if "delivery_service" not in total_count_joins:
        total_count_query = total_count_query.join(
            DeliveryService, Survey.delivery_service_id == DeliveryService.id
        )
    
    total_count_results = (
        total_count_query.with_entities(
            Channel.id.label("channel_id"),
            DeliveryService.id.label("delivery_service_id"),
            func.count(func.distinct(Survey.id)).label("total_count"),
        )
        .group_by(Channel.id, DeliveryService.id)
        .all()
    )

    # Combine results
    # Create dictionaries keyed by (channel_id, delivery_service_id)
    sentiment_dict = {
        (row.channel_id, row.delivery_service_id): row 
        for row in results_grouped_by_channel_and_delivery_service
    }
    
    total_count_dict = {
        (row.channel_id, row.delivery_service_id): row.total_count
        for row in total_count_results
    }
    
    # Iterate through ALL possible channel and delivery service combinations
    channel_and_delivery_service_distribution = []
    for channel in all_channels:
        for delivery_service in all_delivery_services:
            # Look up sentiment data for this channel/delivery service combination
            sentiment_data = sentiment_dict.get((channel.id, delivery_service.id))
            
            if sentiment_data:
                # Use actual sentiment counts
                neutral_count = sentiment_data.neutral_count
                positive_count = sentiment_data.positive_count
                negative_count = sentiment_data.negative_count
                mixed_count = sentiment_data.mixed_count
                sentiment_score = float(sentiment_data.sentiment_score or 0.0)
            else:
                # No sentiment data found, use 0
                neutral_count = 0
                positive_count = 0
                negative_count = 0
                mixed_count = 0
                sentiment_score = 0.0
            
            # Get total count (from query with all filters)
            total_count = total_count_dict.get((channel.id, delivery_service.id), 0)
            
            channel_and_delivery_service_distribution.append(
                ChannelAndDeliveryServiceDistributionResponse(
                    channel=channel.name,
                    delivery_service=delivery_service.name,
                    neutral_count=neutral_count,
                    positive_count=positive_count,
                    negative_count=negative_count,
                    mixed_count=mixed_count,
                    sentiment_score=sentiment_score,
                    total_count_for_option=total_count,
                )
            )
    
    return channel_and_delivery_service_distribution


class TopicSentimentScoreResponse(BaseModel):
    positive_topic_count: int
    negative_topic_count: int
    neutral_topic_count: int
    mix_topic_count: int
    average_mix_topic_score: float
    average_overall_topic_score: float


@router.get("/topic-sentiment-score")
async def get_topic_sentiment_score(
    filter_params: FilterRequest = Depends(get_filter_params),
    db: Session = Depends(get_db),
) -> TopicSentimentScoreResponse:
    filter_dict = filter_params.model_dump()

    # Build base query with filters
    base_query, joined_tables, _ = build_optimized_query(db, filter_dict)

    neutral_count_result = base_query.with_entities(
        func.count(func.distinct(case((Survey.topic_sentiment == TopicSentiment.NEUTRAL, Survey.id)))).label(
            "neutral_count"
        )
    ).first()
    positive_count_result = base_query.with_entities(
        func.count(func.distinct(case((Survey.topic_sentiment == TopicSentiment.POSITIVE, Survey.id)))).label(
            "positive_count"
        )
    ).first()
    negative_count_result = base_query.with_entities(
        func.count(func.distinct(case((Survey.topic_sentiment == TopicSentiment.NEGATIVE, Survey.id)))).label(
        "negative_count"
    )).first()
    mixed_count_result = base_query.with_entities(
        func.count(func.distinct(case((Survey.topic_sentiment == TopicSentiment.MIXED, Survey.id)))).label(
            "mixed_count"
        )
    ).first()
    # Find the average sentiment score for surveys which have mixed sentiment
    average_mix_topic_sentiment_score_result = base_query.with_entities(
        func.avg(Survey.topic_sentiment_score).label("average_mix_topic_sentiment_score")
    ).filter(Survey.topic_sentiment == TopicSentiment.MIXED).first()
    # Find the average sentiment score for surveys for all sentiment types
    average_overall_topic_sentiment_score_result = base_query.with_entities(
        func.avg(Survey.topic_sentiment_score).label("average_overall_topic_sentiment_score")
    ).first()
    return TopicSentimentScoreResponse(
        positive_topic_count=positive_count_result.positive_count or 0,
        negative_topic_count=negative_count_result.negative_count or 0,
        neutral_topic_count=neutral_count_result.neutral_count or 0,
        mix_topic_count=mixed_count_result.mixed_count or 0,
        average_mix_topic_score=float(average_mix_topic_sentiment_score_result.average_mix_topic_sentiment_score or 0.0),
        average_overall_topic_score=float(average_overall_topic_sentiment_score_result.average_overall_topic_sentiment_score or 0.0),
    )


@router.get("/last-updated-date")
async def get_last_updated_date(
    db: Session = Depends(get_db),
) -> str:
    last_updated_date = (
        db.query(func.max(Survey.updated_at)).first()
    )
    if last_updated_date[0] is None:
        return ""
    return last_updated_date[0].astimezone(timezone.utc).isoformat()


class DataCoverageResponse(BaseModel):
    last_data_reported_date: str
    first_data_reported_date: str


@router.get("/data-coverage")
async def get_data_coverage(
    db: Session = Depends(get_db),
) -> DataCoverageResponse:
    last_data_reported_date = (
        db.query(func.max(Survey.reported_at))
        .filter(Survey.is_deleted == False)
        .first()
    )
    first_data_reported_date = (
        db.query(func.min(Survey.reported_at))
        .filter(Survey.is_deleted == False)
        .first()
    )
    if last_data_reported_date[0] is None or first_data_reported_date[0] is None:
        raise HTTPException(status_code=404, detail="No data reported")
    return DataCoverageResponse(
        last_data_reported_date=last_data_reported_date[0]
        .astimezone(timezone.utc)
        .isoformat(),
        first_data_reported_date=first_data_reported_date[0]
        .astimezone(timezone.utc)
        .isoformat(),
    )
