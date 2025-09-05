from models.Survey import Survey
from models.Topic import Topic
from models.Store import Store
from models.Department import Department
from models.District import District
from models.Source import Source
from models.SurveyTopics import SurveyTopics
from models.SurveyKeywords import SurveyKeywords
from models.SurveyDepartments import SurveyDepartments
from models.Keyword import Keyword
from models.Region import Region
from sqlalchemy import and_
from sqlalchemy.orm import joinedload
from sqlalchemy.orm import Query
from sqlalchemy import func, case
from sqlalchemy.orm import Session
from typing import List
from fastapi import HTTPException, Query
from pydantic import BaseModel
from typing import Optional


def build_survey_filter_conditions(filter_dict):
    """Build filter conditions based on the filter dictionary"""
    conditions = []

    # Date range filter
    if filter_dict.get("from_date"):
        conditions.append(Survey.reported_at >= filter_dict["from_date"])

    if filter_dict.get("to_date"):
        conditions.append(Survey.reported_at <= filter_dict["to_date"])

    # Sentiment filter
    if filter_dict.get("sentiments"):
        conditions.append(Survey.sentiment.in_(filter_dict["sentiments"]))

    # id filter
    if filter_dict.get("ids"):
        conditions.append(Survey.id.in_(filter_dict["ids"]))

    return conditions


def build_topic_filter_conditions(filter_dict):
    """Build filter conditions for topic-related queries that include topic filtering"""
    conditions = []
    # Topic filter - this requires joining with SurveyTopics and Topic tables
    if filter_dict.get("topics"):
        conditions.append(Topic.topic.in_(filter_dict["topics"]))

    return conditions


def build_store_filter_conditions(filter_dict):
    """Build filter conditions for store-related queries that include store filtering"""
    conditions = []
    # Store filter
    if filter_dict.get("store_ids"):
        conditions.append(Store.id.in_(filter_dict["store_ids"]))

    if filter_dict.get("store_names"):
        conditions.append(Store.name.in_(filter_dict["store_names"]))

    # Active store filter, default is true
    conditions.append(Store.is_active == True)

    return conditions


def build_department_filter_conditions(filter_dict):
    """Build filter conditions for department-related queries that include department filtering"""
    conditions = []
    # Department filter
    if filter_dict.get("department_ids"):
        conditions.append(Department.id.in_(filter_dict["department_ids"]))

    if filter_dict.get("department_names"):
        conditions.append(Department.name.in_(filter_dict["department_names"]))

    return conditions


def build_district_filter_conditions(filter_dict):
    """Build filter conditions for district-related queries that include district filtering"""
    conditions = []
    # District filter
    if filter_dict.get("district_ids"):
        conditions.append(District.id.in_(filter_dict["district_ids"]))

    if filter_dict.get("district_names"):
        conditions.append(District.name.in_(filter_dict["district_names"]))

    return conditions


def build_source_filter_conditions(filter_dict):
    """Build filter conditions for source-related queries that include source filtering"""
    conditions = []
    # Source filter
    if filter_dict.get("source_ids"):
        conditions.append(Source.id.in_(filter_dict["source_ids"]))

    if filter_dict.get("source_names"):
        conditions.append(Source.name.in_(filter_dict["source_names"]))

    return conditions


def build_keyword_filter_conditions(filter_dict):
    """Build filter conditions for keyword-related queries that include keyword filtering"""
    conditions = []
    # Keyword filter - this requires joining with SurveyKeywords and Keyword tables
    if filter_dict.get("keywords"):
        conditions.append(Keyword.keyword.in_(filter_dict["keywords"]))

    return conditions


