from models.Survey import Survey
from models.Topic import Topic
from models.Store import Store
from models.Department import Department
from models.Hierarchy import Hierarchy
from models.SurveyTopics import SurveyTopics
from models.SurveyKeywords import SurveyKeywords
from models.SurveyDepartments import SurveyDepartments
from models.Keyword import Keyword
from models.Channel import Channel
from models.DeliveryService import DeliveryService
from models.enum.Sentiment import Sentiment, TopicSentiment
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

    # Add is_deleted check
    conditions.append(Survey.is_deleted == False)

    # Date range filter
    if filter_dict.get("from_date"):
        conditions.append(Survey.reported_at >= filter_dict["from_date"])

    if filter_dict.get("to_date"):
        conditions.append(Survey.reported_at <= filter_dict["to_date"])

    # Sentiment filter
    if filter_dict.get("sentiments"):
        conditions.append(Survey.sentiment.in_(filter_dict["sentiments"]))

    # Topic sentiment filter
    if filter_dict.get("topic_sentiments"):
        conditions.append(Survey.topic_sentiment.in_(filter_dict["topic_sentiments"]))

    # Topic sentiment score range filters
    if filter_dict.get("min_topic_sentiment_score") is not None:
        conditions.append(Survey.topic_sentiment_score >= filter_dict["min_topic_sentiment_score"])

    if filter_dict.get("max_topic_sentiment_score") is not None:
        conditions.append(Survey.topic_sentiment_score <= filter_dict["max_topic_sentiment_score"])

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


def build_hierarchy_level_1_filter_conditions(filter_dict, hierarchy_alias=None):
    """Build filter conditions for hierarchy level 1"""
    conditions = []
    if hierarchy_alias is None:
        hierarchy_alias = Hierarchy
    if filter_dict.get("hierarchy_level_1_ids"):
        conditions.append(hierarchy_alias.id.in_(filter_dict["hierarchy_level_1_ids"]))
    if filter_dict.get("hierarchy_level_1_names"):
        conditions.append(hierarchy_alias.name.in_(filter_dict["hierarchy_level_1_names"]))
    return conditions


def build_hierarchy_level_2_filter_conditions(filter_dict, hierarchy_alias=None):
    """Build filter conditions for hierarchy level 2"""
    conditions = []
    if hierarchy_alias is None:
        hierarchy_alias = Hierarchy
    if filter_dict.get("hierarchy_level_2_ids"):
        conditions.append(hierarchy_alias.id.in_(filter_dict["hierarchy_level_2_ids"]))
    if filter_dict.get("hierarchy_level_2_names"):
        conditions.append(hierarchy_alias.name.in_(filter_dict["hierarchy_level_2_names"]))
    return conditions


def build_hierarchy_level_3_filter_conditions(filter_dict, hierarchy_alias=None):
    """Build filter conditions for hierarchy level 3"""
    conditions = []
    if hierarchy_alias is None:
        hierarchy_alias = Hierarchy
    if filter_dict.get("hierarchy_level_3_ids"):
        conditions.append(hierarchy_alias.id.in_(filter_dict["hierarchy_level_3_ids"]))
    if filter_dict.get("hierarchy_level_3_names"):
        conditions.append(hierarchy_alias.name.in_(filter_dict["hierarchy_level_3_names"]))
    return conditions


def build_hierarchy_level_4_filter_conditions(filter_dict, hierarchy_alias=None):
    """Build filter conditions for hierarchy level 4"""
    conditions = []
    if hierarchy_alias is None:
        hierarchy_alias = Hierarchy
    if filter_dict.get("hierarchy_level_4_ids"):
        conditions.append(hierarchy_alias.id.in_(filter_dict["hierarchy_level_4_ids"]))
    if filter_dict.get("hierarchy_level_4_names"):
        conditions.append(hierarchy_alias.name.in_(filter_dict["hierarchy_level_4_names"]))
    return conditions


