"""Governed analytics contracts and Cube query compilation.

This module is the trust boundary between API payloads, locally governed
catalog metadata, and Cube.  Callers may select catalog members, but they can
never submit Cube member names or SQL expressions directly.
"""

from __future__ import annotations

from datetime import date, datetime, time, timezone
from enum import Enum
import math
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


MAX_DIMENSIONS = 3
MAX_METRICS = 5
MAX_FILTERS = 20
MAX_AGGREGATE_ROWS = 1_000

_SAFE_IDENTIFIER = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$")


class AnalyticsValidationError(ValueError):
    """A governed analytics definition or query violates its contract."""


class FieldType(str, Enum):
    STRING = "string"
    NUMBER = "number"
    BOOLEAN = "boolean"
    DATE = "date"
    TIME = "time"


class Visibility(str, Enum):
    VIEWER = "viewer"
    ADMIN = "admin"


class MemberKind(str, Enum):
    DIMENSION = "dimension"
    METRIC = "metric"


class Aggregation(str, Enum):
    COUNT = "count"
    DISTINCT_COUNT = "distinct_count"
    FILTERED_COUNT = "filtered_count"
    FILTERED_RATE = "filtered_rate"
    WEIGHTED_FILTERED_RATE = "weighted_filtered_rate"
    SUM = "sum"
    AVERAGE = "average"
    WEIGHTED_SUM = "weighted_sum"
    WEIGHTED_AVERAGE = "weighted_average"
    MIN = "min"
    MAX = "max"
    VARIANCE_SAMPLE = "variance_sample"
    VARIANCE_POPULATION = "variance_population"
    WEIGHTED_VARIANCE_SAMPLE = "weighted_variance_sample"
    WEIGHTED_VARIANCE_POPULATION = "weighted_variance_population"
    STDDEV_SAMPLE = "stddev_sample"
    STDDEV_POPULATION = "stddev_population"
    WEIGHTED_STDDEV_SAMPLE = "weighted_stddev_sample"
    WEIGHTED_STDDEV_POPULATION = "weighted_stddev_population"
    MEDIAN = "median"
    PERCENTILE = "percentile"
    MEAN_CONFIDENCE_INTERVAL = "mean_confidence_interval"
    WEIGHTED_MEAN_CONFIDENCE_INTERVAL = "weighted_mean_confidence_interval"
    PROPORTION_CONFIDENCE_INTERVAL = "proportion_confidence_interval"
    WEIGHTED_PROPORTION_CONFIDENCE_INTERVAL = (
        "weighted_proportion_confidence_interval"
    )


_ALL_TYPE_AGGREGATIONS = frozenset(
    {
        Aggregation.COUNT,
        Aggregation.DISTINCT_COUNT,
        Aggregation.FILTERED_COUNT,
        Aggregation.FILTERED_RATE,
        Aggregation.WEIGHTED_FILTERED_RATE,
        Aggregation.PROPORTION_CONFIDENCE_INTERVAL,
        Aggregation.WEIGHTED_PROPORTION_CONFIDENCE_INTERVAL,
    }
)
_NUMERIC_AGGREGATIONS = frozenset(
    {
        Aggregation.SUM,
        Aggregation.AVERAGE,
        Aggregation.WEIGHTED_SUM,
        Aggregation.WEIGHTED_AVERAGE,
        Aggregation.MIN,
        Aggregation.MAX,
        Aggregation.VARIANCE_SAMPLE,
        Aggregation.VARIANCE_POPULATION,
        Aggregation.WEIGHTED_VARIANCE_SAMPLE,
        Aggregation.WEIGHTED_VARIANCE_POPULATION,
        Aggregation.STDDEV_SAMPLE,
        Aggregation.STDDEV_POPULATION,
        Aggregation.WEIGHTED_STDDEV_SAMPLE,
        Aggregation.WEIGHTED_STDDEV_POPULATION,
        Aggregation.MEDIAN,
        Aggregation.PERCENTILE,
        Aggregation.MEAN_CONFIDENCE_INTERVAL,
        Aggregation.WEIGHTED_MEAN_CONFIDENCE_INTERVAL,
    }
)
_WEIGHTED_AGGREGATIONS = frozenset(
    {
        Aggregation.WEIGHTED_FILTERED_RATE,
        Aggregation.WEIGHTED_SUM,
        Aggregation.WEIGHTED_AVERAGE,
        Aggregation.WEIGHTED_VARIANCE_SAMPLE,
        Aggregation.WEIGHTED_VARIANCE_POPULATION,
        Aggregation.WEIGHTED_STDDEV_SAMPLE,
        Aggregation.WEIGHTED_STDDEV_POPULATION,
        Aggregation.WEIGHTED_MEAN_CONFIDENCE_INTERVAL,
        Aggregation.WEIGHTED_PROPORTION_CONFIDENCE_INTERVAL,
    }
)


