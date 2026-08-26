"""Governed cursor-paginated survey drilldown queries."""
from __future__ import annotations

from datetime import date, datetime, time, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import Select, and_, func, select, text

import config

from models.Channel import Channel
from models.DeliveryService import DeliveryService
from models.Store import Store
from models.Survey import Survey
from utils.analytics import (
    CatalogField,
    FieldType,
    FilterSpec,
    QuerySpec,
    SemanticCatalog,
    validate_identifier,
    validate_query,
)
from utils.utc import as_timezone, resolve_timezone


DEFAULT_DRILLDOWN_FIELDS = (
    "id",
    "survey_id",
    "reported_at",
    "store_key",
    "store_name",
    "topic_sentiment",
    "comment",
)


class DrilldownSpec(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        json_schema_extra={
            "examples": [
                {
                    "fields": [
                        "survey_id",
                        "respondent_id",
                        "reported_at",
                        "store_key",
                        "topic_sentiment",
                        "topic_sentiment_score",
                        "cls",
                        "comment",
                    ],
                    "filters": [
                        {
                            "member": "topic_sentiment",
                            "operator": "equals",
                            "value": "NEGATIVE",
                        }
                    ],
                    "cursor": 0,
                    "limit": 100,
                    "timezone": "Asia/Hong_Kong",
                }
            ]
        },
    )

    semantic_view: Literal["survey_responses"] = Field(
        default="survey_responses",
        description=(
            "Drilldown is intentionally limited to one survey-response row; "
            "topic, department, and keyword assignment views are aggregate-only."
        ),
    )
    fields: tuple[str, ...] = Field(default=DEFAULT_DRILLDOWN_FIELDS, max_length=50)
    filters: tuple[FilterSpec, ...] = Field(default=(), max_length=20)
    cursor: int | None = Field(default=None, ge=0)
    limit: int = Field(default=100, ge=1, le=250)
    timezone: str | None = Field(
        default=None,
        description=(
            "Optional IANA timezone used for timestamp filters and returned values; "
            "UTC is used when omitted."
        ),
    )

    @field_validator("fields")
    @classmethod
    def _safe_unique_fields(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if not values:
            raise ValueError("Drilldown requires at least one field")
        for value in values:
            validate_identifier(value)
        if len(set(values)) != len(values):
            raise ValueError("Drilldown fields must be unique")
        return values

    @field_validator("timezone")
    @classmethod
    def _timezone(cls, value: str | None) -> str | None:
        if value is not None:
            resolve_timezone(value)
        return value


_CORE_EXPRESSIONS = {
    "id": Survey.id,
    "survey_id": Survey.survey_id,
    "respondent_id": Survey.respondent_id,
    "reported_at": Survey.reported_at,
    "created_at": Survey.created_at,
    "updated_at": Survey.updated_at,
    "comment": Survey.comment,
    "topic_sentiment": Survey.topic_sentiment,
    "topic_sentiment_score": Survey.topic_sentiment_score,
    "cls": Survey.cls,
    "store_key": Survey.store_key,
    "store_name": func.coalesce(Store.store_name_english, Store.store_name_local),
    "store_name_english": Store.store_name_english,
    "store_name_local": Store.store_name_local,
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
    "channel_name": Channel.name,
    "delivery_service_name": DeliveryService.name,
}


def _raw_expression(source_key: str, field_type: FieldType):
    helper = {
        FieldType.STRING: func.analytics_raw_value,
        FieldType.NUMBER: func.analytics_raw_number,
        FieldType.BOOLEAN: func.analytics_raw_boolean,
        # Candidate inference uses "date" for both ISO dates and datetimes.
        # Preserve timestamps (date-only values become midnight) so drilldown
        # agrees with Cube's second-through-year granularities.
        FieldType.DATE: func.analytics_raw_timestamp,
        FieldType.TIME: func.analytics_raw_time,
    }[field_type]
    return helper(Survey.raw_row_data, source_key)


def _expression(
    field: CatalogField,
    raw_fields: dict[str, tuple[str, FieldType]],
):
    if field.slug in _CORE_EXPRESSIONS:
        return _CORE_EXPRESSIONS[field.slug]
    raw_definition = raw_fields.get(field.slug)
    if raw_definition is None:
        raise ValueError(f"Drilldown field {field.slug} has no governed source")
    return _raw_expression(raw_definition[0], FieldType(raw_definition[1]))


def _timestamp_filter_value(value: Any, timezone_name: str | None) -> Any:
    if isinstance(value, datetime):
        timestamp = value
    elif isinstance(value, date):
        timestamp = datetime.combine(value, time.min)
    elif isinstance(value, str):
        try:
            timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return value
    else:
        return value
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=resolve_timezone(timezone_name))
    return timestamp.astimezone(timezone.utc)


