from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, case, extract
from models.Survey import Survey
from models.Topic import Topic
from models.Keyword import Keyword
from models.SurveyKeywords import SurveyKeywords
from models.SurveyDepartments import SurveyDepartments
from models.Store import Store
from models.Department import Department
from models.SurveyTopics import SurveyTopics
from models.Channel import Channel
from models.DeliveryService import DeliveryService
from models.enum.Sentiment import Sentiment, TopicSentiment
from utils.database import get_db
from pydantic import BaseModel
from utils.conditionFilter import (
    build_optimized_query,
    FilterRequest,
    get_filter_params,
)
from typing import List, Optional
from utils.security import get_current_user
from datetime import date
from utils.utc import local_isoformat, resolve_timezone

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
    base_query, _joined_tables, _ = build_optimized_query(db, filter_dict)

    # Add department join if not already present
    if "department" not in _joined_tables:
        base_query = base_query.join(
            SurveyDepartments, Survey.id == SurveyDepartments.survey_id
        )
        base_query = base_query.join(
            Department, SurveyDepartments.department_id == Department.id
        )
        _joined_tables.add("department")

    sentiment_results = (
        base_query.with_entities(
            Department.id.label("department_id"),
            Department.name.label("department"),
            func.count(
                func.distinct(
                    case(
                        (
                            SurveyDepartments.sentiment == Sentiment.NEUTRAL,
                            SurveyDepartments.id,
                        )
                    )
                )
            ).label("neutral_count"),
            func.count(
                func.distinct(
                    case(
                        (
                            SurveyDepartments.sentiment == Sentiment.POSITIVE,
                            SurveyDepartments.id,
                        )
                    )
                )
            ).label("positive_count"),
            func.count(
                func.distinct(
                    case(
                        (
                            SurveyDepartments.sentiment == Sentiment.NEGATIVE,
                            SurveyDepartments.id,
                        )
                    )
                )
            ).label("negative_count"),
        )
        .group_by(Department.id, Department.name)
        .all()
    )

    # Total count query: Apply ALL filters EXCEPT department filters, group by department
    total_count_query, total_count_joins, _ = build_optimized_query(
        db, filter_dict, exclude_filters=["department_ids", "department_names"]
    )

    # Add department join if not already present
    if "department" not in total_count_joins:
        total_count_query = total_count_query.join(
            SurveyDepartments, Survey.id == SurveyDepartments.survey_id
        )
        total_count_query = total_count_query.join(
            Department, SurveyDepartments.department_id == Department.id
        )
        total_count_joins.add("department")

    total_count_results = (
        total_count_query.with_entities(
            Department.id.label("department_id"),
            Department.name.label("department"),
            func.count(func.distinct(SurveyDepartments.id)).label("total_count"),
        )
        .group_by(Department.id, Department.name)
        .all()
    )

    # Get all departments from database
    all_departments = db.query(Department).all()
    # Combine results
    sentiment_dict = {row.department_id: row for row in sentiment_results}
    total_count_dict = {
        row.department_id: row.total_count for row in total_count_results
    }
    department_distribution = []
    for department in all_departments:
        sentiment_row = sentiment_dict.get(department.id)

        if sentiment_row:
            neutral_count = sentiment_row.neutral_count
            positive_count = sentiment_row.positive_count
            negative_count = sentiment_row.negative_count
        else:
            neutral_count = 0
            positive_count = 0
            negative_count = 0
        total_count = total_count_dict.get(department.id, 0)
        department_distribution.append(
            DepartmentDistributionResponse(
                department=department.name,
                neutral_count=neutral_count,
                positive_count=positive_count,
                negative_count=negative_count,
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
    base_query, _joined_tables, _ = build_optimized_query(db, filter_dict)

    # Check if keyword joins are already present, if not add them
    if "keyword" not in _joined_tables:
        base_query = base_query.join(
            SurveyKeywords, Survey.id == SurveyKeywords.survey_id
        )
        base_query = base_query.join(Keyword, SurveyKeywords.keyword_id == Keyword.id)
        _joined_tables.add("keyword")

    sentiment_results = (
        base_query.with_entities(
            Keyword.keyword.label("keyword"),
            func.count(
                func.distinct(
                    case(
                        (
                            SurveyKeywords.sentiment == Sentiment.NEUTRAL,
                            SurveyKeywords.id,
                        )
                    )
                )
            ).label("neutral_count"),
            func.count(
                func.distinct(
                    case(
                        (
                            SurveyKeywords.sentiment == Sentiment.POSITIVE,
                            SurveyKeywords.id,
                        )
                    )
                )
            ).label("positive_count"),
            func.count(
                func.distinct(
                    case(
                        (
                            SurveyKeywords.sentiment == Sentiment.NEGATIVE,
                            SurveyKeywords.id,
                        )
                    )
                )
            ).label("negative_count"),
        )
        .group_by(Keyword.id, Keyword.keyword)
        .order_by(func.count(func.distinct(SurveyKeywords.id)).desc())
        .limit(k)
        .all()
    )
    return sentiment_results


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
    base_query, _joined_tables, _ = build_optimized_query(db, filter_dict)
    if "topic" not in _joined_tables:
        base_query = base_query.join(SurveyTopics, Survey.id == SurveyTopics.survey_id)
        base_query = base_query.join(Topic, SurveyTopics.topic_id == Topic.id)
        _joined_tables.add("topic")

    # Count each SurveyTopics occurrence (same survey can have same topic with different sentiments)
    sentiment_results = (
        base_query.with_entities(
            Topic.topic.label("topic"),
            Topic.id.label("topic_id"),
            func.count(
                func.distinct(
                    case((SurveyTopics.sentiment == Sentiment.NEUTRAL, SurveyTopics.id))
                )
            ).label("neutral_count"),
            func.count(
                func.distinct(
                    case(
                        (SurveyTopics.sentiment == Sentiment.POSITIVE, SurveyTopics.id)
                    )
                )
            ).label("positive_count"),
            func.count(
                func.distinct(
                    case(
                        (SurveyTopics.sentiment == Sentiment.NEGATIVE, SurveyTopics.id)
                    )
                )
            ).label("negative_count"),
        )
        .group_by(Topic.id, Topic.topic)
        .all()
    )

    # Total count query: Apply ALL filters EXCEPT topic filters, group by topic
    total_count_query, total_count_joins, _ = build_optimized_query(
        db, filter_dict, exclude_filters=["topics"]
    )

    # Add necessary joins for total count query
    if "topic" not in total_count_joins:
        total_count_query = total_count_query.join(
            SurveyTopics, Survey.id == SurveyTopics.survey_id
        )
        total_count_query = total_count_query.join(
            Topic, SurveyTopics.topic_id == Topic.id
        )

    # Total count: each SurveyTopics record counts (same topic in same survey with different sentiments = 2)
    total_count_results = (
        total_count_query.with_entities(
            Topic.id.label("topic_id"),
            Topic.topic.label("topic_name"),
            func.count(func.distinct(SurveyTopics.id)).label("total_count"),
        )
        .group_by(Topic.id, Topic.topic)
        .all()
    )

    # Get all topics from database
    all_topics = db.query(Topic).all()

    # Combine results
    sentiment_dict = {row.topic_id: row for row in sentiment_results}
    total_count_dict = {row.topic_id: row.total_count for row in total_count_results}

    topic_distribution = []
    for topic in all_topics:
        sentiment_row = sentiment_dict.get(topic.id)

        if sentiment_row:
            neutral_count = sentiment_row.neutral_count
            positive_count = sentiment_row.positive_count
            negative_count = sentiment_row.negative_count
        else:
            neutral_count = 0
            positive_count = 0
            negative_count = 0

        total_count = total_count_dict.get(topic.id, 0)

        topic_distribution.append(
            TopicDistributionResponse(
                topic=topic.topic,
                neutral_count=neutral_count,
                positive_count=positive_count,
                negative_count=negative_count,
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

    reported_at_local = func.timezone(
        filter_params.timezone or "UTC", Survey.reported_at
    )
    date_results = (
        base_query.with_entities(
            extract("year", reported_at_local).label("year"),
            extract("month", reported_at_local).label("month"),
            extract("day", reported_at_local).label("day"),
            func.count(
                func.distinct(
                    case((Survey.topic_sentiment == TopicSentiment.NEUTRAL, Survey.id))
                )
            ).label("neutral_count"),
            func.count(
                func.distinct(
                    case((Survey.topic_sentiment == TopicSentiment.POSITIVE, Survey.id))
                )
            ).label("positive_count"),
            func.count(
                func.distinct(
                    case((Survey.topic_sentiment == TopicSentiment.NEGATIVE, Survey.id))
                )
            ).label("negative_count"),
            func.count(
                func.distinct(
                    case((Survey.topic_sentiment == TopicSentiment.MIXED, Survey.id))
                )
            ).label("mixed_count"),
            func.avg(Survey.topic_sentiment_score).label("sentiment_score"),
        )
        .group_by(
            extract("year", reported_at_local),
            extract("month", reported_at_local),
            extract("day", reported_at_local),
        )
        .all()
    )

    return date_results


class StoreResponse(BaseModel):
    store_key: int
    store_english_name: Optional[str] = None
    store_local_name: Optional[str] = None
    store_open_date: Optional[date] = None
    store_close_date: Optional[date] = None
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
        base_query = base_query.join(Store, Survey.store_key == Store.store_key)

    results_grouped_by_store = (
        base_query.with_entities(
            Store.store_key.label("store_key"),
            Store.store_name_english.label("store_english_name"),
            Store.store_name_local.label("store_local_name"),
            func.count(
                func.distinct(
                    case((Survey.topic_sentiment == TopicSentiment.NEUTRAL, Survey.id))
                )
            ).label("neutral_count"),
            func.count(
                func.distinct(
                    case((Survey.topic_sentiment == TopicSentiment.POSITIVE, Survey.id))
                )
            ).label("positive_count"),
            func.count(
                func.distinct(
                    case((Survey.topic_sentiment == TopicSentiment.NEGATIVE, Survey.id))
                )
            ).label("negative_count"),
            func.count(
                func.distinct(
                    case((Survey.topic_sentiment == TopicSentiment.MIXED, Survey.id))
                )
            ).label("mixed_count"),
            func.avg(Survey.topic_sentiment_score).label("sentiment_score"),
        )
        .group_by(Store.store_key)
        .all()
    )

    # Total count query: Apply ALL filters EXCEPT store filters, group by store
    total_count_query, total_count_joins, _ = build_optimized_query(
        db, filter_dict, exclude_filters=["store_keys", "store_names"]
    )

    # Add store join if not already present
    if "store" not in total_count_joins:
        total_count_query = total_count_query.join(Store, Survey.store_key == Store.store_key)

    total_count_results = (
        total_count_query.with_entities(
            Store.store_key.label("store_key"),
            Store.store_name_english.label("store_english_name"),
            Store.store_name_local.label("store_local_name"),
            func.count(func.distinct(Survey.id)).label("total_count"),
        )
        .group_by(Store.store_key)
        .all()
    )

    # Get all stores from database
    all_stores = db.query(Store).all()

    # Combine results
    # Create dictionaries keyed by store_key
    sentiment_dict = {row.store_key: row for row in results_grouped_by_store}
    total_count_dict = {row.store_key: row.total_count for row in total_count_results}

    store_distribution = []
    for store in all_stores:
        sentiment_row = sentiment_dict.get(store.store_key)

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

        total_count = total_count_dict.get(store.store_key, 0)

        store_distribution.append(
            StoreResponse(
                store_key=store.store_key,
                store_english_name=store.store_name_english,
                store_local_name=store.store_name_local,
                store_open_date=store.store_open_date,
                store_close_date=store.store_close_date,
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
    channel: Optional[str] = None
    delivery_service: Optional[str] = None
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

    # Single query to get sentiment counts with channel and delivery service filter
    base_query, _joined_tables, _ = build_optimized_query(db, filter_dict)

    # Use LEFT JOIN to handle cases where channel or delivery service might be null
    if "channel" not in _joined_tables:
        base_query = base_query.outerjoin(Channel, Survey.channel_id == Channel.id)
    if "delivery_service" not in _joined_tables:
        base_query = base_query.outerjoin(
            DeliveryService, Survey.delivery_service_id == DeliveryService.id
        )
    
    # Get sentiment counts grouped by channel and delivery service
    results_grouped_by_channel_and_delivery_service = (
        base_query.with_entities(
            Channel.id.label("channel_id"),
            Channel.name.label("channel"),
            DeliveryService.id.label("delivery_service_id"),
            DeliveryService.name.label("delivery_service"),
            func.count(
                func.distinct(
                    case((Survey.topic_sentiment == TopicSentiment.NEUTRAL, Survey.id))
                )
            ).label("neutral_count"),
            func.count(
                func.distinct(
                    case((Survey.topic_sentiment == TopicSentiment.POSITIVE, Survey.id))
                )
            ).label("positive_count"),
            func.count(
                func.distinct(
                    case((Survey.topic_sentiment == TopicSentiment.NEGATIVE, Survey.id))
                )
            ).label("negative_count"),
            func.count(
                func.distinct(
                    case((Survey.topic_sentiment == TopicSentiment.MIXED, Survey.id))
                )
            ).label("mixed_count"),
            func.avg(Survey.topic_sentiment_score).label("sentiment_score"),
        )
        .group_by(Channel.id, Channel.name, DeliveryService.id, DeliveryService.name)
        .all()
    )

    # Total count query: Apply ALL filters EXCEPT channel and delivery service filters, group by channel and delivery service
    total_count_query, total_count_joins, _ = build_optimized_query(
        db,
        filter_dict,
        exclude_filters=[
            "channel_ids",
            "channel_names",
            "delivery_service_ids",
            "delivery_service_names",
        ],
    )

    # Use LEFT JOIN for total count query as well
    if "channel" not in total_count_joins:
        total_count_query = total_count_query.outerjoin(
            Channel, Survey.channel_id == Channel.id
        )
    if "delivery_service" not in total_count_joins:
        total_count_query = total_count_query.outerjoin(
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
    # Note: channel_id or delivery_service_id can be None
    sentiment_dict = {
        (row.channel_id, row.delivery_service_id): row
        for row in results_grouped_by_channel_and_delivery_service
    }

    total_count_dict = {
        (row.channel_id, row.delivery_service_id): row.total_count
        for row in total_count_results
    }

    # Build response from actual data combinations (not all possible combinations)
    channel_and_delivery_service_distribution = []
    for key, sentiment_data in sentiment_dict.items():
        channel_id, delivery_service_id = key
        
        # Get total count for this combination
        total_count = total_count_dict.get(key, 0)

        channel_and_delivery_service_distribution.append(
            ChannelAndDeliveryServiceDistributionResponse(
                channel=sentiment_data.channel,
                delivery_service=sentiment_data.delivery_service,
                neutral_count=sentiment_data.neutral_count,
                positive_count=sentiment_data.positive_count,
                negative_count=sentiment_data.negative_count,
                mixed_count=sentiment_data.mixed_count,
                sentiment_score=float(sentiment_data.sentiment_score or 0.0),
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
        func.count(
            func.distinct(
                case((Survey.topic_sentiment == TopicSentiment.NEUTRAL, Survey.id))
            )
        ).label("neutral_count")
    ).first()
    positive_count_result = base_query.with_entities(
        func.count(
            func.distinct(
                case((Survey.topic_sentiment == TopicSentiment.POSITIVE, Survey.id))
            )
        ).label("positive_count")
    ).first()
    negative_count_result = base_query.with_entities(
        func.count(
            func.distinct(
                case((Survey.topic_sentiment == TopicSentiment.NEGATIVE, Survey.id))
            )
        ).label("negative_count")
    ).first()
    mixed_count_result = base_query.with_entities(
        func.count(
            func.distinct(
                case((Survey.topic_sentiment == TopicSentiment.MIXED, Survey.id))
            )
        ).label("mixed_count")
    ).first()
    # Find the average sentiment score for surveys which have mixed sentiment
    average_mix_topic_sentiment_score_result = (
        base_query.with_entities(
            func.avg(Survey.topic_sentiment_score).label(
                "average_mix_topic_sentiment_score"
            )
        )
        .filter(Survey.topic_sentiment == TopicSentiment.MIXED)
        .first()
    )
    # Find the average sentiment score for surveys for all sentiment types
    average_overall_topic_sentiment_score_result = base_query.with_entities(
        func.avg(Survey.topic_sentiment_score).label(
            "average_overall_topic_sentiment_score"
        )
    ).first()
    return TopicSentimentScoreResponse(
        positive_topic_count=positive_count_result.positive_count or 0,
        negative_topic_count=negative_count_result.negative_count or 0,
        neutral_topic_count=neutral_count_result.neutral_count or 0,
        mix_topic_count=mixed_count_result.mixed_count or 0,
        average_mix_topic_score=float(
            average_mix_topic_sentiment_score_result.average_mix_topic_sentiment_score
            or 0.0
        ),
        average_overall_topic_score=float(
            average_overall_topic_sentiment_score_result.average_overall_topic_sentiment_score
            or 0.0
        ),
    )


@router.get("/last-updated-date")
async def get_last_updated_date(
    timezone: Optional[str] = Query(
        default=None,
        description="Optional IANA timezone for timestamp display; UTC is used when omitted",
    ),
    db: Session = Depends(get_db),
) -> str:
    try:
        resolve_timezone(timezone)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    last_updated_date = db.query(func.max(Survey.updated_at)).first()
    if last_updated_date[0] is None:
        return ""
    return local_isoformat(last_updated_date[0], timezone) or ""


class DataCoverageResponse(BaseModel):
    last_data_reported_date: str
    first_data_reported_date: str


@router.get("/data-coverage")
async def get_data_coverage(
    timezone: Optional[str] = Query(
        default=None,
        description="Optional IANA timezone for timestamp display; UTC is used when omitted",
    ),
    db: Session = Depends(get_db),
) -> DataCoverageResponse:
    try:
        resolve_timezone(timezone)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
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
        last_data_reported_date=local_isoformat(last_data_reported_date[0], timezone) or "",
        first_data_reported_date=local_isoformat(first_data_reported_date[0], timezone) or "",
    )


class StoreColumnSentimentDistributionResponse(BaseModel):
    column_name: str
    neutral_count: int
    positive_count: int
    negative_count: int
    mixed_count: int
    sentiment_score: float
    total_count_for_option: int


@router.get("/store-column-sentiment-distribution")
async def get_store_column_sentiment_distribution(
    column: str = Query(
        ...,
        description="The column name to get the sentiment distribution for store column, columns are bu_key, area_manager, store_format, store_type, operations_controller, regional_manager, px, csr, dr, mag_type, cf_grouping, store_brand, competitor, region, area, province, territory, toh, district, city, operations_manager, district_manager, sic, soc, tech_life_type, operation_manager_tl, region_manager_tl, relocation, latitude, longitude, store_open_date, store_close_date, is_closed, store_key, store_english_name, store_local_name",
    ),
    filter_params: FilterRequest = Depends(get_filter_params),
    db: Session = Depends(get_db),
) -> List[StoreColumnSentimentDistributionResponse]:

    column_name_mapper = {
        "bu_key": Store.bu_key,
        "area_manager": Store.area_manager,
        "store_format": Store.store_format,
        "store_type": Store.store_type,
        "operations_controller": Store.operations_controller,
        "regional_manager": Store.regional_manager,
        "px": Store.px,
        "csr": Store.csr,
        "dr": Store.dr,
        "mag_type": Store.mag_type,
        "cf_grouping": Store.cf_grouping,
        "store_brand": Store.store_brand,
        "competitor": Store.competitor,
        "region": Store.region,
        "area": Store.area,
        "province": Store.province,
        "territory": Store.territory,
        "toh": Store.toh,
        "district": Store.district,
        "city": Store.city,
        "operations_manager": Store.operations_manager,
        "district_manager": Store.district_manager,
        "sic": Store.sic,
        "soc": Store.soc,
        "tech_life_type": Store.tech_life_type,
        "operation_manager_tl": Store.operation_manager_tl,
        "region_manager_tl": Store.region_manager_tl,
        "relocation": Store.relocation,
        "latitude": Store.latitude,
        "longitude": Store.longitude,
        "store_open_date": Store.store_open_date,
        "store_close_date": Store.store_close_date,
        "is_closed": Store.is_closed,
        "store_key": Store.store_key,
        "store_english_name": Store.store_name_english,
        "store_local_name": Store.store_name_local,
    }
    
    column_to_filter_key_mapper = {
        "bu_key": "bu_keys",
        "area_manager": "area_managers",
        "store_format": "store_formats",
        "store_type": "store_types",
        "operations_controller": "operations_controllers",
        "regional_manager": "regional_managers",
        "px": "px",
        "csr": "csr",
        "dr": "dr",
        "mag_type": "mag_types",
        "cf_grouping": "cf_groupings",
        "store_brand": "store_brands",
        "competitor": "competitors",
        "region": "regions",
        "area": "areas",
        "province": "provinces",
        "territory": "territories",
        "toh": "tohs",
        "district": "districts",
        "city": "cities",
        "operations_manager": "operations_managers",
        "district_manager": "district_managers",
        "sic": "sic",
        "soc": "soc",
        "tech_life_type": "tech_life_types",
        "operation_manager_tl": "operation_manager_tls",
        "region_manager_tl": "region_manager_tls",
        "relocation": "relocations",
        "latitude": "latitudes",
        "longitude": "longitudes",
        "store_open_date": "store_open_dates",
        "store_close_date": "store_close_dates",
        "is_closed": "is_closed",
        "store_key": "store_keys",
        "store_english_name": "store_english_names",
        "store_local_name": "store_local_names",
    }
    
    column_name = column_name_mapper.get(column)
    if column_name is None:
        raise HTTPException(status_code=404, detail="Column name not found")
    
    filter_key = column_to_filter_key_mapper.get(column)
    if filter_key is None:
        raise HTTPException(status_code=404, detail="Filter key not found for column")

    filter_dict = filter_params.model_dump()

    # Build base query with filters
    base_query, _joined_tables, _ = build_optimized_query(db, filter_dict)

    # Add store join if not already present
    if "store" not in _joined_tables:
        base_query = base_query.join(Store, Survey.store_key == Store.store_key)

    results_grouped_by_column_name = (
        base_query.with_entities(
            column_name.label("column_name"),
            func.count(func.distinct(Survey.id)).label("total_count"),
            func.count(
                func.distinct(
                    case((Survey.topic_sentiment == TopicSentiment.NEUTRAL, Survey.id))
                )
            ).label("neutral_count"),
            func.count(
                func.distinct(
                    case((Survey.topic_sentiment == TopicSentiment.POSITIVE, Survey.id))
                )
            ).label("positive_count"),
            func.count(
                func.distinct(
                    case((Survey.topic_sentiment == TopicSentiment.NEGATIVE, Survey.id))
                )
            ).label("negative_count"),
            func.count(
                func.distinct(
                    case((Survey.topic_sentiment == TopicSentiment.MIXED, Survey.id))
                )
            ).label("mixed_count"),
            func.avg(Survey.topic_sentiment_score).label("sentiment_score"),
        )
        .filter(column_name.isnot(None))
        .group_by(column_name)
        .all()
    )
    # Total count query: Apply ALL filters EXCEPT store column filters, group by store column
    total_count_query, total_count_joins, _ = build_optimized_query(
        db,
        filter_dict,
        exclude_filters=[filter_key],
    )
    # Add store column join if not already present
    if "store" not in total_count_joins:
        total_count_query = total_count_query.join(Store, Survey.store_key == Store.store_key)

    total_count_results = (
        total_count_query.with_entities(
            column_name.label("column_name"),
            func.count(func.distinct(Survey.id)).label("total_count"),
        )
        .filter(column_name.isnot(None))
        .group_by(column_name)
        .all()
    )

    # Stay within the active filter context when determining which values to return.
    all_values = [
        row.column_name
        for row in total_count_results
        if row.column_name is not None
    ]

    # Combine results
    # Create dictionaries keyed by column value
    sentiment_dict = {row.column_name: row for row in results_grouped_by_column_name}
    total_count_dict = {row.column_name: row.total_count for row in total_count_results}

    # Iterate through ALL possible column values
    column_sentiment_distribution = []
    for value in all_values:
        sentiment_row = sentiment_dict.get(value)
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

        total_count = total_count_dict.get(value, 0)

        column_sentiment_distribution.append(
            StoreColumnSentimentDistributionResponse(
                column_name=str(value),
                neutral_count=neutral_count,
                positive_count=positive_count,
                negative_count=negative_count,
                mixed_count=mixed_count,
                sentiment_score=sentiment_score,
                total_count_for_option=total_count,
            )
        )
    return column_sentiment_distribution