def validate_identifier(value: str) -> str:
    """Validate the deliberately narrow identifier grammar used by the catalog."""

    if (
        not isinstance(value, str)
        or len(value) > 63
        or _SAFE_IDENTIFIER.fullmatch(value) is None
    ):
        raise AnalyticsValidationError(
            "Invalid analytics identifier; use 1-63 lowercase snake-case characters"
        )
    return value


def allowed_aggregations(field_type: FieldType | str) -> frozenset[Aggregation]:
    field_type = FieldType(field_type)
    allowed = set(_ALL_TYPE_AGGREGATIONS)
    if field_type is FieldType.NUMBER:
        allowed.update(_NUMERIC_AGGREGATIONS)
    elif field_type in {FieldType.DATE, FieldType.TIME}:
        allowed.update({Aggregation.MIN, Aggregation.MAX})
    return frozenset(allowed)


class _CatalogModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, use_enum_values=False)

    slug: str
    label: str = Field(min_length=1, max_length=200)
    semantic_view: str
    visibility: Visibility = Visibility.VIEWER
    published: bool = True

    @field_validator("slug", "semantic_view")
    @classmethod
    def _safe_identifier(cls, value: str) -> str:
        return validate_identifier(value)

    @field_validator("label")
    @classmethod
    def _non_blank_label(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("label must not be blank")
        return value


class CatalogField(_CatalogModel):
    data_type: FieldType
    kind: Literal[MemberKind.DIMENSION] = MemberKind.DIMENSION


class CatalogMetric(_CatalogModel):
    aggregation: Aggregation
    source_field: str | None = None
    weight_field: str | None = None
    percentile: float | None = None
    confidence_level: float | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    kind: Literal[MemberKind.METRIC] = MemberKind.METRIC

    @field_validator("source_field", "weight_field")
    @classmethod
    def _safe_optional_identifier(cls, value: str | None) -> str | None:
        return validate_identifier(value) if value is not None else None

    @field_validator("percentile")
    @classmethod
    def _valid_percentile(cls, value: float | None) -> float | None:
        if value is not None and (not math.isfinite(value) or not 0 < value < 1):
            raise ValueError("percentile must be a finite fraction between 0 and 1")
        return value

    @field_validator("confidence_level")
    @classmethod
    def _valid_confidence_level(cls, value: float | None) -> float | None:
        if value is not None and (
            not math.isfinite(value) or not 0.8 <= value <= 0.999
        ):
            raise ValueError("confidence_level must be between 0.8 and 0.999")
        return value


class SemanticCatalog(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    fields: tuple[CatalogField, ...] = ()
    metrics: tuple[CatalogMetric, ...] = ()

    @model_validator(mode="after")
    def _unique_members(self) -> "SemanticCatalog":
        keys: set[tuple[str, str]] = set()
        for member in (*self.fields, *self.metrics):
            key = (member.semantic_view, member.slug)
            if key in keys:
                raise ValueError(
                    f"Duplicate analytics member {member.semantic_view}.{member.slug}"
                )
            keys.add(key)
        return self

    @property
    def views(self) -> frozenset[str]:
        return frozenset(
            member.semantic_view for member in (*self.fields, *self.metrics)
        )

    def field(self, slug: str, semantic_view: str | None = None) -> CatalogField:
        slug_matches = [item for item in self.fields if item.slug == slug]
        matches = [
            item
            for item in slug_matches
            if semantic_view is None or item.semantic_view == semantic_view
        ]
        if len(matches) != 1:
            if semantic_view is not None and slug_matches:
                raise AnalyticsValidationError(
                    f"Dimension {slug} belongs to a different semantic view"
                )
            raise AnalyticsValidationError(f"Unknown analytics dimension: {slug}")
        return matches[0]

    def metric(self, slug: str, semantic_view: str | None = None) -> CatalogMetric:
        slug_matches = [item for item in self.metrics if item.slug == slug]
        matches = [
            item
            for item in slug_matches
            if semantic_view is None or item.semantic_view == semantic_view
        ]
        if len(matches) != 1:
            if semantic_view is not None and slug_matches:
                raise AnalyticsValidationError(
                    f"Metric {slug} belongs to a different semantic view"
                )
            raise AnalyticsValidationError(f"Unknown analytics metric: {slug}")
        return matches[0]

    def member(
        self, slug: str, semantic_view: str | None = None
    ) -> CatalogField | CatalogMetric:
        matches = [
            item
            for item in (*self.fields, *self.metrics)
            if item.slug == slug
            and (semantic_view is None or item.semantic_view == semantic_view)
        ]
        if len(matches) != 1:
            raise AnalyticsValidationError(f"Unknown analytics member: {slug}")
        return matches[0]


FilterOperator = Literal[
    "equals",
    "not_equals",
    "contains",
    "not_contains",
    "starts_with",
    "ends_with",
    "greater_than",
    "greater_than_or_equal",
    "less_than",
    "less_than_or_equal",
    "in",
    "not_in",
    "set",
    "not_set",
    "between",
]


class FilterSpec(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        json_schema_extra={
            "examples": [
                {"member": "sentiment", "operator": "equals", "value": "NEGATIVE"},
                {
                    "member": "reported_at",
                    "operator": "between",
                    "values": ["2026-01-01", "2026-03-31"],
                },
            ]
        },
    )

    member: str
    operator: FilterOperator
    value: Any = None
    values: tuple[Any, ...] | None = None

    @field_validator("member")
    @classmethod
    def _member_identifier(cls, value: str) -> str:
        return validate_identifier(value)


class OrderSpec(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        json_schema_extra={"examples": [{"member": "response_count", "direction": "desc"}]},
    )

    member: str
    direction: Literal["asc", "desc"] = "asc"

    @field_validator("member")
    @classmethod
    def _member_identifier(cls, value: str) -> str:
        return validate_identifier(value)


class QuerySpec(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        json_schema_extra={
            "examples": [
                {
                    "semantic_view": "survey_responses",
                    "dimensions": ["store_name_english", "store_format"],
                    "metrics": ["response_count", "cls_average"],
                    "filters": [
                        {
                            "member": "sentiment",
                            "operator": "equals",
                            "value": "NEGATIVE",
                        }
                    ],
                    "time_dimension": "reported_at",
                    "time_range": ["2024-08-01", "2024-08-31"],
                    "time_granularity": "month",
                    "order": [{"member": "response_count", "direction": "desc"}],
                    "limit": 1000,
                }
            ]
        },
    )

    semantic_view: str
    dimensions: tuple[str, ...] = Field(default=(), max_length=MAX_DIMENSIONS)
    metrics: tuple[str, ...] = Field(default=(), max_length=MAX_METRICS)
    filters: tuple[FilterSpec, ...] = Field(default=(), max_length=MAX_FILTERS)
    time_dimension: str | None = None
    time_range: tuple[str, str] | None = None
    time_granularity: Literal[
        "second", "minute", "hour", "day", "week", "month", "quarter", "year"
    ] | None = None
    order: tuple[OrderSpec, ...] = Field(default=(), max_length=8)
    limit: int = Field(default=MAX_AGGREGATE_ROWS, ge=1, le=MAX_AGGREGATE_ROWS)

    @field_validator("semantic_view")
    @classmethod
    def _view_identifier(cls, value: str) -> str:
        return validate_identifier(value)

    @field_validator("dimensions", "metrics")
    @classmethod
    def _member_identifiers(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        for value in values:
            validate_identifier(value)
        if len(set(values)) != len(values):
            raise ValueError("query members must not be duplicated")
        return values

    @field_validator("time_dimension")
    @classmethod
    def _time_identifier(cls, value: str | None) -> str | None:
        return validate_identifier(value) if value is not None else None

    @field_validator("time_range")
    @classmethod
    def _typed_time_range(
        cls, value: tuple[str, str] | None
    ) -> tuple[str, str] | None:
        if value is None:
            return None
        parsed: list[datetime] = []
        for item in value:
            if len(item) > 64:
                raise ValueError("time range values are too long")
            try:
                timestamp = datetime.fromisoformat(item.replace("Z", "+00:00"))
            except ValueError as error:
                raise ValueError("time range values must be ISO-8601 timestamps") from error
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=timezone.utc)
            parsed.append(timestamp.astimezone(timezone.utc))
        if parsed[0] > parsed[1]:
            raise ValueError("time range start must not be after its end")
        return value

    @model_validator(mode="after")
    def _time_contract(self) -> "QuerySpec":
        if (self.time_range is not None or self.time_granularity is not None) and not self.time_dimension:
            raise ValueError("time range and granularity require a time dimension")
        if (
            self.time_granularity is not None
            and self.time_dimension in self.dimensions
        ):
            raise ValueError(
                "a granular time dimension must not also be selected as a raw dimension"
            )
        return self


def _visible(member: _CatalogModel, role: str) -> bool:
    if not member.published:
        return False
    if role == "admin":
        return True
    return member.visibility is Visibility.VIEWER


def _ensure_query_member(
    member: CatalogField | CatalogMetric,
    semantic_view: str,
    role: str,
) -> None:
    if member.semantic_view != semantic_view:
        raise AnalyticsValidationError(
            f"Member {member.slug} belongs to a different semantic view"
        )
    if not _visible(member, role):
        raise AnalyticsValidationError(
            f"Member {member.slug} is not published and visible to role {role}"
        )


def _typed_value_is_valid(value: Any, field_type: FieldType) -> bool:
    if value is None:
        return False
    if field_type is FieldType.NUMBER:
        return (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(float(value))
        )
    if field_type is FieldType.BOOLEAN:
        return isinstance(value, bool)
    if field_type is FieldType.STRING:
        return isinstance(value, str) and len(value) <= 1_000
    if not isinstance(value, (str, date, datetime, time)):
        return False
    if not isinstance(value, str):
        return True
    try:
        if field_type is FieldType.DATE:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        else:
            time.fromisoformat(value)
    except ValueError:
        return False
    return True


def _validate_filter(filter_spec: FilterSpec, field: CatalogField) -> None:
    no_value = {"set", "not_set"}
    multiple_values = {"in", "not_in", "between"}
    text_only = {"contains", "not_contains", "starts_with", "ends_with"}
    comparisons = {
        "greater_than",
        "greater_than_or_equal",
        "less_than",
        "less_than_or_equal",
        "between",
    }

    if filter_spec.operator in no_value:
        if filter_spec.value is not None or filter_spec.values is not None:
            raise AnalyticsValidationError(
                f"Filter {filter_spec.operator} does not accept values"
            )
        return
    if filter_spec.operator in multiple_values:
        values = filter_spec.values
        expected = 2 if filter_spec.operator == "between" else None
        if not values or len(values) > 100 or (expected and len(values) != expected):
            raise AnalyticsValidationError(
                f"Filter {filter_spec.operator} has an invalid values list"
            )
    else:
        if filter_spec.values is not None or filter_spec.value is None:
            raise AnalyticsValidationError(
                f"Filter {filter_spec.operator} requires exactly one value"
            )
        values = (filter_spec.value,)

    if filter_spec.operator in text_only and field.data_type is not FieldType.STRING:
        raise AnalyticsValidationError("Text filter requires a string dimension")
    if filter_spec.operator in comparisons and field.data_type not in {
        FieldType.NUMBER,
        FieldType.DATE,
        FieldType.TIME,
    }:
        raise AnalyticsValidationError(
            "Comparison filter requires a numeric, date, or time dimension"
        )
    if not all(_typed_value_is_valid(value, field.data_type) for value in values):
        type_label = "numeric" if field.data_type is FieldType.NUMBER else field.data_type.value
        raise AnalyticsValidationError(f"Filter requires {type_label} values")


def validate_metric(metric: CatalogMetric, catalog: SemanticCatalog) -> CatalogMetric:
    source: CatalogField | None = None
    if metric.source_field is not None:
        source = catalog.field(metric.source_field, metric.semantic_view)

    source_optional = {Aggregation.COUNT}
    if metric.aggregation not in source_optional and source is None:
        raise AnalyticsValidationError(
            f"Metric {metric.slug} requires a source field"
        )
    if source is not None and metric.aggregation not in allowed_aggregations(
        source.data_type
    ):
        raise AnalyticsValidationError(
            f"Aggregation {metric.aggregation.value} is not valid for {source.data_type.value}"
        )

    if metric.aggregation in _WEIGHTED_AGGREGATIONS:
        if metric.weight_field is None:
            raise AnalyticsValidationError(
                f"Weighted metric {metric.slug} requires a weight field"
            )
        weight = catalog.field(metric.weight_field, metric.semantic_view)
        if weight.data_type is not FieldType.NUMBER:
            raise AnalyticsValidationError("Weight field must be numeric")
    elif metric.weight_field is not None:
        raise AnalyticsValidationError(
            f"Aggregation {metric.aggregation.value} does not support weights"
        )

    if metric.aggregation is Aggregation.PERCENTILE:
        if metric.percentile is None:
            raise AnalyticsValidationError("Percentile metric requires a percentile")
    elif metric.percentile is not None:
        raise AnalyticsValidationError("Only percentile metrics accept a percentile")

    confidence_operations = {
        Aggregation.MEAN_CONFIDENCE_INTERVAL,
        Aggregation.WEIGHTED_MEAN_CONFIDENCE_INTERVAL,
        Aggregation.PROPORTION_CONFIDENCE_INTERVAL,
        Aggregation.WEIGHTED_PROPORTION_CONFIDENCE_INTERVAL,
    }
    if metric.aggregation in confidence_operations:
        if metric.confidence_level is None:
            raise AnalyticsValidationError(
                "Confidence interval metric requires a confidence level"
            )
    elif metric.confidence_level is not None:
        raise AnalyticsValidationError(
            "Only confidence interval metrics accept a confidence level"
        )

    filtered_operations = {
        Aggregation.FILTERED_COUNT,
        Aggregation.FILTERED_RATE,
        Aggregation.WEIGHTED_FILTERED_RATE,
        Aggregation.PROPORTION_CONFIDENCE_INTERVAL,
        Aggregation.WEIGHTED_PROPORTION_CONFIDENCE_INTERVAL,
    }
    if metric.aggregation in filtered_operations:
        filter_definition = metric.parameters.get("filter")
        if not isinstance(filter_definition, dict):
            raise AnalyticsValidationError(
                "Filtered metric requires a structured filter"
            )
        allowed_keys = {"operator", "value", "values"}
        if set(filter_definition) - allowed_keys:
            raise AnalyticsValidationError("Filtered metric has unsupported keys")
        operator = filter_definition.get("operator")
        if operator not in {
            "equals",
            "not_equals",
            "greater_than",
            "greater_than_or_equal",
            "less_than",
            "less_than_or_equal",
            "is_null",
            "is_not_null",
            "in",
        }:
            raise AnalyticsValidationError("Filtered metric has an invalid operator")
        if operator == "in":
            values = filter_definition.get("values")
            if not isinstance(values, list) or not 1 <= len(values) <= 100:
                raise AnalyticsValidationError("Filtered metric has invalid values")
        elif operator not in {"is_null", "is_not_null"} and "value" not in filter_definition:
            raise AnalyticsValidationError("Filtered metric requires a filter value")
    return metric


def validate_query(
    query: QuerySpec | dict[str, Any],
    catalog: SemanticCatalog,
    role: str = "viewer",
) -> QuerySpec:
    query = query if isinstance(query, QuerySpec) else QuerySpec.model_validate(query)
    if role not in {"viewer", "admin"}:
        raise AnalyticsValidationError("Unknown analytics role")
    if query.semantic_view not in catalog.views:
        raise AnalyticsValidationError("Unknown semantic view")
    if not query.dimensions and not query.metrics and not query.time_dimension:
        raise AnalyticsValidationError("Query must select at least one member")

    selected: set[str] = set()
    for slug in query.dimensions:
        field = catalog.field(slug, query.semantic_view)
        _ensure_query_member(field, query.semantic_view, role)
        selected.add(slug)
    for slug in query.metrics:
        metric = catalog.metric(slug, query.semantic_view)
        _ensure_query_member(metric, query.semantic_view, role)
        validate_metric(metric, catalog)
        selected.add(slug)

    if query.time_dimension:
        time_field = catalog.field(query.time_dimension, query.semantic_view)
        _ensure_query_member(time_field, query.semantic_view, role)
        if time_field.data_type not in {FieldType.DATE, FieldType.TIME}:
            raise AnalyticsValidationError("Time dimension must be a date or time field")
        selected.add(query.time_dimension)

    for filter_spec in query.filters:
        field = catalog.field(filter_spec.member, query.semantic_view)
        _ensure_query_member(field, query.semantic_view, role)
        _validate_filter(filter_spec, field)

    for order in query.order:
        if order.member not in selected:
            raise AnalyticsValidationError("Ordering is limited to selected members")
    return query


_CUBE_OPERATORS = {
    "equals": "equals",
    "not_equals": "notEquals",
    "contains": "contains",
    "not_contains": "notContains",
    "starts_with": "startsWith",
    "ends_with": "endsWith",
    "greater_than": "gt",
    "greater_than_or_equal": "gte",
    "less_than": "lt",
    "less_than_or_equal": "lte",
    "in": "equals",
    "not_in": "notEquals",
    "set": "set",
    "not_set": "notSet",
}


def _cube_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (date, datetime, time)):
        return value.isoformat()
    return str(value)


def compile_cube_query(
    query: QuerySpec | dict[str, Any],
    catalog: SemanticCatalog,
    role: str = "viewer",
) -> dict[str, Any]:
    """Validate and compile a governed request into Cube's JSON query format."""

    query = validate_query(query, catalog, role)
    prefix = f"{query.semantic_view}."
    result: dict[str, Any] = {
        "dimensions": [prefix + slug for slug in query.dimensions],
        "measures": [prefix + slug for slug in query.metrics],
    }

    filters: list[dict[str, Any]] = []
    for item in query.filters:
        if item.operator == "between":
            assert item.values is not None
            filters.extend(
                [
                    {
                        "member": prefix + item.member,
                        "operator": "gte",
                        "values": [_cube_value(item.values[0])],
                    },
                    {
                        "member": prefix + item.member,
                        "operator": "lte",
                        "values": [_cube_value(item.values[1])],
                    },
                ]
            )
            continue
        compiled_filter: dict[str, Any] = {
            "member": prefix + item.member,
            "operator": _CUBE_OPERATORS[item.operator],
        }
        if item.operator not in {"set", "not_set"}:
            values = item.values if item.operator in {"in", "not_in"} else (item.value,)
            assert values is not None
            compiled_filter["values"] = [_cube_value(value) for value in values]
        filters.append(compiled_filter)
    if filters:
        result["filters"] = filters

    if query.time_dimension:
        time_dimension: dict[str, Any] = {"dimension": prefix + query.time_dimension}
        if query.time_range:
            time_dimension["dateRange"] = list(query.time_range)
        if query.time_granularity:
            time_dimension["granularity"] = query.time_granularity
        result["timeDimensions"] = [time_dimension]
    if query.order:
        result["order"] = {
            prefix + order.member: order.direction for order in query.order
        }
    result["limit"] = query.limit
    return result


_CHART_TYPES = frozenset(
    {
        "kpi",
        "table",
        "bar",
        "column",
        "stacked_bar",
        "line",
        "area",
        "pie",
        "donut",
        "scatter",
        "heatmap",
        "store_map",
    }
)


def validate_chart_definition(
    chart_type: str,
    dimensions: list[str] | tuple[str, ...],
    metrics: list[str] | tuple[str, ...],
    catalog: SemanticCatalog | None = None,
    *,
    semantic_view: str | None = None,
    role: str = "viewer",
) -> None:
    """Validate chart arity before a definition can be published."""

    if chart_type not in _CHART_TYPES:
        raise AnalyticsValidationError("Unsupported chart type")
    for member in (*dimensions, *metrics):
        validate_identifier(member)
    dimension_count = len(dimensions)
    metric_count = len(metrics)

    valid = False
    if chart_type == "kpi":
        valid = dimension_count == 0 and metric_count == 1
    elif chart_type == "table":
        valid = (
            dimension_count <= MAX_DIMENSIONS
            and metric_count <= MAX_METRICS
            and dimension_count + metric_count > 0
        )
    elif chart_type in {"bar", "column", "line", "area"}:
        valid = 1 <= dimension_count <= MAX_DIMENSIONS and 1 <= metric_count <= MAX_METRICS
    elif chart_type == "stacked_bar":
        valid = dimension_count == 2 and 1 <= metric_count <= MAX_METRICS
    elif chart_type in {"pie", "donut"}:
        valid = dimension_count == 1 and metric_count == 1
    elif chart_type == "scatter":
        valid = dimension_count <= 1 and metric_count == 2
    elif chart_type == "heatmap":
        valid = dimension_count == 2 and metric_count == 1
    elif chart_type == "store_map":
        valid = (
            set(dimensions)
            == {"store_key", "store_name", "latitude", "longitude"}
            and dimension_count == 4
            and metric_count == 1
        )
    if not valid:
        raise AnalyticsValidationError(
            f"Chart type {chart_type} requires a compatible dimension/metric shape"
        )

    if catalog is not None:
        if semantic_view is None:
            raise AnalyticsValidationError(
                "Catalog chart validation requires a semantic view"
            )
        if role not in {"viewer", "admin"}:
            raise AnalyticsValidationError("Unknown analytics role")
        for slug in dimensions:
            member = catalog.field(slug, semantic_view)
            _ensure_query_member(member, semantic_view, role)
        for slug in metrics:
            member = catalog.metric(slug, semantic_view)
            _ensure_query_member(member, semantic_view, role)
            validate_metric(member, catalog)
            if chart_type not in {"kpi", "table"}:
                source = (
                    catalog.field(member.source_field, semantic_view)
                    if member.source_field is not None
                    else None
                )
                if (
                    source is not None
                    and source.data_type in {FieldType.DATE, FieldType.TIME}
                    and member.aggregation in {Aggregation.MIN, Aggregation.MAX}
                ):
                    raise AnalyticsValidationError(
                        f"Chart type {chart_type} requires numeric metrics"
                    )


def escape_spreadsheet_formula(value: Any) -> Any:
    """Neutralize values that spreadsheet software could execute as formulas."""

    if isinstance(value, str) and value.startswith(
        ("=", "+", "-", "@", "\t", "\r", "\n")
    ):
        return "'" + value
    return value
