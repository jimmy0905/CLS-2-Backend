from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, or_, distinct, case, and_, cast, Float
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
            func.count(Survey.id).label("total_count"),
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
    keyword_results = (
        build_SurveyKeywords_sentiment_aggregation_query(
            base_query, Keyword.keyword.label("keyword")
        )
        .order_by(func.count(Survey.id).desc())
        .limit(k)
        .all()
    )

    return [
        KeywordAnalysisResponse(
            keyword=row.keyword,
            neutral_count=row.neutral_count,
            positive_count=row.positive_count,
            negative_count=row.negative_count,
        )
        for row in keyword_results
    ]


class HierarchyDistributionResponse(BaseModel):
    id: int
    name: str
    level: int
    neutral_count: int
    positive_count: int
    negative_count: int
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

    sentiment_results = build_Survey_sentiment_aggregation_query(
        sentiment_query,
        sentiment_hierarchy_alias.id.label("hierarchy_id"),
        sentiment_hierarchy_alias.name.label("hierarchy_name"),
    ).all()

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
            func.count(Survey.id).label("total_count"),
        )
        .group_by(total_hierarchy_alias.id, total_hierarchy_alias.name)
        .all()
    )

    # Combine results
    sentiment_dict = {row.hierarchy_id: row for row in sentiment_results}
    total_dict = {row.hierarchy_id: row.total_count for row in total_results}

    hierarchy_distribution = []
    for hierarchy_id in set(list(sentiment_dict.keys()) + list(total_dict.keys())):
        sentiment_row = sentiment_dict.get(hierarchy_id)
        total_count = total_dict.get(hierarchy_id, 0)

        # Get hierarchy name from either sentiment or total results
        hierarchy_name = (
            sentiment_row.hierarchy_name
            if sentiment_row
            else next(
                (
                    row.hierarchy_name
                    for row in total_results
                    if row.hierarchy_id == hierarchy_id
                ),
                "",
            )
        )

        hierarchy_distribution.append(
            HierarchyDistributionResponse(
                id=hierarchy_id,
                name=hierarchy_name,
                level=level,
                neutral_count=sentiment_row.neutral_count if sentiment_row else 0,
                positive_count=sentiment_row.positive_count if sentiment_row else 0,
                negative_count=sentiment_row.negative_count if sentiment_row else 0,
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
            Topic.topic.label("topic"), func.count(Survey.id).label("total_count")
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
    neutral_count: int
    positive_count: int
    negative_count: int
    total_positive_count_for_option: int
    total_negative_count_for_option: int
    total_neutral_count_for_option: int


@router.get("/sentiment-distribution")
async def get_sentiment_distribution(
    filter_params: FilterRequest = Depends(get_filter_params),
    db: Session = Depends(get_db),
) -> List[DailySentimentDistributionResponse]:
    filter_dict = filter_params.model_dump()

    # Single query to get both sentiment and total counts by date
    sentiment_query, _, _ = build_optimized_query(db, filter_dict)

    sentiment_results = (
        build_Survey_sentiment_aggregation_query(
            sentiment_query, func.date(Survey.reported_at).label("date")
        )
        .group_by(func.date(Survey.reported_at))
        .order_by(func.date(Survey.reported_at))
        .all()
    )
    total_query, _, _ = build_optimized_query(
        db, filter_dict, exclude_filters=["sentiments"]
    )
    total_results = total_query.with_entities(
        func.date(Survey.reported_at).label("date"),
        func.count(case((Survey.sentiment == "neutral", Survey.id))).label(
            "neutral_count_for_option"
        ),
        func.count(case((Survey.sentiment == "positive", Survey.id))).label(
            "positive_count_for_option"
        ),
        func.count(case((Survey.sentiment == "negative", Survey.id))).label(
            "negative_count_for_option"
        ),
    )
    total_results = total_results.group_by(func.date(Survey.reported_at)).all()
    sentiment_dict = {row.date: row for row in sentiment_results}
    total_dict = {row.date: row for row in total_results}

    date_results = []
    for date in set(list(sentiment_dict.keys()) + list(total_dict.keys())):
        sentiment_row = sentiment_dict.get(date)
        total_row = total_dict.get(date)

        date_results.append(
            DailySentimentDistributionResponse(
                year=date.year,
                month=date.month,
                day=date.day,
                neutral_count=sentiment_row.neutral_count if sentiment_row else 0,
                positive_count=sentiment_row.positive_count if sentiment_row else 0,
                negative_count=sentiment_row.negative_count if sentiment_row else 0,
                total_positive_count_for_option=total_row.positive_count_for_option,
                total_negative_count_for_option=total_row.negative_count_for_option,
                total_neutral_count_for_option=total_row.neutral_count_for_option,
            )
        )

    return date_results


class StoreResponse(BaseModel):
    id: int
    name: str
    neutral_count: int
    positive_count: int
    negative_count: int
    total_count_for_option: int


@router.get("/store-distribution")
async def get_store_distribution(
    filter_params: FilterRequest = Depends(get_filter_params),
    db: Session = Depends(get_db),
) -> List[StoreResponse]:
    filter_dict = filter_params.model_dump()

    # Single query to get sentiment counts with store filter
    sentiment_query, sentiment_joins, _ = build_optimized_query(db, filter_dict)

    # Add store join if not already present
    if "store" not in sentiment_joins:
        sentiment_query = sentiment_query.join(Store, Survey.store_id == Store.id)

    sentiment_results = build_Survey_sentiment_aggregation_query(
        sentiment_query, Store.id.label("store_id"), Store.name.label("store_name")
    ).all()

    # Total count query: Apply ALL filters EXCEPT store filters, but group by store
    total_query, total_joins, _ = build_optimized_query(
        db, filter_dict, exclude_filters=["store_ids", "store_names"]
    )

    # Always add store join for total counts since we need to group by store
    if "store" not in total_joins:
        total_query = total_query.join(Store, Survey.store_id == Store.id)

    total_results = (
        total_query.with_entities(
            Store.id.label("store_id"),
            Store.name.label("store_name"),
            func.count(Survey.id).label("total_count"),
        )
        .group_by(Store.id, Store.name)
        .all()
    )

    # Combine results
    sentiment_dict = {row.store_id: row for row in sentiment_results}
    total_dict = {row.store_id: row.total_count for row in total_results}

    store_distribution = []
    for store_id in set(list(sentiment_dict.keys()) + list(total_dict.keys())):
        sentiment_row = sentiment_dict.get(store_id)
        total_count = total_dict.get(store_id, 0)

        # Get store name from either sentiment or total results
        store_name = (
            sentiment_row.store_name
            if sentiment_row
            else next(
                (row.store_name for row in total_results if row.store_id == store_id),
                "",
            )
        )

        store_distribution.append(
            StoreResponse(
                id=store_id,
                name=store_name,
                neutral_count=sentiment_row.neutral_count if sentiment_row else 0,
                positive_count=sentiment_row.positive_count if sentiment_row else 0,
                negative_count=sentiment_row.negative_count if sentiment_row else 0,
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
    sentiment_query, sentiment_joins, _ = build_optimized_query(db, filter_dict)

    # Add necessary joins if not already present
    if "channel" not in sentiment_joins:
        sentiment_query = sentiment_query.join(Channel, Survey.channel_id == Channel.id)
    if "delivery_service" not in sentiment_joins:
        sentiment_query = sentiment_query.join(
            DeliveryService, Survey.delivery_service_id == DeliveryService.id
        )

    sentiment_results = build_Survey_sentiment_aggregation_query(
        sentiment_query,
        Channel.name.label("channel"),
        DeliveryService.name.label("delivery_service"),
    ).all()

    # Total count query: Apply ALL filters EXCEPT channel and delivery service filters, but group by channel and delivery service
    total_query, total_joins, _ = build_optimized_query(
        db,
        filter_dict,
        exclude_filters=[
            "channel_ids",
            "channel_names",
            "delivery_service_ids",
            "delivery_service_names",
        ],
    )

    # Always add necessary joins for total counts since we need to group by channel and delivery service
    if "channel" not in total_joins:
        total_query = total_query.join(Channel, Survey.channel_id == Channel.id)
    if "delivery_service" not in total_joins:
        total_query = total_query.join(
            DeliveryService, Survey.delivery_service_id == DeliveryService.id
        )

    total_results = (
        total_query.with_entities(
            Channel.name.label("channel"),
            DeliveryService.name.label("delivery_service"),
            func.count(Survey.id).label("total_count"),
        )
        .group_by(Channel.id, Channel.name, DeliveryService.id, DeliveryService.name)
        .all()
    )

    # Combine results
    sentiment_dict = {
        (row.channel, row.delivery_service): row for row in sentiment_results
    }
    total_dict = {
        (row.channel, row.delivery_service): row.total_count for row in total_results
    }

    # Generate all possible combinations
    channel_and_delivery_service_distribution = []
    for channel in all_channels:
        for delivery_service in all_delivery_services:
            channel_name = channel.name
            delivery_service_name = delivery_service.name

            sentiment_row = sentiment_dict.get((channel_name, delivery_service_name))
            total_count = total_dict.get((channel_name, delivery_service_name), 0)

            channel_and_delivery_service_distribution.append(
                ChannelAndDeliveryServiceDistributionResponse(
                    channel=channel_name,
                    delivery_service=delivery_service_name,
                    neutral_count=sentiment_row.neutral_count if sentiment_row else 0,
                    positive_count=sentiment_row.positive_count if sentiment_row else 0,
                    negative_count=sentiment_row.negative_count if sentiment_row else 0,
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

    # Add topic joins if not already present
    if "topic" not in joined_tables:
        base_query = base_query.outerjoin(
            SurveyTopics, Survey.id == SurveyTopics.survey_id
        )

    # Create CTE for topic counts per survey
    positive_count = func.sum(
        case((SurveyTopics.sentiment == "POSITIVE", 1), else_=0)
    ).label("positive_count")

    negative_count = func.sum(
        case((SurveyTopics.sentiment == "NEGATIVE", 1), else_=0)
    ).label("negative_count")

    neutral_count = func.sum(
        case((SurveyTopics.sentiment == "NEUTRAL", 1), else_=0)
    ).label("neutral_count")

    total_topics = func.count(SurveyTopics.id).label("total_topics")

    # Build subquery with topic counts
    topic_counts_subquery = (
        base_query.with_entities(
            Survey.id.label("survey_id"),
            positive_count,
            negative_count,
            neutral_count,
            total_topics,
        )
        .group_by(Survey.id)
        .subquery()
    )

    # Calculate sentiment score and category for each survey
    sentiment_score_expr = case(
        # If survey has no topics, return 0
        (topic_counts_subquery.c.total_topics == 0, 0.0),
        # If only neutral topics, return 0 , neutral
        (
            (topic_counts_subquery.c.positive_count == 0)
            & (topic_counts_subquery.c.negative_count == 0),
            0.0,
        ),
        # If only positive and neutral (no negative), return 1 , positive
        (
            (topic_counts_subquery.c.positive_count > 0)
            & (topic_counts_subquery.c.negative_count == 0),
            1.0,
        ),
        # If only negative and neutral (no positive), return -1 , negative
        (
            (topic_counts_subquery.c.positive_count == 0)
            & (topic_counts_subquery.c.negative_count > 0),
            -1.0,
        ),
        # Otherwise, calculate (Positive - Negative) / Total
        else_=(
            cast(
                topic_counts_subquery.c.positive_count
                - topic_counts_subquery.c.negative_count,
                Float,
            )
            / topic_counts_subquery.c.total_topics
        ),
    ).label("sentiment_score")

    category_expr = case(
        # Only neutral topics
        (
            (topic_counts_subquery.c.positive_count == 0)
            & (topic_counts_subquery.c.negative_count == 0),
            "neutral_only",
        ),
        # Only positive and neutral (no negative)
        (
            (topic_counts_subquery.c.positive_count > 0)
            & (topic_counts_subquery.c.negative_count == 0),
            "positive_only",
        ),
        # Only negative and neutral (no positive)
        (
            (topic_counts_subquery.c.positive_count == 0)
            & (topic_counts_subquery.c.negative_count > 0),
            "negative_only",
        ),
        # Mixed: both positive and negative
        else_="mixed",
    ).label("category")

    # Create categories subquery
    categories_subquery = db.query(
        topic_counts_subquery.c.survey_id, sentiment_score_expr, category_expr
    ).subquery()

    # Final aggregation query

    result = db.query(
        func.sum(
            case((categories_subquery.c.category == "positive_only", 1), else_=0)
        ).label("positive_topic_count"),
        func.sum(
            case((categories_subquery.c.category == "negative_only", 1), else_=0)
        ).label("negative_topic_count"),
        func.sum(
            case((categories_subquery.c.category == "neutral_only", 1), else_=0)
        ).label("neutral_topic_count"),
        func.sum(case((categories_subquery.c.category == "mixed", 1), else_=0)).label(
            "mix_topic_count"
        ),
        func.avg(
            case(
                (
                    categories_subquery.c.category == "mixed",
                    categories_subquery.c.sentiment_score,
                )
            )
        ).label("average_mix_topic_score"),
    ).first()

    average_overall_topic_score = (
        (result.mix_topic_count * (result.average_mix_topic_score or 0.0))
        + (result.positive_topic_count * 1.0)
        + (result.negative_topic_count * -1.0)
        + (result.neutral_topic_count * 0.0)
    ) / (
        result.mix_topic_count
        + result.positive_topic_count
        + result.negative_topic_count
        + result.neutral_topic_count
    )
    return TopicSentimentScoreResponse(
        positive_topic_count=result.positive_topic_count or 0,
        negative_topic_count=result.negative_topic_count or 0,
        neutral_topic_count=result.neutral_topic_count or 0,
        mix_topic_count=result.mix_topic_count or 0,
        average_mix_topic_score=float(result.average_mix_topic_score or 0.0),
        average_overall_topic_score=float(average_overall_topic_score or 0.0),
    )

@router.get("/last-updated-date")
async def get_last_updated_date(
    db: Session = Depends(get_db),
) -> str:
    last_updated_date = db.query(func.max(Survey.updated_at)).first()
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
    last_data_reported_date = db.query(func.max(Survey.reported_at)).first()
    first_data_reported_date = db.query(func.min(Survey.reported_at)).first()
    if last_data_reported_date[0] is None or first_data_reported_date[0] is None:
        raise HTTPException(status_code=404, detail="No data reported")
    return DataCoverageResponse(
        last_data_reported_date=last_data_reported_date[0].astimezone(timezone.utc).isoformat(),
        first_data_reported_date=first_data_reported_date[0].astimezone(timezone.utc).isoformat(),
    )