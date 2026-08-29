from infrastructure.database.dbo.Channel import Channel
from infrastructure.database.dbo.DeliveryService import DeliveryService
from infrastructure.database.dbo.Department import Department
from infrastructure.database.dbo.Keyword import Keyword
from infrastructure.database.dbo.Store import Store
from infrastructure.database.dbo.Survey import Survey
from infrastructure.database.dbo.SurveyDepartments import SurveyDepartments
from infrastructure.database.dbo.SurveyKeywords import SurveyKeywords
from infrastructure.database.dbo.SurveyTopics import SurveyTopics
from infrastructure.database.dbo.Topic import Topic
from sqlalchemy import and_
from sqlalchemy.orm import Query
from sqlalchemy.orm import Session
from typing import List
from fastapi import HTTPException, Query
from pydantic import BaseModel, field_validator
from typing import Optional
from datetime import date, datetime, time, timezone
from core.time import resolve_timezone


class FilterRequest(BaseModel):
    store_keys: List[int] = []
    store_english_names: List[str] = []
    store_local_names: List[str] = []
    bu_keys: List[str] = []
    area_managers: List[str] = []
    store_formats: List[str] = []
    store_types: List[str] = []
    operations_controllers: List[str] = []
    regional_managers: List[str] = []
    px: List[str] = []
    csr: List[str] = []
    dr: List[str] = []
    mag_types: List[str] = []
    cf_groupings: List[str] = []
    store_brands: List[str] = []
    competitors: List[str] = []
    regions: List[str] = []
    areas: List[str] = []
    provinces: List[str] = []
    territories: List[str] = []
    tohs: List[str] = []
    districts: List[str] = []
    cities: List[str] = []
    operations_managers: List[str] = []
    district_managers: List[str] = []
    sic: List[str] = []
    soc: List[str] = []
    tech_life_types: List[str] = []
    operation_manager_tls: List[str] = []
    region_manager_tls: List[str] = []
    relocations: List[str] = []
    latitudes: List[float] = []
    longitudes: List[float] = []
    store_open_dates: List[date] = []
    store_close_dates: List[date] = []
    is_closed: Optional[bool] = None
    department_ids: List[int] = []
    department_names: List[str] = []
    channel_ids: List[int] = []
    channel_names: List[str] = []
    delivery_service_ids: List[int] = []
    delivery_service_names: List[str] = []
    topics: List[str] = []
    keywords: List[str] = []
    from_date: Optional[str] = ""
    to_date: Optional[str] = ""
    timezone: Optional[str] = None
    sentiments: List[str] = []
    topic_sentiments: List[str] = []
    min_topic_sentiment_score: Optional[float] = None
    max_topic_sentiment_score: Optional[float] = None
    min_cls: Optional[float] = None
    max_cls: Optional[float] = None

    @field_validator("timezone")
    @classmethod
    def _timezone(cls, value: str | None) -> str | None:
        if value is not None:
            resolve_timezone(value)
        return value