def build_survey_query(query: Query, filter_dict) -> Query:
    """Build a complete survey query with appropriate joins and optimizations based on filter conditions"""
    # Build all filter conditions
    survey_conditions = build_survey_filter_conditions(filter_dict)
    store_conditions = build_store_filter_conditions(filter_dict)
    department_conditions = build_department_filter_conditions(filter_dict)
    district_conditions = build_district_filter_conditions(filter_dict)
    source_conditions = build_source_filter_conditions(filter_dict)
    topic_conditions = build_topic_filter_conditions(filter_dict)
    region_conditions = build_region_filter_conditions(filter_dict)
    keyword_conditions = build_keyword_filter_conditions(filter_dict)
    # Add joins only when filtering is needed to avoid cartesian products
    joins_added = set()

    # Join Store if store filters are applied or if we need it for district/source/region joins
    if (
        store_conditions
        or district_conditions
        or source_conditions
        or region_conditions
    ):
        query = query.join(Store, Survey.store_id == Store.id)
        joins_added.add("store")

    # Join Department if department filters are applied
    if department_conditions:
        query = query.join(SurveyDepartments, Survey.id == SurveyDepartments.survey_id)
        query = query.join(Department, SurveyDepartments.department_id == Department.id)
        joins_added.add("department")

    # Join District through Store if district filters are applied
    if district_conditions:
        query = query.join(District, Store.district_id == District.id)
        joins_added.add("district")

    # Join Source through Store if source filters are applied
    if source_conditions:
        query = query.join(Source, Store.source_id == Source.id)
        joins_added.add("source")

    # Join Topic through SurveyTopics if topic filters are applied
    if topic_conditions:
        query = query.join(SurveyTopics, Survey.id == SurveyTopics.survey_id)
        query = query.join(Topic, SurveyTopics.topic_id == Topic.id)
        joins_added.add("topic")

    # Join Region through Store if region filters are applied
    if region_conditions and "store" in joins_added:
        query = query.join(Region, Store.region_id == Region.id)
        joins_added.add("region")

    # Join Keyword through SurveyKeywords if keyword filters are applied
    if keyword_conditions:
        query = query.join(SurveyKeywords, Survey.id == SurveyKeywords.survey_id)
        query = query.join(Keyword, SurveyKeywords.keyword_id == Keyword.id)
        joins_added.add("keyword")

    # Optimize loading of relationships
    query = query.options(
        joinedload(Survey.survey_topics).joinedload(SurveyTopics.topic),
        joinedload(Survey.survey_keywords).joinedload(SurveyKeywords.keyword),
        joinedload(Survey.store),
        joinedload(Survey.survey_departments).joinedload(SurveyDepartments.department),
        joinedload(Survey.district),
        joinedload(Survey.source),
        joinedload(Survey.region),
    )

    # Apply the filter conditions
    filter_conditions = merge_filter_conditions(
        survey_conditions,
        store_conditions,
        department_conditions,
        district_conditions,
        source_conditions,
        topic_conditions,
        region_conditions,
        keyword_conditions,
    )
    if filter_conditions is not None:
        query = query.filter(filter_conditions)

    return query


def merge_filter_conditions(*condition_lists):
    """Merge filter conditions into a single condition"""
    # Flatten all condition lists and filter out empty ones
    all_conditions = []
    for condition_list in condition_lists:
        if condition_list:  # Only add non-empty lists
            all_conditions.extend(condition_list)

    # Return None if no conditions, otherwise return and_() with all conditions
    if not all_conditions:
        return None

    return and_(*all_conditions)


def build_region_filter_conditions(filter_dict):
    """Build filter conditions for region-related queries that include region filtering"""
    conditions = []
    # Region filter
    if filter_dict.get("region_ids"):
        conditions.append(Region.id.in_(filter_dict["region_ids"]))

    if filter_dict.get("region_names"):
        conditions.append(Region.name.in_(filter_dict["region_names"]))

    return conditions