def _normalise_filter(item: FilterSpec, field_type: FieldType, timezone_name: str | None) -> FilterSpec:
    if field_type is not FieldType.DATE:
        return item
    if item.values is not None:
        values = tuple(_timestamp_filter_value(value, timezone_name) for value in item.values)
        return item.model_copy(update={"values": values})
    if item.value is not None:
        return item.model_copy(
            update={"value": _timestamp_filter_value(item.value, timezone_name)}
        )
    return item


def _condition(expression: Any, item: FilterSpec):
    if item.operator == "equals":
        return expression == item.value
    if item.operator == "not_equals":
        return expression != item.value
    if item.operator == "contains":
        return expression.contains(item.value)
    if item.operator == "not_contains":
        return ~expression.contains(item.value)
    if item.operator == "starts_with":
        return expression.startswith(item.value)
    if item.operator == "ends_with":
        return expression.endswith(item.value)
    if item.operator == "greater_than":
        return expression > item.value
    if item.operator == "greater_than_or_equal":
        return expression >= item.value
    if item.operator == "less_than":
        return expression < item.value
    if item.operator == "less_than_or_equal":
        return expression <= item.value
    if item.operator == "in":
        return expression.in_(item.values)
    if item.operator == "not_in":
        return expression.not_in(item.values)
    if item.operator == "set":
        return expression.is_not(None)
    if item.operator == "not_set":
        return expression.is_(None)
    if item.operator == "between":
        assert item.values is not None
        return expression.between(item.values[0], item.values[1])
    raise ValueError("Unsupported drilldown filter")


def build_drilldown_statement(
    spec: DrilldownSpec,
    catalog: SemanticCatalog,
    *,
    role: str,
    raw_fields: dict[str, tuple[str, FieldType]],
) -> Select:
    fields: dict[str, CatalogField] = {}
    for slug in spec.fields:
        validate_query(
            QuerySpec(semantic_view=spec.semantic_view, dimensions=[slug], limit=1),
            catalog,
            role,
        )
        fields[slug] = catalog.field(slug, spec.semantic_view)
    if spec.filters:
        validate_query(
            QuerySpec(
                semantic_view=spec.semantic_view,
                dimensions=[spec.fields[0]],
                filters=spec.filters,
                limit=1,
            ),
            catalog,
            role,
        )

    selected = [_expression(field, raw_fields).label(slug) for slug, field in fields.items()]
    if "id" not in fields:
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
    for item in spec.filters:
        field = catalog.field(item.member, spec.semantic_view)
        normalized_item = _normalise_filter(item, field.data_type, spec.timezone)
        conditions.append(_condition(_expression(field, raw_fields), normalized_item))
    if conditions:
        statement = statement.where(and_(*conditions))
    if spec.cursor is not None:
        statement = statement.where(Survey.id > spec.cursor)
    return statement.order_by(Survey.id.asc()).limit(spec.limit + 1)


def _json_value(value: Any, timezone_name: str | None = None) -> Any:
    if hasattr(value, "value"):
        return value.value
    if isinstance(value, (date, datetime, time)):
        if isinstance(value, datetime):
            value = as_timezone(value, timezone_name)
        return value.isoformat()
    return value


def execute_drilldown(
    db: Any,
    spec: DrilldownSpec,
    catalog: SemanticCatalog,
    *,
    role: str,
    raw_fields: dict[str, tuple[str, FieldType]],
) -> dict[str, Any]:
    if hasattr(db, "get_bind") and db.get_bind().dialect.name == "postgresql":
        db.execute(
            text("SELECT set_config('statement_timeout', :timeout, true)"),
            {"timeout": f"{config.ANALYTICS_DRILLDOWN_STATEMENT_TIMEOUT_MS}ms"},
        )
    result = db.execute(
        build_drilldown_statement(spec, catalog, role=role, raw_fields=raw_fields)
    ).mappings().all()
    has_more = len(result) > spec.limit
    page = result[: spec.limit]
    rows = [
        {
            key: _json_value(value, spec.timezone)
            for key, value in dict(row).items()
            if key != "__cursor_id"
        }
        for row in page
    ]
    next_cursor = None
    if has_more and page:
        last = dict(page[-1])
        next_cursor = int(last.get("id") or last.get("__cursor_id"))
    return {"rows": rows, "next_cursor": next_cursor, "has_more": has_more}