def build_hierarchy_level_5_filter_conditions(filter_dict, hierarchy_alias=None):
    """Build filter conditions for hierarchy level 5"""
    conditions = []
    if hierarchy_alias is None:
        hierarchy_alias = Hierarchy
    if filter_dict.get("hierarchy_level_5_ids"):
        conditions.append(hierarchy_alias.id.in_(filter_dict["hierarchy_level_5_ids"]))
    if filter_dict.get("hierarchy_level_5_names"):
        conditions.append(hierarchy_alias.name.in_(filter_dict["hierarchy_level_5_names"]))
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
    # Build all filter conditions (for non-hierarchy filters first)
    survey_conditions = build_survey_filter_conditions(filter_dict)
    store_conditions = build_store_filter_conditions(filter_dict)
    department_conditions = build_department_filter_conditions(filter_dict)
    topic_conditions = build_topic_filter_conditions(filter_dict)
    keyword_conditions = build_keyword_filter_conditions(filter_dict)
    channel_conditions = build_channel_filter_conditions(filter_dict)
    delivery_service_conditions = build_delivery_service_filter_conditions(filter_dict)
    
    # Check if hierarchy conditions exist before creating joins
    has_hierarchy_level_1 = bool(filter_dict.get("hierarchy_level_1_ids") or filter_dict.get("hierarchy_level_1_names"))
    has_hierarchy_level_2 = bool(filter_dict.get("hierarchy_level_2_ids") or filter_dict.get("hierarchy_level_2_names"))
    has_hierarchy_level_3 = bool(filter_dict.get("hierarchy_level_3_ids") or filter_dict.get("hierarchy_level_3_names"))
    has_hierarchy_level_4 = bool(filter_dict.get("hierarchy_level_4_ids") or filter_dict.get("hierarchy_level_4_names"))
    has_hierarchy_level_5 = bool(filter_dict.get("hierarchy_level_5_ids") or filter_dict.get("hierarchy_level_5_names"))
    
    # Add joins only when filtering is needed to avoid cartesian products
    joins_added = set()

    # Join Store if store filters are applied or if we need it for hierarchy joins
    if (
        store_conditions
        or has_hierarchy_level_1
        or has_hierarchy_level_2
        or has_hierarchy_level_3
        or has_hierarchy_level_4
        or has_hierarchy_level_5
    ):
        query = query.join(Store, Survey.store_id == Store.id)
        joins_added.add("store")

    # Join Department if department filters are applied
    if department_conditions:
        query = query.join(SurveyDepartments, Survey.id == SurveyDepartments.survey_id)
        query = query.join(Department, SurveyDepartments.department_id == Department.id)
        joins_added.add("department")

    # Join Hierarchy levels through Store if hierarchy filters are applied
    # Each hierarchy level needs to be aliased to allow multiple joins
    from sqlalchemy.orm import aliased
    
    hierarchy_level_1_conditions = []
    hierarchy_level_2_conditions = []
    hierarchy_level_3_conditions = []
    hierarchy_level_4_conditions = []
    hierarchy_level_5_conditions = []
    
    if has_hierarchy_level_1 and "store" in joins_added:
        hierarchy_level_1_alias = aliased(Hierarchy)
        query = query.join(hierarchy_level_1_alias, Store.hierarchy_level_1_id == hierarchy_level_1_alias.id)
        hierarchy_level_1_conditions = build_hierarchy_level_1_filter_conditions(filter_dict, hierarchy_level_1_alias)
        joins_added.add("hierarchy_level_1")
    
    if has_hierarchy_level_2 and "store" in joins_added:
        hierarchy_level_2_alias = aliased(Hierarchy)
        query = query.join(hierarchy_level_2_alias, Store.hierarchy_level_2_id == hierarchy_level_2_alias.id)
        hierarchy_level_2_conditions = build_hierarchy_level_2_filter_conditions(filter_dict, hierarchy_level_2_alias)
        joins_added.add("hierarchy_level_2")
    
    if has_hierarchy_level_3 and "store" in joins_added:
        hierarchy_level_3_alias = aliased(Hierarchy)
        query = query.join(hierarchy_level_3_alias, Store.hierarchy_level_3_id == hierarchy_level_3_alias.id)
        hierarchy_level_3_conditions = build_hierarchy_level_3_filter_conditions(filter_dict, hierarchy_level_3_alias)
        joins_added.add("hierarchy_level_3")
    
    if has_hierarchy_level_4 and "store" in joins_added:
        hierarchy_level_4_alias = aliased(Hierarchy)
        query = query.join(hierarchy_level_4_alias, Store.hierarchy_level_4_id == hierarchy_level_4_alias.id)
        hierarchy_level_4_conditions = build_hierarchy_level_4_filter_conditions(filter_dict, hierarchy_level_4_alias)
        joins_added.add("hierarchy_level_4")
    
    if has_hierarchy_level_5 and "store" in joins_added:
        hierarchy_level_5_alias = aliased(Hierarchy)
        query = query.join(hierarchy_level_5_alias, Store.hierarchy_level_5_id == hierarchy_level_5_alias.id)
        hierarchy_level_5_conditions = build_hierarchy_level_5_filter_conditions(filter_dict, hierarchy_level_5_alias)
        joins_added.add("hierarchy_level_5")

    # Join Topic through SurveyTopics if topic filters are applied
    if topic_conditions:
        query = query.join(SurveyTopics, Survey.id == SurveyTopics.survey_id)
        query = query.join(Topic, SurveyTopics.topic_id == Topic.id)
        joins_added.add("topic")

    # Join Keyword through SurveyKeywords if keyword filters are applied
    if keyword_conditions:
        query = query.join(SurveyKeywords, Survey.id == SurveyKeywords.survey_id)
        query = query.join(Keyword, SurveyKeywords.keyword_id == Keyword.id)
        joins_added.add("keyword")

    # Join Channel through Survey if channel filters are applied
    if channel_conditions:
        query = query.join(Channel, Survey.channel_id == Channel.id)
        joins_added.add("channel")

    # Join DeliveryService through Survey if delivery service filters are applied
    if delivery_service_conditions:
        query = query.join(DeliveryService, Survey.delivery_service_id == DeliveryService.id)
        joins_added.add("delivery_service")

    # Apply the filter conditions
    filter_conditions = merge_filter_conditions(
        survey_conditions,
        store_conditions,
        department_conditions,
        hierarchy_level_1_conditions,
        hierarchy_level_2_conditions,
        hierarchy_level_3_conditions,
        hierarchy_level_4_conditions,
        hierarchy_level_5_conditions,
        topic_conditions,
        keyword_conditions,
        channel_conditions,
        delivery_service_conditions,
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


def build_channel_filter_conditions(filter_dict):
    """Build filter conditions for channel-related queries that include channel filtering"""
    conditions = []
    # Channel filter
    if filter_dict.get("channel_ids"):
        conditions.append(Channel.id.in_(filter_dict["channel_ids"]))

    if filter_dict.get("channel_names"):
        conditions.append(Channel.name.in_(filter_dict["channel_names"]))

    return conditions


def build_delivery_service_filter_conditions(filter_dict):
    """Build filter conditions for delivery service-related queries that include delivery service filtering"""
    conditions = []
    # Delivery service filter
    if filter_dict.get("delivery_service_ids"):
        conditions.append(DeliveryService.id.in_(filter_dict["delivery_service_ids"]))

    if filter_dict.get("delivery_service_names"):
        conditions.append(DeliveryService.name.in_(filter_dict["delivery_service_names"]))

    return conditions


def build_optimized_query(
    db: Session, filter_dict: dict, exclude_filters: List[str] = None
):
    """Build an optimized query with minimal joins and filtering"""
    exclude_filters = exclude_filters or []

    # Create a copy of filter_dict without excluded filters
    working_filter = {k: v for k, v in filter_dict.items() if k not in exclude_filters}

    # Build filter conditions (for non-hierarchy filters first)
    survey_conditions = build_survey_filter_conditions(working_filter)
    store_conditions = build_store_filter_conditions(working_filter)
    department_conditions = build_department_filter_conditions(working_filter)
    topic_conditions = build_topic_filter_conditions(working_filter)
    keyword_conditions = build_keyword_filter_conditions(working_filter)
    channel_conditions = build_channel_filter_conditions(working_filter)
    delivery_service_conditions = build_delivery_service_filter_conditions(working_filter)
    
    # Check if hierarchy conditions exist before creating joins
    has_hierarchy_level_1 = bool(working_filter.get("hierarchy_level_1_ids") or working_filter.get("hierarchy_level_1_names"))
    has_hierarchy_level_2 = bool(working_filter.get("hierarchy_level_2_ids") or working_filter.get("hierarchy_level_2_names"))
    has_hierarchy_level_3 = bool(working_filter.get("hierarchy_level_3_ids") or working_filter.get("hierarchy_level_3_names"))
    has_hierarchy_level_4 = bool(working_filter.get("hierarchy_level_4_ids") or working_filter.get("hierarchy_level_4_names"))
    has_hierarchy_level_5 = bool(working_filter.get("hierarchy_level_5_ids") or working_filter.get("hierarchy_level_5_names"))

    # Start with base query
    query = db.query(Survey)

    # Add joins only when needed - track what we've joined to avoid duplicates
    joined_tables = set()

    # Join Store if store filters are applied or if we need it for hierarchy joins
    if (
        store_conditions
        or has_hierarchy_level_1
        or has_hierarchy_level_2
        or has_hierarchy_level_3
        or has_hierarchy_level_4
        or has_hierarchy_level_5
    ):
        query = query.join(Store, Survey.store_id == Store.id)
        joined_tables.add("store")

    if department_conditions:
        query = query.join(SurveyDepartments, Survey.id == SurveyDepartments.survey_id)
        query = query.join(Department, SurveyDepartments.department_id == Department.id)
        joined_tables.add("department")

    # Join Hierarchy levels through Store if hierarchy filters are applied
    # Each hierarchy level needs to be aliased to allow multiple joins
    from sqlalchemy.orm import aliased
    
    hierarchy_aliases = {}
    hierarchy_level_1_conditions = []
    hierarchy_level_2_conditions = []
    hierarchy_level_3_conditions = []
    hierarchy_level_4_conditions = []
    hierarchy_level_5_conditions = []
    
    if has_hierarchy_level_1 and "store" in joined_tables:
        hierarchy_level_1_alias = aliased(Hierarchy)
        query = query.join(hierarchy_level_1_alias, Store.hierarchy_level_1_id == hierarchy_level_1_alias.id)
        hierarchy_aliases[1] = hierarchy_level_1_alias
        hierarchy_level_1_conditions = build_hierarchy_level_1_filter_conditions(working_filter, hierarchy_level_1_alias)
        joined_tables.add("hierarchy_level_1")
    
    if has_hierarchy_level_2 and "store" in joined_tables:
        hierarchy_level_2_alias = aliased(Hierarchy)
        query = query.join(hierarchy_level_2_alias, Store.hierarchy_level_2_id == hierarchy_level_2_alias.id)
        hierarchy_aliases[2] = hierarchy_level_2_alias
        hierarchy_level_2_conditions = build_hierarchy_level_2_filter_conditions(working_filter, hierarchy_level_2_alias)
        joined_tables.add("hierarchy_level_2")
    
    if has_hierarchy_level_3 and "store" in joined_tables:
        hierarchy_level_3_alias = aliased(Hierarchy)
        query = query.join(hierarchy_level_3_alias, Store.hierarchy_level_3_id == hierarchy_level_3_alias.id)
        hierarchy_aliases[3] = hierarchy_level_3_alias
        hierarchy_level_3_conditions = build_hierarchy_level_3_filter_conditions(working_filter, hierarchy_level_3_alias)
        joined_tables.add("hierarchy_level_3")
    
    if has_hierarchy_level_4 and "store" in joined_tables:
        hierarchy_level_4_alias = aliased(Hierarchy)
        query = query.join(hierarchy_level_4_alias, Store.hierarchy_level_4_id == hierarchy_level_4_alias.id)
        hierarchy_aliases[4] = hierarchy_level_4_alias
        hierarchy_level_4_conditions = build_hierarchy_level_4_filter_conditions(working_filter, hierarchy_level_4_alias)
        joined_tables.add("hierarchy_level_4")
    
    if has_hierarchy_level_5 and "store" in joined_tables:
        hierarchy_level_5_alias = aliased(Hierarchy)
        query = query.join(hierarchy_level_5_alias, Store.hierarchy_level_5_id == hierarchy_level_5_alias.id)
        hierarchy_aliases[5] = hierarchy_level_5_alias
        hierarchy_level_5_conditions = build_hierarchy_level_5_filter_conditions(working_filter, hierarchy_level_5_alias)
        joined_tables.add("hierarchy_level_5")

    if topic_conditions:
        query = query.join(SurveyTopics, Survey.id == SurveyTopics.survey_id)
        query = query.join(Topic, SurveyTopics.topic_id == Topic.id)
        joined_tables.add("topic")

    if keyword_conditions:
        query = query.join(SurveyKeywords, Survey.id == SurveyKeywords.survey_id)
        query = query.join(Keyword, SurveyKeywords.keyword_id == Keyword.id)
        joined_tables.add("keyword")

    if channel_conditions:
        query = query.join(Channel, Survey.channel_id == Channel.id)
        joined_tables.add("channel")

    if delivery_service_conditions:
        query = query.join(DeliveryService, Survey.delivery_service_id == DeliveryService.id)
        joined_tables.add("delivery_service")

    # Apply filters
    filter_conditions = merge_filter_conditions(
        survey_conditions,
        store_conditions,
        department_conditions,
        hierarchy_level_1_conditions,
        hierarchy_level_2_conditions,
        hierarchy_level_3_conditions,
        hierarchy_level_4_conditions,
        hierarchy_level_5_conditions,
        topic_conditions,
        keyword_conditions,
        channel_conditions,
        delivery_service_conditions,
    )

    if filter_conditions is not None:
        query = query.filter(filter_conditions)

    return query, joined_tables, hierarchy_aliases


def build_Survey_sentiment_aggregation_query(base_query, *group_by_fields):
    """Build a sentiment aggregation query with variable group by fields"""
    return base_query.with_entities(
        *group_by_fields,
        func.count(func.distinct(case((Survey.sentiment == Sentiment.NEUTRAL, Survey.id)))).label(
            "neutral_count"
        ),
        func.count(func.distinct(case((Survey.sentiment == Sentiment.POSITIVE, Survey.id)))).label(
            "positive_count"
        ),
        func.count(func.distinct(case((Survey.sentiment == Sentiment.NEGATIVE, Survey.id)))).label(
            "negative_count"
        ),
    ).group_by(*group_by_fields)


def build_SurveyKeywords_sentiment_aggregation_query(base_query, *group_by_fields):
    """Build a sentiment aggregation query with variable group by fields"""
    return base_query.with_entities(
        *group_by_fields,
        func.count(func.distinct(case((SurveyKeywords.sentiment == Sentiment.NEUTRAL, SurveyKeywords.id)))).label(
            "neutral_count"
        ),
        func.count(func.distinct(case((SurveyKeywords.sentiment == Sentiment.POSITIVE, SurveyKeywords.id)))).label(
            "positive_count"
        ),
        func.count(func.distinct(case((SurveyKeywords.sentiment == Sentiment.NEGATIVE, SurveyKeywords.id)))).label(
            "negative_count"
        ),
    ).group_by(*group_by_fields)


def build_SurveyDepartments_sentiment_aggregation_query(base_query, *group_by_fields):
    """Build a sentiment aggregation query with variable group by fields"""
    return base_query.with_entities(
        *group_by_fields,
        func.count(func.distinct(case((SurveyDepartments.sentiment == Sentiment.NEUTRAL, SurveyDepartments.id)))).label(
            "neutral_count"
        ),
        func.count(func.distinct(case((SurveyDepartments.sentiment == Sentiment.POSITIVE, SurveyDepartments.id)))).label(
            "positive_count"
        ),
        func.count(func.distinct(case((SurveyDepartments.sentiment == Sentiment.NEGATIVE, SurveyDepartments.id)))).label(
            "negative_count"
        ),
    ).group_by(*group_by_fields)


def build_SurveyTopics_sentiment_aggregation_query(base_query, *group_by_fields):
    """Build a sentiment aggregation query with variable group by fields"""
    return base_query.with_entities(
        *group_by_fields,
        func.count(func.distinct(case((SurveyTopics.sentiment == Sentiment.NEUTRAL, SurveyTopics.id)))).label(
            "neutral_count"
        ),
        func.count(func.distinct(case((SurveyTopics.sentiment == Sentiment.POSITIVE, SurveyTopics.id)))).label(
            "positive_count"
        ),
        func.count(func.distinct(case((SurveyTopics.sentiment == Sentiment.NEGATIVE, SurveyTopics.id)))).label(
            "negative_count"
        ),
    ).group_by(*group_by_fields)

class FilterRequest(BaseModel):
    store_ids: List[int] = []
    store_names: List[str] = []
    department_ids: List[int] = []
    department_names: List[str] = []
    hierarchy_level_1_ids: List[int] = []
    hierarchy_level_1_names: List[str] = []
    hierarchy_level_2_ids: List[int] = []
    hierarchy_level_2_names: List[str] = []
    hierarchy_level_3_ids: List[int] = []
    hierarchy_level_3_names: List[str] = []
    hierarchy_level_4_ids: List[int] = []
    hierarchy_level_4_names: List[str] = []
    hierarchy_level_5_ids: List[int] = []
    hierarchy_level_5_names: List[str] = []
    channel_ids: List[int] = []
    channel_names: List[str] = []
    delivery_service_ids: List[int] = []
    delivery_service_names: List[str] = []
    topics: List[str] = []
    keywords: List[str] = []
    from_date: Optional[str] = ""
    to_date: Optional[str] = ""
    sentiments: List[str] = []
    topic_sentiments: List[str] = []
    min_topic_sentiment_score: Optional[float] = None
    max_topic_sentiment_score: Optional[float] = None


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
    hierarchy_level_1_ids: List[int] = Query(
        default=[],
        description="The hierarchy level 1 ids to filter by",
    ),
    hierarchy_level_1_names: List[str] = Query(
        default=[],
        description="The hierarchy level 1 names to filter by",
    ),
    hierarchy_level_2_ids: List[int] = Query(
        default=[],
        description="The hierarchy level 2 ids to filter by",
    ),
    hierarchy_level_2_names: List[str] = Query(
        default=[],
        description="The hierarchy level 2 names to filter by",
    ),
    hierarchy_level_3_ids: List[int] = Query(
        default=[],
        description="The hierarchy level 3 ids to filter by",
    ),
    hierarchy_level_3_names: List[str] = Query(
        default=[],
        description="The hierarchy level 3 names to filter by",
    ),
    hierarchy_level_4_ids: List[int] = Query(
        default=[],
        description="The hierarchy level 4 ids to filter by",
    ),
    hierarchy_level_4_names: List[str] = Query(
        default=[],
        description="The hierarchy level 4 names to filter by",
    ),
    hierarchy_level_5_ids: List[int] = Query(
        default=[],
        description="The hierarchy level 5 ids to filter by",
    ),
    hierarchy_level_5_names: List[str] = Query(
        default=[],
        description="The hierarchy level 5 names to filter by",
    ),
    channel_ids: List[int] = Query(
        default=[],
        description="The channel ids to filter by",
    ),
    channel_names: List[str] = Query(
        default=[],
        description="The channel names to filter by",
    ),
    delivery_service_ids: List[int] = Query(
        default=[],
        description="The delivery service ids to filter by",
    ),
    delivery_service_names: List[str] = Query(
        default=[],
        description="The delivery service names to filter by",
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
        description="The sentiments to filter by (POSITIVE, NEGATIVE, NEUTRAL)",
    ),
    topic_sentiments: List[str] = Query(
        default=[],
        description="The topic sentiments to filter by (POSITIVE, NEGATIVE, NEUTRAL, MIXED)",
    ),
    min_topic_sentiment_score: Optional[float] = Query(
        default=None,
        description="Minimum topic sentiment score to filter by",
    ),
    max_topic_sentiment_score: Optional[float] = Query(
        default=None,
        description="Maximum topic sentiment score to filter by",
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
    # hierarchy_level_1_ids and hierarchy_level_1_names cannot be used together
    if hierarchy_level_1_ids and hierarchy_level_1_names:
        raise HTTPException(
            status_code=400,
            detail="hierarchy_level_1_ids and hierarchy_level_1_names cannot be used together",
        )
    # hierarchy_level_2_ids and hierarchy_level_2_names cannot be used together
    if hierarchy_level_2_ids and hierarchy_level_2_names:
        raise HTTPException(
            status_code=400,
            detail="hierarchy_level_2_ids and hierarchy_level_2_names cannot be used together",
        )
    # hierarchy_level_3_ids and hierarchy_level_3_names cannot be used together
    if hierarchy_level_3_ids and hierarchy_level_3_names:
        raise HTTPException(
            status_code=400,
            detail="hierarchy_level_3_ids and hierarchy_level_3_names cannot be used together",
        )
    # hierarchy_level_4_ids and hierarchy_level_4_names cannot be used together
    if hierarchy_level_4_ids and hierarchy_level_4_names:
        raise HTTPException(
            status_code=400,
            detail="hierarchy_level_4_ids and hierarchy_level_4_names cannot be used together",
        )
    # hierarchy_level_5_ids and hierarchy_level_5_names cannot be used together
    if hierarchy_level_5_ids and hierarchy_level_5_names:
        raise HTTPException(
            status_code=400,
            detail="hierarchy_level_5_ids and hierarchy_level_5_names cannot be used together",
        )
    # channel_ids and channel_names cannot be used together
    if channel_ids and channel_names:
        raise HTTPException(
            status_code=400,
            detail="channel_ids and channel_names cannot be used together",
        )
    # delivery_service_ids and delivery_service_names cannot be used together
    if delivery_service_ids and delivery_service_names:
        raise HTTPException(
            status_code=400,
            detail="delivery_service_ids and delivery_service_names cannot be used together",
        )

    return FilterRequest(
        store_ids=store_ids,
        store_names=store_names,
        department_ids=department_ids,
        department_names=department_names,
        hierarchy_level_1_ids=hierarchy_level_1_ids,
        hierarchy_level_1_names=hierarchy_level_1_names,
        hierarchy_level_2_ids=hierarchy_level_2_ids,
        hierarchy_level_2_names=hierarchy_level_2_names,
        hierarchy_level_3_ids=hierarchy_level_3_ids,
        hierarchy_level_3_names=hierarchy_level_3_names,
        hierarchy_level_4_ids=hierarchy_level_4_ids,
        hierarchy_level_4_names=hierarchy_level_4_names,
        hierarchy_level_5_ids=hierarchy_level_5_ids,
        hierarchy_level_5_names=hierarchy_level_5_names,
        channel_ids=channel_ids,
        channel_names=channel_names,
        delivery_service_ids=delivery_service_ids,
        delivery_service_names=delivery_service_names,
        topics=topics,
        keywords=keywords,
        from_date=from_date,
        to_date=to_date,
        sentiments=[
            sentiment.lower() for sentiment in sentiments # Convert into list of lowercase strings
        ],
        topic_sentiments=[
            topic_sentiment.upper() for topic_sentiment in topic_sentiments # Convert into list of uppercase strings to match enum
        ],
        min_topic_sentiment_score=min_topic_sentiment_score,
        max_topic_sentiment_score=max_topic_sentiment_score,
    )