def build_optimized_query(
    db: Session, filter_dict: dict, exclude_filters: List[str] = None
):
    """Build an optimized query with minimal joins and filtering"""
    exclude_filters = exclude_filters or []

    # Create a copy of filter_dict without excluded filters
    working_filter = {k: v for k, v in filter_dict.items() if k not in exclude_filters}

    # Build filter conditions
    survey_conditions = build_survey_filter_conditions(working_filter)
    store_conditions = build_store_filter_conditions(working_filter)
    department_conditions = build_department_filter_conditions(working_filter)
    district_conditions = build_district_filter_conditions(working_filter)
    source_conditions = build_source_filter_conditions(working_filter)
    topic_conditions = build_topic_filter_conditions(working_filter)
    keyword_conditions = build_keyword_filter_conditions(working_filter)
    region_conditions = build_region_filter_conditions(working_filter)

    # Start with base query
    query = db.query(Survey)

    # Add joins only when needed - track what we've joined to avoid duplicates
    joined_tables = set()

    # Join Store if store filters are applied or if we need it for district/source/region joins
    if (
        store_conditions
        or district_conditions
        or source_conditions
        or region_conditions
    ):
        query = query.join(Store, Survey.store_id == Store.id)
        joined_tables.add("store")

    if department_conditions:
        query = query.join(SurveyDepartments, Survey.id == SurveyDepartments.survey_id)
        query = query.join(Department, SurveyDepartments.department_id == Department.id)
        joined_tables.add("department")

    if district_conditions and "store" in joined_tables:
        query = query.join(District, Store.district_id == District.id)
        joined_tables.add("district")

    if source_conditions and "store" in joined_tables:
        query = query.join(Source, Store.source_id == Source.id)
        joined_tables.add("source")

    if topic_conditions:
        query = query.join(SurveyTopics, Survey.id == SurveyTopics.survey_id)
        query = query.join(Topic, SurveyTopics.topic_id == Topic.id)
        joined_tables.add("topic")

    if region_conditions and "store" in joined_tables:
        query = query.join(Region, Store.region_id == Region.id)
        joined_tables.add("region")

    if keyword_conditions:
        query = query.join(SurveyKeywords, Survey.id == SurveyKeywords.survey_id)
        query = query.join(Keyword, SurveyKeywords.keyword_id == Keyword.id)
        joined_tables.add("keyword")

    # Apply filters
    filter_conditions = merge_filter_conditions(
        survey_conditions,
        store_conditions,
        department_conditions,
        district_conditions,
        source_conditions,
        topic_conditions,
        region_conditions,
        keyword_conditions,
    )

    if filter_conditions is not None:
        query = query.filter(filter_conditions)

    return query, joined_tables


def build_Survey_sentiment_aggregation_query(base_query, *group_by_fields):
    """Build a sentiment aggregation query with variable group by fields"""
    return base_query.with_entities(
        *group_by_fields,
        func.count(case((Survey.sentiment == "neutral", Survey.id))).label(
            "neutral_count"
        ),
        func.count(case((Survey.sentiment == "positive", Survey.id))).label(
            "positive_count"
        ),
        func.count(case((Survey.sentiment == "negative", Survey.id))).label(
            "negative_count"
        ),
    ).group_by(*group_by_fields)


def build_SurveyKeywords_sentiment_aggregation_query(base_query, *group_by_fields):
    """Build a sentiment aggregation query with variable group by fields"""
    return base_query.with_entities(
        *group_by_fields,
        func.count(case((SurveyKeywords.sentiment == "neutral", Survey.id))).label(
            "neutral_count"
        ),
        func.count(case((SurveyKeywords.sentiment == "positive", Survey.id))).label(
            "positive_count"
        ),
        func.count(case((SurveyKeywords.sentiment == "negative", Survey.id))).label(
            "negative_count"
        ),
    ).group_by(*group_by_fields)


def build_SurveyDepartments_sentiment_aggregation_query(base_query, *group_by_fields):
    """Build a sentiment aggregation query with variable group by fields"""
    return base_query.with_entities(
        *group_by_fields,
        func.count(case((SurveyDepartments.sentiment == "neutral", Survey.id))).label(
            "neutral_count"
        ),
        func.count(case((SurveyDepartments.sentiment == "positive", Survey.id))).label(
            "positive_count"
        ),
        func.count(case((SurveyDepartments.sentiment == "negative", Survey.id))).label(
            "negative_count"
        ),
    ).group_by(*group_by_fields)


