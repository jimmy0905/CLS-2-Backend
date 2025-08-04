from models.Survey import Survey
from models.Topic import Topic
from models.Store import Store
from models.Department import Department
from models.District import District
from models.Source import Source
from models.SurveyTopics import SurveyTopics
from models.SurveyKeywords import SurveyKeywords
from models.Region import Region
from sqlalchemy import and_
from sqlalchemy.orm import joinedload
from sqlalchemy.orm import Query
from sqlalchemy import func, case
from sqlalchemy.orm import Session
from typing import List


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

    # Add joins only when filtering is needed to avoid cartesian products
    joins_added = set()

    # Join Store if store filters are applied or if we need it for district/source/region joins
    if store_conditions or district_conditions or source_conditions or region_conditions:
        query = query.join(Store, Survey.store_id == Store.id)
        joins_added.add("store")

    # Join Department if department filters are applied
    if department_conditions:
        query = query.join(Department, Survey.department_id == Department.id)
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

    # Optimize loading of relationships
    query = query.options(
        joinedload(Survey.survey_topics).joinedload(SurveyTopics.topic),
        joinedload(Survey.survey_keywords).joinedload(SurveyKeywords.keyword),
        joinedload(Survey.store),
        joinedload(Survey.department),
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
    region_conditions = build_region_filter_conditions(working_filter)

    # Start with base query
    query = db.query(Survey)

    # Add joins only when needed - track what we've joined to avoid duplicates
    joined_tables = set()

    # Join Store if store filters are applied or if we need it for district/source/region joins
    if store_conditions or district_conditions or source_conditions or region_conditions:
        query = query.join(Store, Survey.store_id == Store.id)
        joined_tables.add("store")

    if department_conditions:
        query = query.join(Department, Survey.department_id == Department.id)
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

    # Apply filters
    filter_conditions = merge_filter_conditions(
        survey_conditions,
        store_conditions,
        department_conditions,
        district_conditions,
        source_conditions,
        topic_conditions,
        region_conditions,
    )

    if filter_conditions is not None:
        query = query.filter(filter_conditions)

    return query, joined_tables


def build_sentiment_aggregation_query(base_query, group_by_field):
    """Build a sentiment aggregation query"""
    return base_query.with_entities(
        group_by_field,
        func.count(case((Survey.sentiment == "Neutral", Survey.id))).label(
            "neutral_count"
        ),
        func.count(case((Survey.sentiment == "Positive", Survey.id))).label(
            "positive_count"
        ),
        func.count(case((Survey.sentiment == "Negative", Survey.id))).label(
            "negative_count"
        ),
    ).group_by(group_by_field)