def get_filter_params(
    store_keys: List[int] = Query(
        default=[],
        description="The store keys to filter by",
    ),
    store_english_names: List[str] = Query(
        default=[],
        description="The store english names to filter by",
    ),
    store_local_names: List[str] = Query(
        default=[],
        description="The store local names to filter by",
    ),
    bu_keys: List[str] = Query(
        default=[],
        description="The store bu keys to filter by",
    ),  
    area_managers: List[str] = Query(
        default=[],
        description="The area managers to filter by",
    ),
    store_formats: List[str] = Query(
        default=[],
        description="The store formats to filter by",
    ),
    store_types: List[str] = Query(
        default=[],
        description="The store types to filter by",
    ),
    operations_controllers: List[str] = Query(
        default=[],
        description="The operations controllers to filter by",
    ),
    regional_managers: List[str] = Query(
        default=[],
        description="The regional managers to filter by",
    ),
    px: List[str] = Query(
        default=[],
        description="The px to filter by",
    ),
    csr: List[str] = Query(
        default=[],
        description="The csr to filter by",
    ),
    dr: List[str] = Query(
        default=[],
        description="The dr to filter by",
    ),
    mag_types: List[str] = Query(
        default=[],
        description="The mag types to filter by",
    ),
    cf_groupings: List[str] = Query(
        default=[],
        description="The cf groupings to filter by",
    ),
    store_brands: List[str] = Query(
        default=[],
        description="The store brands to filter by",
    ),
    competitors: List[str] = Query(
        default=[],
        description="The competitors to filter by",
    ),
    regions: List[str] = Query(
        default=[],
        description="The regions to filter by",
    ),
    areas: List[str] = Query(
        default=[],
        description="The areas to filter by",
    ),
    provinces: List[str] = Query(
        default=[],
        description="The provinces to filter by",
    ),
    territories: List[str] = Query(
        default=[],
        description="The territories to filter by",
    ),
    tohs: List[str] = Query(
        default=[],
        description="The tohs to filter by",
    ),
    districts: List[str] = Query(
        default=[],
        description="The districts to filter by",
    ),
    cities: List[str] = Query(
        default=[],
        description="The cities to filter by",
    ),
    operations_managers: List[str] = Query(
        default=[],
        description="The operations managers to filter by",
    ),
    district_managers: List[str] = Query(
        default=[],
        description="The district managers to filter by",
    ),
    sic: List[str] = Query(
        default=[],
        description="The sic to filter by",
    ),
    soc: List[str] = Query(
        default=[],
        description="The soc to filter by",
    ),
    tech_life_types: List[str] = Query(
        default=[],
        description="The tech life types to filter by",
    ),
    operation_manager_tls: List[str] = Query(
        default=[],
        description="The operation manager tls to filter by",
    ),
    region_manager_tls: List[str] = Query(
        default=[],
        description="The region manager tls to filter by",
    ),
    relocations: List[str] = Query(
        default=[],
        description="The relocations to filter by",
    ),
    latitudes: List[float] = Query(
        default=[],
        description="The latitudes to filter by",
    ),
    longitudes: List[float] = Query(
        default=[],
        description="The longitudes to filter by",
    ),
    store_open_dates: List[date] = Query(
        default=[],
        description="The store open dates to filter by",
    ),
    store_close_dates: List[date] = Query(
        default=[],
        description="The store close dates to filter by",
    ),
    is_closed: Optional[bool] = Query(
        default=None,
        description="The is closed to filter by",
    ),
    department_ids: List[int] = Query(
        default=[],
        description="The department ids to filter by",
    ),
    department_names: List[str] = Query(
        default=[],
        description="The department names to filter by",
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
        description=(
            "The inclusive start timestamp to filter by, in UTC ISO format unless "
            "timezone is supplied"
        ),
    ),
    to_date: str = Query(
        default="",
        description=(
            "The exclusive end timestamp to filter by, in UTC ISO format unless "
            "timezone is supplied"
        ),
    ),
    timezone: Optional[str] = Query(
        default=None,
        description=(
            "Optional IANA timezone for date-only or timezone-less from_date/to_date "
            "values and timestamp display; UTC is used when omitted"
        ),
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
    min_cls: Optional[float] = Query(
        default=None,
        description="Minimum CLS score to filter by",
    ),
    max_cls: Optional[float] = Query(
        default=None,
        description="Maximum CLS score to filter by",
    ),
) -> FilterRequest:

    return FilterRequest(
        store_keys=store_keys,
        store_english_names=store_english_names,
        store_local_names=store_local_names,
        bu_keys=bu_keys,
        area_managers=area_managers,
        store_formats=store_formats,
        store_types=store_types,
        operations_controllers=operations_controllers,
        regional_managers=regional_managers,
        px=px,
        csr=csr,
        dr=dr,
        mag_types=mag_types,
        cf_groupings=cf_groupings,
        store_brands=store_brands,
        competitors=competitors,
        regions=regions,
        areas=areas,
        provinces=provinces,
        territories=territories,
        tohs=tohs,
        districts=districts,
        cities=cities,
        operations_managers=operations_managers,
        district_managers=district_managers,
        sic=sic,
        soc=soc,
        tech_life_types=tech_life_types,
        operation_manager_tls=operation_manager_tls,
        region_manager_tls=region_manager_tls,
        relocations=relocations,
        latitudes=latitudes,
        longitudes=longitudes,
        store_open_dates=store_open_dates,
        store_close_dates=store_close_dates,
        is_closed=is_closed,
        department_ids=department_ids,
        department_names=department_names,
        channel_ids=channel_ids,
        channel_names=channel_names,
        delivery_service_ids=delivery_service_ids,
        delivery_service_names=delivery_service_names,
        topics=topics,
        keywords=keywords,
        from_date=from_date,
        to_date=to_date,
        timezone=timezone,
        sentiments=[
            sentiment.lower() for sentiment in sentiments # Convert into list of lowercase strings
        ],
        topic_sentiments=[
            topic_sentiment.upper() for topic_sentiment in topic_sentiments # Convert into list of uppercase strings to match enum
        ],
        min_topic_sentiment_score=min_topic_sentiment_score,
        max_topic_sentiment_score=max_topic_sentiment_score,
        min_cls=min_cls,
        max_cls=max_cls,
    )



def build_survey_filter_conditions(filter_dict: FilterRequest):
    """Build filter conditions based on the filter dictionary"""
    conditions = []

    timezone_name = filter_dict.get("timezone")
    try:
        local_timezone = resolve_timezone(timezone_name)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    def parse_filter_datetime(value: str | date | datetime, field_name: str) -> datetime:
        if isinstance(value, datetime):
            parsed_datetime = value
        elif isinstance(value, date):
            parsed_datetime = datetime.combine(value, time.min)
        else:
            if "T" not in value and " " not in value and not timezone_name:
                raise HTTPException(
                    status_code=400,
                    detail=f"{field_name} must use UTC ISO timestamp format or provide timezone",
                )
            normalized_value = value.replace("Z", "+00:00")
            try:
                parsed_datetime = datetime.fromisoformat(normalized_value)
            except ValueError as exc:
                raise HTTPException(
                    status_code=400,
                    detail=f"{field_name} must use UTC ISO timestamp format",
                ) from exc
            if parsed_datetime.tzinfo is None and not timezone_name:
                raise HTTPException(
                    status_code=400,
                    detail=f"{field_name} must use UTC ISO timestamp format or provide timezone",
                )
        if parsed_datetime.tzinfo is None:
            try:
                parsed_datetime = parsed_datetime.replace(
                    tzinfo=local_timezone
                )
            except ValueError as error:
                raise HTTPException(status_code=400, detail=str(error)) from error
        return parsed_datetime.astimezone(timezone.utc)

    # Add is_deleted check
    conditions.append(Survey.is_deleted == False)

    # Date range filter
    if filter_dict.get("from_date"):
        from_date = parse_filter_datetime(filter_dict["from_date"], "from_date")
        conditions.append(Survey.reported_at >= from_date)

    if filter_dict.get("to_date"):
        to_date = parse_filter_datetime(filter_dict["to_date"], "to_date")
        conditions.append(Survey.reported_at < to_date)

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

    # CLS score range filters
    if filter_dict.get("min_cls") is not None:
        conditions.append(Survey.cls >= filter_dict["min_cls"])

    if filter_dict.get("max_cls") is not None:
        conditions.append(Survey.cls <= filter_dict["max_cls"])

    # id filter
    if filter_dict.get("ids"):
        conditions.append(Survey.id.in_(filter_dict["ids"]))

    return conditions


def build_topic_filter_conditions(filter_dict: FilterRequest):
    """Build filter conditions for topic-related queries that include topic filtering"""
    conditions = []
    # Topic filter - this requires joining with SurveyTopics and Topic tables
    if filter_dict.get("topics"):
        conditions.append(Topic.topic.in_(filter_dict["topics"]))

    return conditions


def build_store_filter_conditions(filter_dict: FilterRequest):
    """Build filter conditions for store-related queries that include store filtering"""
    conditions = []
    # Store filter
    if filter_dict.get("store_keys"):
        conditions.append(Store.store_key.in_(filter_dict["store_keys"]))

    if filter_dict.get("store_english_names"):
        conditions.append(Store.store_name_english.in_(filter_dict["store_english_names"]))

    if filter_dict.get("store_local_names"):
        conditions.append(Store.store_name_local.in_(filter_dict["store_local_names"]))

    if filter_dict.get("bu_keys"):
        conditions.append(Store.bu_key.in_(filter_dict["bu_keys"]))

    if filter_dict.get("area_managers"):
        conditions.append(Store.area_manager.in_(filter_dict["area_managers"]))

    if filter_dict.get("store_formats"):
        conditions.append(Store.store_format.in_(filter_dict["store_formats"]))

    if filter_dict.get("store_types"):
        conditions.append(Store.store_type.in_(filter_dict["store_types"]))

    if filter_dict.get("operations_controllers"):
        conditions.append(Store.operations_controller.in_(filter_dict["operations_controllers"]))

    if filter_dict.get("regional_managers"):
        conditions.append(Store.regional_manager.in_(filter_dict["regional_managers"]))

    if filter_dict.get("px"):
        conditions.append(Store.px.in_(filter_dict["px"]))

    if filter_dict.get("csr"):
        conditions.append(Store.csr.in_(filter_dict["csr"]))

    if filter_dict.get("dr"):
        conditions.append(Store.dr.in_(filter_dict["dr"]))

    if filter_dict.get("mag_types"):
        conditions.append(Store.mag_type.in_(filter_dict["mag_types"]))

    if filter_dict.get("cf_groupings"):
        conditions.append(Store.cf_grouping.in_(filter_dict["cf_groupings"]))

    if filter_dict.get("store_brands"):
        conditions.append(Store.store_brand.in_(filter_dict["store_brands"]))

    if filter_dict.get("competitors"):
        conditions.append(Store.competitor.in_(filter_dict["competitors"]))

    if filter_dict.get("regions"):
        conditions.append(Store.region.in_(filter_dict["regions"]))

    if filter_dict.get("areas"):
        conditions.append(Store.area.in_(filter_dict["areas"]))

    if filter_dict.get("provinces"):
        conditions.append(Store.province.in_(filter_dict["provinces"]))

    if filter_dict.get("territories"):
        conditions.append(Store.territory.in_(filter_dict["territories"]))

    if filter_dict.get("tohs"):
        conditions.append(Store.toh.in_(filter_dict["tohs"]))

    if filter_dict.get("districts"):
        conditions.append(Store.district.in_(filter_dict["districts"]))

    if filter_dict.get("cities"):
        conditions.append(Store.city.in_(filter_dict["cities"]))

    if filter_dict.get("operations_managers"):
        conditions.append(Store.operations_manager.in_(filter_dict["operations_managers"]))

    if filter_dict.get("district_managers"):
        conditions.append(Store.district_manager.in_(filter_dict["district_managers"]))

    if filter_dict.get("sic"):
        conditions.append(Store.sic.in_(filter_dict["sic"]))

    if filter_dict.get("soc"):
        conditions.append(Store.soc.in_(filter_dict["soc"]))

    if filter_dict.get("tech_life_types"):
        conditions.append(Store.tech_life_type.in_(filter_dict["tech_life_types"]))

    if filter_dict.get("operation_manager_tls"):
        conditions.append(Store.operation_manager_tl.in_(filter_dict["operation_manager_tls"]))

    if filter_dict.get("region_manager_tls"):
        conditions.append(Store.region_manager_tl.in_(filter_dict["region_manager_tls"]))

    if filter_dict.get("relocations"):
        conditions.append(Store.relocation.in_(filter_dict["relocations"]))

    if filter_dict.get("latitudes"):
        conditions.append(Store.latitude.in_(filter_dict["latitudes"]))

    if filter_dict.get("longitudes"):
        conditions.append(Store.longitude.in_(filter_dict["longitudes"]))

    if filter_dict.get("store_open_dates"):
        conditions.append(Store.store_open_date.in_(filter_dict["store_open_dates"]))

    if filter_dict.get("store_close_dates"):
        conditions.append(Store.store_close_date.in_(filter_dict["store_close_dates"]))

    if filter_dict.get("is_closed") is not None:
        conditions.append(Store.is_closed == filter_dict["is_closed"])

    return conditions


def build_department_filter_conditions(filter_dict: FilterRequest):
    """Build filter conditions for department-related queries that include department filtering"""
    conditions = []
    # Department filter
    if filter_dict.get("department_ids"):
        conditions.append(Department.id.in_(filter_dict["department_ids"]))

    if filter_dict.get("department_names"):
        conditions.append(Department.name.in_(filter_dict["department_names"]))

    return conditions

def build_keyword_filter_conditions(filter_dict: FilterRequest):
    """Build filter conditions for keyword-related queries that include keyword filtering"""
    conditions = []
    # Keyword filter - this requires joining with SurveyKeywords and Keyword tables
    if filter_dict.get("keywords"):
        conditions.append(Keyword.keyword.in_(filter_dict["keywords"]))

    return conditions


def build_survey_query(query: Query, filter_dict: FilterRequest) -> Query:
    """Build a complete survey query with appropriate joins and optimizations based on filter conditions"""
    # Build all filter conditions (for non-hierarchy filters first)
    survey_conditions = build_survey_filter_conditions(filter_dict)
    store_conditions = build_store_filter_conditions(filter_dict)
    department_conditions = build_department_filter_conditions(filter_dict)
    topic_conditions = build_topic_filter_conditions(filter_dict)
    keyword_conditions = build_keyword_filter_conditions(filter_dict)
    channel_conditions = build_channel_filter_conditions(filter_dict)
    delivery_service_conditions = build_delivery_service_filter_conditions(filter_dict)
    
    # Add joins only when filtering is needed to avoid cartesian products
    joins_added = set()

    # Join Store if store filters are applied or if we need it for hierarchy joins
    if (
        store_conditions
    ):
        query = query.join(Store, Survey.store_key == Store.store_key)
        joins_added.add("store")

    # Join Department if department filters are applied
    if department_conditions:
        query = query.join(SurveyDepartments, Survey.id == SurveyDepartments.survey_id)
        query = query.join(Department, SurveyDepartments.department_id == Department.id)
        joins_added.add("department")


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


def build_channel_filter_conditions(filter_dict: FilterRequest):
    """Build filter conditions for channel-related queries that include channel filtering"""
    conditions = []
    # Channel filter
    if filter_dict.get("channel_ids"):
        conditions.append(Channel.id.in_(filter_dict["channel_ids"]))

    if filter_dict.get("channel_names"):
        conditions.append(Channel.name.in_(filter_dict["channel_names"]))

    return conditions


def build_delivery_service_filter_conditions(filter_dict: FilterRequest):
    """Build filter conditions for delivery service-related queries that include delivery service filtering"""
    conditions = []
    # Delivery service filter
    if filter_dict.get("delivery_service_ids"):
        conditions.append(DeliveryService.id.in_(filter_dict["delivery_service_ids"]))

    if filter_dict.get("delivery_service_names"):
        conditions.append(DeliveryService.name.in_(filter_dict["delivery_service_names"]))

    return conditions


def build_optimized_query(
    db: Session, filter_dict: FilterRequest, exclude_filters: List[str] = None
):
    """
    Build an optimized query with minimal joins and filtering.
    
    Returns:
        tuple: (query, joined_tables, working_filter)
            - query: SQLAlchemy query object with filters applied
            - joined_tables: Set of table names that have been joined
            - working_filter: Dictionary of filters that were actually applied
    """
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
    
    # Start with base query
    query = db.query(Survey)

    # Add joins only when needed - track what we've joined to avoid duplicates
    joined_tables = set()

    # Join Store if store filters are applied
    if (
        store_conditions
    ):
        query = query.join(Store, Survey.store_key == Store.store_key)
        joined_tables.add("store")

    if department_conditions:
        query = query.join(SurveyDepartments, Survey.id == SurveyDepartments.survey_id)
        query = query.join(Department, SurveyDepartments.department_id == Department.id)
        joined_tables.add("department")

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
        topic_conditions,
        keyword_conditions,
        channel_conditions,
        delivery_service_conditions,
    )

    if filter_conditions is not None:
        query = query.filter(filter_conditions)

    return query, joined_tables, working_filter
