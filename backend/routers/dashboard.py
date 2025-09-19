from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, or_, distinct, case, and_
from models.Survey import Survey
from models.Topic import Topic
from models.Keyword import Keyword
from models.SurveyKeywords import SurveyKeywords
from models.SurveyDepartments import SurveyDepartments
from models.Store import Store
from models.Department import Department
from models.District import District
from models.Region import Region
from models.Source import Source
from models.SurveyTopics import SurveyTopics
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
    sentiment_query, sentiment_joins = build_optimized_query(db, filter_dict)

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
    total_query, total_joins = build_optimized_query(
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
    base_query, joined_tables = build_optimized_query(db, filter_dict)

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


class DistrictDistributionResponse(BaseModel):
    district: str
    neutral_count: int
    positive_count: int
    negative_count: int
    total_count_for_option: int


@router.get("/district-distribution")
async def get_district_distribution(
    filter_params: FilterRequest = Depends(get_filter_params),
    db: Session = Depends(get_db),
) -> List[DistrictDistributionResponse]:
    filter_dict = filter_params.model_dump()

    # Single query to get sentiment counts with district filter
    sentiment_query, sentiment_joins = build_optimized_query(db, filter_dict)

    # Add necessary joins if not already present
    if "store" not in sentiment_joins:
        sentiment_query = sentiment_query.join(Store, Survey.store_id == Store.id)
    if "district" not in sentiment_joins:
        sentiment_query = sentiment_query.join(
            District, Store.district_id == District.id
        )

    sentiment_results = build_Survey_sentiment_aggregation_query(
        sentiment_query, District.name.label("district")
    ).all()

    # Total count query: Apply ALL filters EXCEPT district filters, but group by district
    total_query, total_joins = build_optimized_query(
        db, filter_dict, exclude_filters=["district_ids", "district_names"]
    )

    # Always add necessary joins for total counts since we need to group by district
    if "store" not in total_joins:
        total_query = total_query.join(Store, Survey.store_id == Store.id)
    if "district" not in total_joins:
        total_query = total_query.join(District, Store.district_id == District.id)

    total_results = (
        total_query.with_entities(
            District.name.label("district"), func.count(Survey.id).label("total_count")
        )
        .group_by(District.id, District.name)
        .all()
    )

    # Combine results
    sentiment_dict = {row.district: row for row in sentiment_results}
    total_dict = {row.district: row.total_count for row in total_results}

    district_distribution = []
    for district_name in set(list(sentiment_dict.keys()) + list(total_dict.keys())):
        sentiment_row = sentiment_dict.get(district_name)
        total_count = total_dict.get(district_name, 0)

        district_distribution.append(
            DistrictDistributionResponse(
                district=district_name,
                neutral_count=sentiment_row.neutral_count if sentiment_row else 0,
                positive_count=sentiment_row.positive_count if sentiment_row else 0,
                negative_count=sentiment_row.negative_count if sentiment_row else 0,
                total_count_for_option=total_count,
            )
        )

    return district_distribution


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
    sentiment_query, sentiment_joins = build_optimized_query(db, filter_dict)

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
    total_query, total_joins = build_optimized_query(
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
    sentiment_query, _ = build_optimized_query(db, filter_dict)

    sentiment_results = (
        build_Survey_sentiment_aggregation_query(
            sentiment_query, func.date(Survey.reported_at).label("date")
        )
        .group_by(func.date(Survey.reported_at))
        .order_by(func.date(Survey.reported_at))
        .all()
    )
    total_query, _ = build_optimized_query(
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


class SourceResponse(BaseModel):
    id: int
    source: str
    neutral_count: int
    positive_count: int
    negative_count: int
    total_count_for_option: int


@router.get("/source-distribution")
async def get_source_distribution(
    filter_params: FilterRequest = Depends(get_filter_params),
    db: Session = Depends(get_db),
) -> List[SourceResponse]:
    filter_dict = filter_params.model_dump()

    # Single query to get sentiment counts with source filter
    sentiment_query, sentiment_joins = build_optimized_query(db, filter_dict)

    # Add necessary joins if not already present
    if "store" not in sentiment_joins:
        sentiment_query = sentiment_query.join(Store, Survey.store_id == Store.id)
    if "source" not in sentiment_joins:
        sentiment_query = sentiment_query.join(Source, Store.source_id == Source.id)

    sentiment_results = build_Survey_sentiment_aggregation_query(
        sentiment_query, Source.id.label("source_id"), Source.name.label("source")
    ).all()

    # Total count query: Apply ALL filters EXCEPT source filters, but group by source
    total_query, total_joins = build_optimized_query(
        db, filter_dict, exclude_filters=["source_ids", "source_names"]
    )

    # Always add necessary joins for total counts since we need to group by source
    if "store" not in total_joins:
        total_query = total_query.join(Store, Survey.store_id == Store.id)
    if "source" not in total_joins:
        total_query = total_query.join(Source, Store.source_id == Source.id)

    total_results = (
        total_query.with_entities(
            Source.id.label("source_id"),
            Source.name.label("source"),
            func.count(Survey.id).label("total_count"),
        )
        .group_by(Source.id, Source.name)
        .all()
    )

    # Combine results
    sentiment_dict = {row.source_id: row for row in sentiment_results}
    total_dict = {row.source_id: row.total_count for row in total_results}

    source_distribution = []
    for source_id in set(list(sentiment_dict.keys()) + list(total_dict.keys())):
        sentiment_row = sentiment_dict.get(source_id)
        total_count = total_dict.get(source_id, 0)
        # Get source name from either sentiment or total results
        source_name = (
            sentiment_row.source
            if sentiment_row
            else next(
                (row.source for row in total_results if row.source_id == source_id), ""
            )
        )

        source_distribution.append(
            SourceResponse(
                id=source_id,
                source=source_name,
                neutral_count=sentiment_row.neutral_count if sentiment_row else 0,
                positive_count=sentiment_row.positive_count if sentiment_row else 0,
                negative_count=sentiment_row.negative_count if sentiment_row else 0,
                total_count_for_option=total_count,
            )
        )

    return source_distribution


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
    sentiment_query, sentiment_joins = build_optimized_query(db, filter_dict)

    # Add store join if not already present
    if "store" not in sentiment_joins:
        sentiment_query = sentiment_query.join(Store, Survey.store_id == Store.id)

    sentiment_results = build_Survey_sentiment_aggregation_query(
        sentiment_query, Store.id.label("store_id"), Store.name.label("store_name")
    ).all()

    # Total count query: Apply ALL filters EXCEPT store filters, but group by store
    total_query, total_joins = build_optimized_query(
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


class RegionDistributionResponse(BaseModel):
    region: str
    neutral_count: int
    positive_count: int
    negative_count: int
    total_count_for_option: int


@router.get("/region-distribution")
async def get_region_distribution(
    filter_params: FilterRequest = Depends(get_filter_params),
    db: Session = Depends(get_db),
) -> List[RegionDistributionResponse]:
    filter_dict = filter_params.model_dump()

    # Single query to get sentiment counts with district filter
    sentiment_query, sentiment_joins = build_optimized_query(db, filter_dict)

    # Add necessary joins if not already present
    if "store" not in sentiment_joins:
        sentiment_query = sentiment_query.join(Store, Survey.store_id == Store.id)
    if "region" not in sentiment_joins:
        sentiment_query = sentiment_query.join(Region, Store.region_id == Region.id)

    sentiment_results = build_Survey_sentiment_aggregation_query(
        sentiment_query, Region.name.label("region")
    ).all()

    # Total count query: Apply ALL filters EXCEPT district filters, but group by district
    total_query, total_joins = build_optimized_query(
        db, filter_dict, exclude_filters=["region_ids", "region_names"]
    )

    # Always add necessary joins for total counts since we need to group by district
    if "store" not in total_joins:
        total_query = total_query.join(Store, Survey.store_id == Store.id)
    if "region" not in total_joins:
        total_query = total_query.join(Region, Store.region_id == Region.id)

    total_results = (
        total_query.with_entities(
            Region.name.label("region"), func.count(Survey.id).label("total_count")
        )
        .group_by(Region.id, Region.name)
        .all()
    )

    # Combine results
    sentiment_dict = {row.region: row for row in sentiment_results}
    total_dict = {row.region: row.total_count for row in total_results}

    region_distribution = []
    for region_name in set(list(sentiment_dict.keys()) + list(total_dict.keys())):
        sentiment_row = sentiment_dict.get(region_name)
        total_count = total_dict.get(region_name, 0)

        region_distribution.append(
            RegionDistributionResponse(
                region=region_name,
                neutral_count=sentiment_row.neutral_count if sentiment_row else 0,
                positive_count=sentiment_row.positive_count if sentiment_row else 0,
                negative_count=sentiment_row.negative_count if sentiment_row else 0,
                total_count_for_option=total_count,
            )
        )

    return region_distribution