def build_SurveyTopics_sentiment_aggregation_query(base_query, *group_by_fields):
    """Build a sentiment aggregation query with variable group by fields"""
    return base_query.with_entities(
        *group_by_fields,
        func.count(case((SurveyTopics.sentiment == "neutral", Survey.id))).label(
            "neutral_count"
        ),
        func.count(case((SurveyTopics.sentiment == "positive", Survey.id))).label(
            "positive_count"
        ),
        func.count(case((SurveyTopics.sentiment == "negative", Survey.id))).label(
            "negative_count"
        ),
    ).group_by(*group_by_fields)


class FilterRequest(BaseModel):
    store_ids: List[int] = []
    store_names: List[str] = []
    department_ids: List[int] = []
    department_names: List[str] = []
    district_ids: List[int] = []
    district_names: List[str] = []
    region_ids: List[int] = []
    region_names: List[str] = []
    source_ids: List[int] = []
    source_names: List[str] = []
    topics: List[str] = []
    keywords: List[str] = []
    from_date: Optional[str] = ""
    to_date: Optional[str] = ""
    sentiments: List[str] = []


def get_filter_params(
    store_ids: List[int] = Query(
        default=[],
        description="The store ids to filter by, separated by |",
    ),
    store_names: List[str] = Query(
        default=[],
        description="The store names to filter by",
    ),
    department_ids: List[int] = Query(
        default=[],
        description="The department ids to filter by",
    ),
    department_names: List[str] = Query(
        default=[],
        description="The department names to filter by",
    ),
    district_ids: List[int] = Query(
        default=[],
        description="The district ids to filter by",
    ),
    district_names: List[str] = Query(
        default=[],
        description="The district names to filter by",
    ),
    region_ids: List[int] = Query(
        default=[],
        description="The region ids to filter by",
    ),
    region_names: List[str] = Query(
        default=[],
        description="The region names to filter by",
    ),
    source_ids: List[int] = Query(
        default=[],
        description="The source ids to filter by",
    ),
    source_names: List[str] = Query(
        default=[],
        description="The source names to filter by",
    ),
    topics: List[str] = Query(
        default=[],
        description="The topics to filter by",
    ),
    keywords: List[str] = Query(
        default=[],
        description="The keywords to filter by",
    ),
    from_date: str = Query(
        default="",
        description="The start date to filter by, in the format YYYY-MM-DD",
    ),
    to_date: str = Query(
        default="",
        description="The end date to filter by, in the format YYYY-MM-DD",
    ),
    sentiments: List[str] = Query(
        default=[],
        description="The sentiments to filter by",
    ),
) -> FilterRequest:
    # store_ids and store_names cannot be used together
    if store_ids and store_names:
        raise HTTPException(
            status_code=400,
            detail="store_ids and store_names cannot be used together",
        )
    # department_ids and department_names cannot be used together
    if department_ids and department_names:
        raise HTTPException(
            status_code=400,
            detail="department_ids and department_names cannot be used together",
        )
    # district_ids and district_names cannot be used together
    if district_ids and district_names:
        raise HTTPException(
            status_code=400,
            detail="district_ids and district_names cannot be used together",
        )
    # region_ids and region_names cannot be used together
    if region_ids and region_names:
        raise HTTPException(
            status_code=400,
            detail="region_ids and region_names cannot be used together",
        )
    # source_ids and source_names cannot be used together
    if source_ids and source_names:
        raise HTTPException(
            status_code=400,
            detail="source_ids and source_names cannot be used together",
        )

    return FilterRequest(
        store_ids=store_ids,
        store_names=store_names,
        department_ids=department_ids,
        department_names=department_names,
        district_ids=district_ids,
        district_names=district_names,
        region_ids=region_ids,
        region_names=region_names,
        source_ids=source_ids,
        source_names=source_names,
        topics=topics,
        keywords=keywords,
        from_date=from_date,
        to_date=to_date,
        sentiments=[
            sentiment.lower() for sentiment in sentiments # Convert into list of lowercase strings
        ],  
    )
