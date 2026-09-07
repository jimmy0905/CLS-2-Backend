"""Governed, live-database record queries for analytics clients."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from typing import Any, Callable, Literal

from sqlalchemy import Select, and_, exists, func, select, text
from sqlalchemy.orm import Session, selectinload

import core.config as config
from core.time import as_timezone, resolve_timezone
from features.analytics.model.semantic import (
    CatalogField,
    FieldType,
    FilterSpec,
    SemanticCatalog,
    validate_query_fields,
)
from infrastructure.database.dbo.Channel import Channel
from infrastructure.database.dbo.Department import Department
from infrastructure.database.dbo.DeliveryService import DeliveryService
from infrastructure.database.dbo.Keyword import Keyword
from infrastructure.database.dbo.Store import Store
from infrastructure.database.dbo.Survey import Survey
from infrastructure.database.dbo.SurveyDepartments import SurveyDepartments
from infrastructure.database.dbo.SurveyKeywords import SurveyKeywords
from infrastructure.database.dbo.SurveyTopics import SurveyTopics
from infrastructure.database.dbo.Topic import Topic


RecordResource = Literal[
    "surveys",
    "stores",
    "departments",
    "channels",
    "delivery_services",
    "topics",
]

DEFAULT_PROJECTED_RECORD_FIELDS = (
    "id",
    "survey_id",
    "reported_at",
    "store_key",
    "store_name",
    "topic_sentiment",
    "comment",
)


@dataclass(frozen=True)
class RecordField:
    expression: Any
    data_type: FieldType
    is_datetime: bool = False
    normalizer: Callable[[Any], Any] | None = None


def _upper(value: Any) -> Any:
    return value.upper() if isinstance(value, str) else value


def _store_fields() -> dict[str, RecordField]:
    return {
        "store_key": RecordField(Store.store_key, FieldType.NUMBER),
        "store_name_english": RecordField(Store.store_name_english, FieldType.STRING),
        "store_name_local": RecordField(Store.store_name_local, FieldType.STRING),
        "bu_key": RecordField(Store.bu_key, FieldType.STRING),
        "area_manager": RecordField(Store.area_manager, FieldType.STRING),
        "store_format": RecordField(Store.store_format, FieldType.STRING),
        "store_type": RecordField(Store.store_type, FieldType.STRING),
        "operations_controller": RecordField(Store.operations_controller, FieldType.STRING),
        "regional_manager": RecordField(Store.regional_manager, FieldType.STRING),
        "px": RecordField(Store.px, FieldType.STRING),
        "csr": RecordField(Store.csr, FieldType.STRING),
        "dr": RecordField(Store.dr, FieldType.STRING),
        "mag_type": RecordField(Store.mag_type, FieldType.STRING),
        "cf_grouping": RecordField(Store.cf_grouping, FieldType.STRING),
        "store_brand": RecordField(Store.store_brand, FieldType.STRING),
        "competitor": RecordField(Store.competitor, FieldType.STRING),
        "region": RecordField(Store.region, FieldType.STRING),
        "area": RecordField(Store.area, FieldType.STRING),
        "province": RecordField(Store.province, FieldType.STRING),
        "territory": RecordField(Store.territory, FieldType.STRING),
        "toh": RecordField(Store.toh, FieldType.STRING),
        "district": RecordField(Store.district, FieldType.STRING),
        "city": RecordField(Store.city, FieldType.STRING),
        "operations_manager": RecordField(Store.operations_manager, FieldType.STRING),
        "district_manager": RecordField(Store.district_manager, FieldType.STRING),
        "sic": RecordField(Store.sic, FieldType.STRING),
        "soc": RecordField(Store.soc, FieldType.STRING),
        "tech_life_type": RecordField(Store.tech_life_type, FieldType.STRING),
        "operation_manager_tl": RecordField(Store.operation_manager_tl, FieldType.STRING),
        "region_manager_tl": RecordField(Store.region_manager_tl, FieldType.STRING),
        "relocation": RecordField(Store.relocation, FieldType.STRING),
        "latitude": RecordField(Store.latitude, FieldType.NUMBER),
        "longitude": RecordField(Store.longitude, FieldType.NUMBER),
        "store_open_date": RecordField(Store.store_open_date, FieldType.DATE),
        "store_close_date": RecordField(Store.store_close_date, FieldType.DATE),
        "is_closed": RecordField(Store.is_closed, FieldType.BOOLEAN),
    }


_MASTER_FIELDS: dict[str, dict[str, RecordField]] = {
    "stores": _store_fields(),
    "departments": {
        "id": RecordField(Department.id, FieldType.NUMBER),
        "name": RecordField(Department.name, FieldType.STRING),
    },
    "channels": {
        "id": RecordField(Channel.id, FieldType.NUMBER),
        "name": RecordField(Channel.name, FieldType.STRING),
    },
    "delivery_services": {
        "id": RecordField(DeliveryService.id, FieldType.NUMBER),
        "name": RecordField(DeliveryService.name, FieldType.STRING),
    },
    "topics": {
        "id": RecordField(Topic.id, FieldType.NUMBER),
        "topic": RecordField(Topic.topic, FieldType.STRING),
    },
}


_SURVEY_FIELDS: dict[str, RecordField] = {
    "id": RecordField(Survey.id, FieldType.NUMBER),
    "survey_id": RecordField(Survey.survey_id, FieldType.STRING),
    "respondent_id": RecordField(Survey.respondent_id, FieldType.STRING),
    "store_key": RecordField(Survey.store_key, FieldType.NUMBER),
    "store_name": RecordField(
        func.coalesce(Store.store_name_english, Store.store_name_local), FieldType.STRING
    ),
    "store_name_english": RecordField(Store.store_name_english, FieldType.STRING),
    "store_name_local": RecordField(Store.store_name_local, FieldType.STRING),
    "bu_key": RecordField(Store.bu_key, FieldType.STRING),
    "area_manager": RecordField(Store.area_manager, FieldType.STRING),
    "store_format": RecordField(Store.store_format, FieldType.STRING),
    "store_type": RecordField(Store.store_type, FieldType.STRING),
    "operations_controller": RecordField(Store.operations_controller, FieldType.STRING),
    "regional_manager": RecordField(Store.regional_manager, FieldType.STRING),
    "px": RecordField(Store.px, FieldType.STRING),
    "csr": RecordField(Store.csr, FieldType.STRING),
    "dr": RecordField(Store.dr, FieldType.STRING),
    "mag_type": RecordField(Store.mag_type, FieldType.STRING),
    "cf_grouping": RecordField(Store.cf_grouping, FieldType.STRING),
    "store_brand": RecordField(Store.store_brand, FieldType.STRING),
    "competitor": RecordField(Store.competitor, FieldType.STRING),
    "region": RecordField(Store.region, FieldType.STRING),
    "area": RecordField(Store.area, FieldType.STRING),
    "province": RecordField(Store.province, FieldType.STRING),
    "territory": RecordField(Store.territory, FieldType.STRING),
    "toh": RecordField(Store.toh, FieldType.STRING),
    "district": RecordField(Store.district, FieldType.STRING),
    "city": RecordField(Store.city, FieldType.STRING),
    "operations_manager": RecordField(Store.operations_manager, FieldType.STRING),
    "district_manager": RecordField(Store.district_manager, FieldType.STRING),
    "sic": RecordField(Store.sic, FieldType.STRING),
    "soc": RecordField(Store.soc, FieldType.STRING),
    "tech_life_type": RecordField(Store.tech_life_type, FieldType.STRING),
    "operation_manager_tl": RecordField(Store.operation_manager_tl, FieldType.STRING),
    "region_manager_tl": RecordField(Store.region_manager_tl, FieldType.STRING),
    "relocation": RecordField(Store.relocation, FieldType.STRING),
    "latitude": RecordField(Store.latitude, FieldType.NUMBER),
    "longitude": RecordField(Store.longitude, FieldType.NUMBER),
    "store_open_date": RecordField(Store.store_open_date, FieldType.DATE),
    "store_close_date": RecordField(Store.store_close_date, FieldType.DATE),
    "is_closed": RecordField(Store.is_closed, FieldType.BOOLEAN),
    "channel_id": RecordField(Survey.channel_id, FieldType.NUMBER),
    "channel_name": RecordField(Channel.name, FieldType.STRING),
    "channel": RecordField(Channel.name, FieldType.STRING),
    "delivery_service_id": RecordField(Survey.delivery_service_id, FieldType.NUMBER),
    "delivery_service_name": RecordField(DeliveryService.name, FieldType.STRING),
    "delivery_service": RecordField(DeliveryService.name, FieldType.STRING),
    "comment": RecordField(Survey.comment, FieldType.STRING),
    "sentiment": RecordField(Survey.sentiment, FieldType.STRING, normalizer=_upper),
    "topic_sentiment": RecordField(
        Survey.topic_sentiment, FieldType.STRING, normalizer=_upper
    ),
    "topic_sentiment_score": RecordField(Survey.topic_sentiment_score, FieldType.NUMBER),
    "cls": RecordField(Survey.cls, FieldType.NUMBER),
    "reported_at": RecordField(Survey.reported_at, FieldType.DATE, is_datetime=True),
    "created_at": RecordField(Survey.created_at, FieldType.DATE, is_datetime=True),
    "updated_at": RecordField(Survey.updated_at, FieldType.DATE, is_datetime=True),
}

_ASSIGNMENT_FIELDS = {
    "topic_id": (SurveyTopics, Topic, SurveyTopics.topic_id, Topic.id, Topic.topic),
    "topic": (SurveyTopics, Topic, SurveyTopics.topic_id, Topic.id, Topic.topic),
    "topic_assignment_sentiment": (
        SurveyTopics,
        Topic,
        SurveyTopics.sentiment,
        None,
        None,
    ),
    "department_id": (
        SurveyDepartments,
        Department,
        SurveyDepartments.department_id,
        Department.id,
        Department.name,
    ),
    "department": (
        SurveyDepartments,
        Department,
        SurveyDepartments.department_id,
        Department.id,
        Department.name,
    ),
    "department_assignment_sentiment": (
        SurveyDepartments,
        Department,
        SurveyDepartments.sentiment,
        None,
        None,
    ),
    "keyword_id": (
        SurveyKeywords,
        Keyword,
        SurveyKeywords.keyword_id,
        Keyword.id,
        Keyword.keyword,
    ),
    "keyword": (
        SurveyKeywords,
        Keyword,
        SurveyKeywords.keyword_id,
        Keyword.id,
        Keyword.keyword,
    ),
    "keyword_assignment_sentiment": (
        SurveyKeywords,
        Keyword,
        SurveyKeywords.sentiment,
        None,
        None,
    ),
}


def fields_for(resource: RecordResource) -> dict[str, RecordField]:
    if resource == "surveys":
        return _SURVEY_FIELDS
    return _MASTER_FIELDS[resource]


def _coerce_scalar(
    value: Any, field: RecordField, timezone_name: str | None
) -> Any:
    if field.normalizer is not None:
        value = field.normalizer(value)
    if field.data_type is FieldType.STRING:
        if not isinstance(value, str):
            raise ValueError("record filter value must be a string")
        return value
    if field.data_type is FieldType.NUMBER:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("record filter value must be a number")
        if not math.isfinite(float(value)):
            raise ValueError("record filter value must be finite")
        return value
    if field.data_type is FieldType.BOOLEAN:
        if not isinstance(value, bool):
            raise ValueError("record filter value must be a boolean")
        return value
    if field.data_type is FieldType.TIME:
        if isinstance(value, time):
            return value
        if isinstance(value, str):
            try:
                return time.fromisoformat(value)
            except ValueError as error:
                raise ValueError("record filter value must be an ISO time") from error
        raise ValueError("record filter value must be an ISO time")
    if field.is_datetime:
        if isinstance(value, date) and not isinstance(value, datetime):
            parsed = datetime.combine(value, time.min)
        elif isinstance(value, datetime):
            parsed = value
        elif isinstance(value, str):
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError as error:
                raise ValueError("record filter value must be an ISO timestamp") from error
        else:
            raise ValueError("record filter value must be an ISO timestamp")
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=resolve_timezone(timezone_name))
        return parsed.astimezone(timezone.utc)
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError as error:
            raise ValueError("record filter value must be an ISO date") from error
    raise ValueError("record filter value must be an ISO date")


def _filter_parts(item: Any, field: RecordField, timezone_name: str | None):
    operator = item.operator
    if operator in {"set", "not_set"}:
        if item.value is not None or item.values is not None:
            raise ValueError(f"{operator} filters do not accept a value")
        return operator, None
    values = item.values
    if operator in {"in", "not_in", "between"} and values is None:
        if isinstance(item.value, (list, tuple)):
            values = tuple(item.value)
        else:
            raise ValueError(f"{operator} filters require values")
    if operator in {"in", "not_in"}:
        if not values:
            raise ValueError(f"{operator} filters require at least one value")
        return operator, tuple(_coerce_scalar(value, field, timezone_name) for value in values)
    if operator == "between":
        if values is None or len(values) != 2:
            raise ValueError("between filters require exactly two values")
        return operator, tuple(_coerce_scalar(value, field, timezone_name) for value in values)
    if item.value is None:
        raise ValueError(f"{operator} filters require value")
    if values is not None:
        raise ValueError(f"{operator} filters do not accept values")
    return operator, _coerce_scalar(item.value, field, timezone_name)


def _condition(expression: Any, operator: str, value: Any):
    if operator == "equals":
        return expression == value
    if operator == "not_equals":
        return expression != value
    if operator == "contains":
        return expression.contains(value)
    if operator == "not_contains":
        return ~expression.contains(value)
    if operator == "starts_with":
        return expression.startswith(value)
    if operator == "ends_with":
        return expression.endswith(value)
    if operator == "greater_than":
        return expression > value
    if operator == "greater_than_or_equal":
        return expression >= value
    if operator == "less_than":
        return expression < value
    if operator == "less_than_or_equal":
        return expression <= value
    if operator == "in":
        return expression.in_(value)
    if operator == "not_in":
        return expression.not_in(value)
    if operator == "set":
        return expression.is_not(None)
    if operator == "not_set":
        return expression.is_(None)
    if operator == "between":
        return expression.between(value[0], value[1])
    raise ValueError("Unsupported record filter operator")


def _assignment_condition(
    item: Any, timezone_name: str | None
):
    assignment_model, master_model, assignment_expression, id_expression, name_expression = (
        _ASSIGNMENT_FIELDS[item.member]
    )
    assignment_field = RecordField(assignment_expression, FieldType.STRING)
    if item.member.endswith("_id"):
        assignment_field = RecordField(assignment_expression, FieldType.NUMBER)
    elif item.member in {"topic", "department", "keyword"}:
        assignment_field = RecordField(name_expression, FieldType.STRING)
        assignment_expression = name_expression
    else:
        assignment_field = RecordField(assignment_expression, FieldType.STRING, normalizer=_upper)
    operator, value = _filter_parts(item, assignment_field, timezone_name)
    conditions = [assignment_model.survey_id == Survey.id]
    conditions.append(_condition(assignment_expression, operator, value))
    statement = select(1).select_from(assignment_model)
    if id_expression is not None:
        statement = statement.join(master_model, id_expression == master_model.id)
    return exists(
        statement.where(and_(*conditions))
    )


def _base_query(db: Session, resource: RecordResource):
    models = {
        "surveys": Survey,
        "stores": Store,
        "departments": Department,
        "channels": Channel,
        "delivery_services": DeliveryService,
        "topics": Topic,
    }
    query = db.query(models[resource])
    if resource == "surveys":
        query = query.options(
            selectinload(Survey.store),
            selectinload(Survey.channel),
            selectinload(Survey.delivery_service),
            selectinload(Survey.survey_departments).selectinload(SurveyDepartments.department),
            selectinload(Survey.survey_topics).selectinload(SurveyTopics.topic),
            selectinload(Survey.survey_keywords).selectinload(SurveyKeywords.keyword),
        ).join(Store, Store.store_key == Survey.store_key).outerjoin(
            Channel, Channel.id == Survey.channel_id
        ).outerjoin(
            DeliveryService, DeliveryService.id == Survey.delivery_service_id
        ).filter(Survey.is_deleted.is_not(True))
    return query


def build_record_query(
    db: Session,
    resource: RecordResource,
    filters: tuple[Any, ...] = (),
    order: tuple[Any, ...] = (),
    timezone_name: str | None = None,
):
    if resource not in {"surveys", *(_MASTER_FIELDS.keys())}:
        raise ValueError("Unknown analytics record resource")
    resolve_timezone(timezone_name)
    fields = fields_for(resource)
    query = _base_query(db, resource)
    for item in filters:
        if resource == "surveys" and item.member in _ASSIGNMENT_FIELDS:
            query = query.filter(_assignment_condition(item, timezone_name))
            continue
        field = fields.get(item.member)
        if field is None:
            raise ValueError(f"Unknown field for {resource}: {item.member}")
        operator, value = _filter_parts(item, field, timezone_name)
        query = query.filter(_condition(field.expression, operator, value))
    order_clauses = []
    for item in order:
        field = fields.get(item.member)
        if field is None:
            raise ValueError(f"Unknown order field for {resource}: {item.member}")
        order_clauses.append(
            field.expression.desc() if item.direction == "desc" else field.expression.asc()
        )
    primary = "id" if resource != "stores" else "store_key"
    if not order:
        order_clauses = [
            fields["reported_at"].expression.desc(),
            fields["id"].expression.desc(),
        ] if resource == "surveys" else [fields[primary].expression.asc()]
    return query.order_by(*order_clauses)


def serialize_record(resource: RecordResource, record: Any, timezone_name: str | None):
    if resource == "surveys":
        return record.to_dict(timezone_name)
    return record.to_dict()


def query_records(
    db: Session,
    resource: RecordResource,
    filters: tuple[Any, ...],
    order: tuple[Any, ...],
    page: int,
    size: int,
    timezone_name: str | None,
) -> dict[str, Any]:
    query = build_record_query(db, resource, filters, order, timezone_name)
    total = query.order_by(None).count()
    records = query.offset((page - 1) * size).limit(size).all()
    items = [serialize_record(resource, record, timezone_name) for record in records]
    return {
        "resource": resource,
        "representation": "full",
        "items": items,
        "page": page,
        "size": size,
        "total": total,
        "has_more": page * size < total,
        "timezone": timezone_name or "UTC",
    }


_PROJECTED_CORE_EXPRESSIONS = {
    slug: field.expression for slug, field in _SURVEY_FIELDS.items()
}


def _raw_expression(source_key: str, field_type: FieldType):
    helper = {
        FieldType.STRING: func.analytics_raw_value,
        FieldType.NUMBER: func.analytics_raw_number,
        FieldType.BOOLEAN: func.analytics_raw_boolean,
        # Candidate inference uses "date" for both ISO dates and datetimes.
        # Preserve timestamps so projected records agree with Cube time grains.
        FieldType.DATE: func.analytics_raw_timestamp,
        FieldType.TIME: func.analytics_raw_time,
    }[field_type]
    return helper(Survey.raw_row_data, source_key)


def _projected_expression(
    field: CatalogField,
    raw_fields: dict[str, tuple[str, FieldType]],
):
    if field.slug in _PROJECTED_CORE_EXPRESSIONS:
        return _PROJECTED_CORE_EXPRESSIONS[field.slug]
    raw_definition = raw_fields.get(field.slug)
    if raw_definition is None:
        raise ValueError(f"Projected record field {field.slug} has no governed source")
    return _raw_expression(raw_definition[0], FieldType(raw_definition[1]))


def _catalog_filter(item: Any) -> FilterSpec:
    """Convert the record filter aliases into the catalog filter contract."""

    value = item.value
    values = item.values
    if item.operator in {"in", "not_in", "between"} and values is None:
        if isinstance(value, (list, tuple)):
            values = tuple(value)
            value = None
    return FilterSpec(
        member=item.member,
        operator=item.operator,
        value=value,
        values=values,
    )


def build_projected_record_statement(
    *,
    fields: tuple[str, ...],
    filters: tuple[Any, ...],
    cursor: int | None,
    size: int,
    timezone_name: str | None,
    catalog: SemanticCatalog,
    role: str,
    raw_fields: dict[str, tuple[str, FieldType]],
) -> Select:
    """Build a role-scoped flat survey projection with stable cursor ordering."""

    resolve_timezone(timezone_name)
    selected_fields: dict[str, CatalogField] = {}
    for slug in fields:
        validate_query_fields(
            semantic_view="survey_responses",
            dimensions=[slug],
            filters=[],
            catalog=catalog,
            role=role,
        )
        selected_fields[slug] = catalog.field(slug, "survey_responses")

    catalog_filters = tuple(
        _catalog_filter(item)
        for item in filters
        if item.member not in _ASSIGNMENT_FIELDS
    )
    if catalog_filters:
        validate_query_fields(
            semantic_view="survey_responses",
            dimensions=[],
            filters=catalog_filters,
            catalog=catalog,
            role=role,
        )

    selected = [
        _projected_expression(field, raw_fields).label(slug)
        for slug, field in selected_fields.items()
    ]
    if "id" not in selected_fields:
        selected.append(Survey.id.label("__cursor_id"))
    statement = (
        select(*selected)
        .select_from(Survey)
        .join(Store, Store.store_key == Survey.store_key)
        .outerjoin(Channel, Channel.id == Survey.channel_id)
        .outerjoin(DeliveryService, DeliveryService.id == Survey.delivery_service_id)
        .where(Survey.is_deleted.is_not(True))
    )
    conditions = []
    for item in filters:
        if item.member in _ASSIGNMENT_FIELDS:
            conditions.append(_assignment_condition(item, timezone_name))
            continue
        catalog_field = catalog.field(item.member, "survey_responses")
        expression = _projected_expression(catalog_field, raw_fields)
        filter_item = _catalog_filter(item)
        record_field = RecordField(
            expression,
            catalog_field.data_type,
            is_datetime=(
                catalog_field.data_type is FieldType.DATE
                and (
                    catalog_field.slug in {"reported_at", "created_at", "updated_at"}
                    or catalog_field.slug not in _PROJECTED_CORE_EXPRESSIONS
                )
            ),
        )
        operator, value = _filter_parts(filter_item, record_field, timezone_name)
        conditions.append(_condition(expression, operator, value))
    if conditions:
        statement = statement.where(and_(*conditions))
    if cursor is not None:
        statement = statement.where(Survey.id > cursor)
    return statement.order_by(Survey.id.asc()).limit(size + 1)


def _json_value(value: Any, timezone_name: str | None = None) -> Any:
    if hasattr(value, "value"):
        return value.value
    if isinstance(value, (date, datetime, time)):
        if isinstance(value, datetime):
            value = as_timezone(value, timezone_name)
        return value.isoformat()
    return value


def execute_projected_records(
    db: Any,
    *,
    fields: tuple[str, ...],
    filters: tuple[Any, ...],
    cursor: int | None,
    size: int,
    timezone_name: str | None,
    catalog: SemanticCatalog,
    role: str,
    raw_fields: dict[str, tuple[str, FieldType]],
) -> dict[str, Any]:
    """Execute one bounded projected-record page with the legacy DB guardrails."""

    if hasattr(db, "get_bind") and db.get_bind().dialect.name == "postgresql":
        db.execute(
            text("SELECT set_config('statement_timeout', :timeout, true)"),
            {"timeout": f"{config.ANALYTICS_DRILLDOWN_STATEMENT_TIMEOUT_MS}ms"},
        )
    result = db.execute(
        build_projected_record_statement(
            fields=fields,
            filters=filters,
            cursor=cursor,
            size=size,
            timezone_name=timezone_name,
            catalog=catalog,
            role=role,
            raw_fields=raw_fields,
        )
    ).mappings().all()
    has_more = len(result) > size
    page = result[:size]
    items = [
        {
            key: _json_value(value, timezone_name)
            for key, value in dict(row).items()
            if key != "__cursor_id"
        }
        for row in page
    ]
    next_cursor = None
    if has_more and page:
        last = dict(page[-1])
        next_cursor = int(last.get("id") or last.get("__cursor_id"))
    return {
        "items": items,
        "next_cursor": next_cursor,
        "has_more": has_more,
    }
