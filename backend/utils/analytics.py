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
from utils.utc import resolve_timezone


MAX_DIMENSIONS = 3
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


class QueryAggregation(str, Enum):
    COUNT = "count"
    DISTINCT_COUNT = "distinct_count"
    SUM = "sum"
    AVERAGE = "average"
    MIN = "min"
    MAX = "max"
    MEDIAN = "median"


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

SIMPLE_AGGREGATIONS = frozenset(
    {
        Aggregation.COUNT,
        Aggregation.DISTINCT_COUNT,
        Aggregation.SUM,
        Aggregation.AVERAGE,
        Aggregation.MIN,
        Aggregation.MAX,
        Aggregation.MEDIAN,
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


def allowed_query_aggregations(
    field_type: FieldType | str,
) -> frozenset[Aggregation]:
    """Return the intentionally small aggregate-query surface for a raw field."""

    field_type = FieldType(field_type)
    result = {Aggregation.COUNT, Aggregation.DISTINCT_COUNT}
    if field_type is FieldType.NUMBER:
        result.update(
            {
                Aggregation.SUM,
                Aggregation.AVERAGE,
                Aggregation.MIN,
                Aggregation.MAX,
                Aggregation.MEDIAN,
            }
        )
    elif field_type in {FieldType.DATE, FieldType.TIME}:
        result.update({Aggregation.MIN, Aggregation.MAX})
    return frozenset(result)


class _CatalogModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, use_enum_values=False)

    slug: str
    label: str = Field(min_length=1, max_length=200)
    semantic_view: str = Field(
        description=(
            "Required row grain: survey_responses is one survey response; "
            "survey_topics, survey_departments, and survey_keywords are one "
            "assignment row each. In assignment views, sentiment is assignment "
            "sentiment and topic_sentiment is the canonical surveys.topic_sentiment."
        )
    )
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
    scope: Literal["response", "assignment"] = "response"
    usage: Literal["chart", "table_only"] = "table_only"
    filterable: bool = True
    time_dimension: bool = False
    kind: Literal[MemberKind.DIMENSION] = MemberKind.DIMENSION

    @model_validator(mode="after")
    def _time_dimension_type(self) -> "CatalogField":
        if self.time_dimension and self.data_type not in {FieldType.DATE, FieldType.TIME}:
            raise ValueError("time dimensions must use a date or time field")
        return self


class CatalogMetric(_CatalogModel):
    aggregation: Aggregation
    source_field: str | None = None
    query_target: str | None = None
    public_aggregation: QueryAggregation | None = None
    entity: str | None = None
    weight_field: str | None = None
    percentile: float | None = None
    confidence_level: float | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    kind: Literal[MemberKind.METRIC] = MemberKind.METRIC

    @field_validator("source_field", "weight_field", "query_target", "entity")
    @classmethod
    def _safe_optional_identifier(cls, value: str | None) -> str | None:
        return validate_identifier(value) if value is not None else None

    @model_validator(mode="after")
    def _public_target_contract(self) -> "CatalogMetric":
        if (self.query_target is None) != (self.public_aggregation is None):
            raise ValueError(
                "query_target and public_aggregation must be supplied together"
            )
        return self

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


class MetricAggregationOption(BaseModel):
    """One public method supported by a logical business metric target."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    method: QueryAggregation
    label: str
    result_type: FieldType
    cube_metric: str = Field(exclude=True)


class MetricTarget(BaseModel):
    """A business entity or value users can measure in one semantic view."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    metric: str = Field(
        description=(
            "Logical business target such as survey, keyword_assignment, store, or cls; "
            "physical fields and Cube measure names are not accepted"
        )
    )
    label: str
    entity: str
    aggregations: tuple[MetricAggregationOption, ...]


def metric_result_type(
    metric: CatalogMetric, catalog: SemanticCatalog
) -> FieldType:
    if metric.public_aggregation in {QueryAggregation.MIN, QueryAggregation.MAX}:
        if metric.source_field is None:
            return FieldType.NUMBER
        field = catalog.field(metric.source_field, metric.semantic_view)
        if field.data_type in {FieldType.DATE, FieldType.TIME}:
            return field.data_type
    return FieldType.NUMBER


def _metric_target_candidates(
    catalog: SemanticCatalog,
    semantic_view: str,
    target: str,
    aggregation: QueryAggregation,
    role: str,
) -> list[CatalogMetric]:
    return [
        metric
        for metric in catalog.metrics
        if metric.semantic_view == semantic_view
        and metric.query_target == target
        and metric.public_aggregation is aggregation
        and metric.aggregation in SIMPLE_AGGREGATIONS
        and _visible(metric, role)
    ]


def resolve_query_metric(
    query: "QuerySpec",
    catalog: SemanticCatalog,
    role: str = "viewer",
) -> CatalogMetric:
    """Resolve a logical metric target/method to one governed Cube measure."""

    matches = _metric_target_candidates(
        catalog, query.semantic_view, query.metric, query.aggregation, role
    )
    if not matches:
        raise AnalyticsValidationError(
            f"Metric target {query.metric}/{query.aggregation.value} is not published"
        )
    if len(matches) != 1:
        raise AnalyticsValidationError(
            f"Metric target {query.metric}/{query.aggregation.value} is ambiguous"
        )
    validate_metric(matches[0], catalog)
    return matches[0]


def metric_targets(
    catalog: SemanticCatalog,
    semantic_view: str,
    role: str = "viewer",
) -> tuple[MetricTarget, ...]:
    """List unique logical metric targets for one semantic view."""

    if role not in {"viewer", "admin"}:
        raise AnalyticsValidationError("Unknown analytics role")
    pairs = {
        (metric.query_target, metric.public_aggregation)
        for metric in catalog.metrics
        if metric.semantic_view == semantic_view
        and metric.query_target is not None
        and metric.public_aggregation is not None
        and metric.aggregation in SIMPLE_AGGREGATIONS
        and _visible(metric, role)
    }
    by_target: dict[str, list[MetricAggregationOption]] = {}
    target_labels: dict[str, str] = {}
    target_entities: dict[str, str] = {}
    for target, aggregation in sorted(
        pairs, key=lambda pair: (str(pair[0]), str(pair[1]))
    ):
        assert target is not None and aggregation is not None
        matches = _metric_target_candidates(
            catalog, semantic_view, target, aggregation, role
        )
        if len(matches) != 1:
            continue
        governed = matches[0]
        try:
            validate_metric(governed, catalog)
        except AnalyticsValidationError:
            continue
        entity = governed.entity or target
        target_labels.setdefault(target, entity.replace("_", " ").title())
        target_entities.setdefault(target, entity)
        by_target.setdefault(target, []).append(
            MetricAggregationOption(
                method=aggregation,
                label=governed.label,
                result_type=metric_result_type(governed, catalog),
                cube_metric=governed.slug,
            )
        )
    return tuple(
        MetricTarget(
            metric=target,
            label=target_labels[target],
            entity=target_entities[target],
            aggregations=tuple(
                sorted(by_target[target], key=lambda item: item.method.value)
            ),
        )
        for target in sorted(by_target)
    )

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


def allowed_filter_operators(field_type: FieldType | str) -> tuple[str, ...]:
    """Return the public operators accepted by the typed filter validator."""

    field_type = FieldType(field_type)
    operators = {
        "equals",
        "not_equals",
        "in",
        "not_in",
        "set",
        "not_set",
    }
    if field_type is FieldType.STRING:
        operators.update(
            {"contains", "not_contains", "starts_with", "ends_with"}
        )
    if field_type in {FieldType.NUMBER, FieldType.DATE, FieldType.TIME}:
        operators.update(
            {
                "greater_than",
                "greater_than_or_equal",
                "less_than",
                "less_than_or_equal",
                "between",
            }
        )
    return tuple(sorted(operators))


class FilterSpec(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        json_schema_extra={
            "examples": [
                {
                    "member": "topic_sentiment",
                    "operator": "equals",
                    "value": "NEGATIVE",
                },
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
        json_schema_extra={"examples": [{"member": "value", "direction": "desc"}]},
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
                    "metric": "cls",
                    "aggregation": "average",
                    "filters": [
                        {
                            "member": "topic_sentiment",
                            "operator": "equals",
                            "value": "NEGATIVE",
                        }
                    ],
                    "time_dimension": "reported_at",
                    "time_range": ["2024-08-01", "2024-08-31"],
                    "time_granularity": "month",
                    "timezone": "Asia/Hong_Kong",
                    "order": [{"member": "value", "direction": "desc"}],
                    "limit": 1000,
                }
            ]
        },
    )

    semantic_view: str = Field(
        description=(
            "Required row grain: survey_responses is one survey response; "
            "survey_topics, survey_departments, and survey_keywords are one "
            "assignment row each. In assignment views, sentiment is assignment "
            "sentiment and topic_sentiment is the canonical surveys.topic_sentiment."
        )
    )
    dimensions: tuple[str, ...] = Field(default=(), max_length=MAX_DIMENSIONS)
    metric: str = Field(
        description=(
            "Logical business target such as survey, keyword_assignment, store, or cls; "
            "physical fields and Cube measure names are not accepted"
        )
    )
    aggregation: QueryAggregation
    filters: tuple[FilterSpec, ...] = Field(default=(), max_length=MAX_FILTERS)
    time_dimension: str | None = None
    time_range: tuple[str, str] | None = None
    timezone: str | None = Field(
        default=None,
        description=(
            "Optional IANA timezone used for time-range boundaries and time buckets; "
            "UTC is used when omitted."
        ),
    )
    time_granularity: Literal[
        "second", "minute", "hour", "day", "week", "month", "quarter", "year"
    ] | None = None
    order: tuple[OrderSpec, ...] = Field(default=(), max_length=8)
    limit: int = Field(default=MAX_AGGREGATE_ROWS, ge=1, le=MAX_AGGREGATE_ROWS)

    @field_validator("semantic_view")
    @classmethod
    def _view_identifier(cls, value: str) -> str:
        return validate_identifier(value)

    @field_validator("dimensions")
    @classmethod
    def _member_identifiers(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        for value in values:
            validate_identifier(value)
        if len(set(values)) != len(values):
            raise ValueError("query members must not be duplicated")
        return values

    @field_validator("metric")
    @classmethod
    def _metric_identifier(cls, value: str) -> str:
        return validate_identifier(value)

    @field_validator("aggregation")
    @classmethod
    def _simple_aggregation(cls, value: QueryAggregation) -> QueryAggregation:
        return value

    @field_validator("time_dimension")
    @classmethod
    def _time_identifier(cls, value: str | None) -> str | None:
        return validate_identifier(value) if value is not None else None

    @field_validator("timezone")
    @classmethod
    def _timezone(cls, value: str | None) -> str | None:
        if value is not None:
            resolve_timezone(value)
        return value

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
        if "value" in self.dimensions or self.time_dimension == "value":
            raise ValueError("value is the reserved output key for the selected metric")
        if (self.time_range is not None or self.time_granularity is not None) and not self.time_dimension:
            raise ValueError("time range and granularity require a time dimension")
        if self.time_dimension in self.dimensions:
            raise ValueError(
                "a time dimension must not also be selected as a raw dimension"
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
        if filter_spec.value is not None:
            raise AnalyticsValidationError(
                f"Filter {filter_spec.operator} does not accept value"
            )
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


def validate_query_fields(
    *,
    semantic_view: str,
    dimensions: tuple[str, ...] | list[str],
    filters: tuple[FilterSpec, ...] | list[FilterSpec],
    catalog: SemanticCatalog,
    role: str = "viewer",
    time_dimension: str | None = None,
) -> None:
    """Validate dimensions and filters for aggregate queries and drilldowns."""

    if role not in {"viewer", "admin"}:
        raise AnalyticsValidationError("Unknown analytics role")
    if semantic_view not in catalog.views:
        raise AnalyticsValidationError("Unknown semantic view")
    for slug in dimensions:
        field = catalog.field(slug, semantic_view)
        _ensure_query_member(field, semantic_view, role)
    if time_dimension:
        time_field = catalog.field(time_dimension, semantic_view)
        _ensure_query_member(time_field, semantic_view, role)
        if time_field.data_type not in {FieldType.DATE, FieldType.TIME}:
            raise AnalyticsValidationError("Time dimension must be a date or time field")
        if not time_field.time_dimension:
            raise AnalyticsValidationError(
                "Selected field is not a granular time dimension"
            )
    for filter_spec in filters:
        field = catalog.field(filter_spec.member, semantic_view)
        _ensure_query_member(field, semantic_view, role)
        if not field.filterable:
            raise AnalyticsValidationError(
                f"Dimension {field.slug} is not available for filtering"
            )
        _validate_filter(filter_spec, field)


def validate_query(
    query: QuerySpec | dict[str, Any],
    catalog: SemanticCatalog,
    role: str = "viewer",
) -> QuerySpec:
    query = query if isinstance(query, QuerySpec) else QuerySpec.model_validate(query)
    validate_query_fields(
        semantic_view=query.semantic_view,
        dimensions=query.dimensions,
        filters=query.filters,
        catalog=catalog,
        role=role,
        time_dimension=query.time_dimension,
    )
    resolve_query_metric(query, catalog, role)

    selected = {*query.dimensions, "value"}
    if query.time_dimension:
        selected.add(query.time_dimension)
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


def _cube_value(
    value: Any,
    field_type: FieldType | None = None,
    timezone_name: str | None = None,
) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if field_type is FieldType.DATE:
        if isinstance(value, datetime):
            timestamp = value
        elif isinstance(value, date):
            timestamp = datetime.combine(value, time.min)
        elif isinstance(value, str):
            try:
                timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                timestamp = None
        else:
            timestamp = None
        if timestamp is not None:
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=resolve_timezone(timezone_name))
            return timestamp.astimezone(timezone.utc).isoformat()
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
    metric = resolve_query_metric(query, catalog, role)
    result: dict[str, Any] = {
        "dimensions": [prefix + slug for slug in query.dimensions],
        "measures": [prefix + metric.slug],
    }

    filters: list[dict[str, Any]] = []
    for item in query.filters:
        field = catalog.field(item.member, query.semantic_view)
        if item.operator == "between":
            assert item.values is not None
            filters.extend(
                [
                    {
                        "member": prefix + item.member,
                        "operator": "gte",
                        "values": [
                            _cube_value(
                                item.values[0], field.data_type, query.timezone
                            )
                        ],
                    },
                    {
                        "member": prefix + item.member,
                        "operator": "lte",
                        "values": [
                            _cube_value(
                                item.values[1], field.data_type, query.timezone
                            )
                        ],
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
            compiled_filter["values"] = [
                _cube_value(value, field.data_type, query.timezone)
                for value in values
            ]
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
    if query.timezone is not None:
        result["timezone"] = query.timezone
    if query.order:
        result["order"] = {
            (prefix + metric.slug if order.member == "value" else prefix + order.member): order.direction
            for order in query.order
        }
    result["limit"] = query.limit
    return result


CHART_COMBINATION_RULES: tuple[dict[str, Any], ...] = (
    {
        "chart_type": "kpi",
        "min_dimensions": 0,
        "max_dimensions": 0,
        "time_dimension": "forbidden",
        "requires_time_granularity": False,
        "numeric_metric_required": False,
        "exact_metric_count": 1,
    },
    {
        "chart_type": "table",
        "min_dimensions": 0,
        "max_dimensions": MAX_DIMENSIONS,
        "time_dimension": "optional",
        "requires_time_granularity": False,
        "numeric_metric_required": False,
        "exact_metric_count": 1,
    },
    *(
        {
            "chart_type": chart_type,
            "min_dimensions": 1,
            "max_dimensions": 1,
            "time_dimension": "forbidden",
            "requires_time_granularity": False,
            "numeric_metric_required": True,
            "exact_metric_count": 1,
        }
        for chart_type in ("bar", "column", "pie", "donut")
    ),
    *(
        {
            "chart_type": chart_type,
            "min_dimensions": 2,
            "max_dimensions": 2,
            "time_dimension": "forbidden",
            "requires_time_granularity": False,
            "numeric_metric_required": True,
            "exact_metric_count": 1,
        }
        for chart_type in ("stacked_bar", "heatmap")
    ),
    *(
        {
            "chart_type": chart_type,
            "min_dimensions": 0,
            "max_dimensions": 1,
            "time_dimension": "required",
            "requires_time_granularity": True,
            "numeric_metric_required": True,
            "exact_metric_count": 1,
        }
        for chart_type in ("line", "area")
    ),
)
_CHART_RULES_BY_TYPE = {
    rule["chart_type"]: rule for rule in CHART_COMBINATION_RULES
}


def chart_combination_rules() -> tuple[dict[str, Any], ...]:
    """Return defensive copies of the chart contract used by validation."""

    return tuple(dict(rule) for rule in CHART_COMBINATION_RULES)


def validate_chart_definition(
    chart_type: str,
    dimensions: list[str] | tuple[str, ...],
    metric: str,
    aggregation: QueryAggregation | Aggregation | str,
    catalog: SemanticCatalog | None = None,
    *,
    semantic_view: str | None = None,
    time_dimension: str | None = None,
    time_granularity: str | None = None,
    role: str = "viewer",
) -> None:
    """Validate chart arity before a definition can be published."""

    rule = _CHART_RULES_BY_TYPE.get(chart_type)
    if rule is None:
        raise AnalyticsValidationError("Unsupported chart type")
    for member in (*dimensions, metric):
        validate_identifier(member)
    aggregation = Aggregation(aggregation)
    if aggregation not in SIMPLE_AGGREGATIONS:
        raise AnalyticsValidationError("Unsupported simple-query aggregation")
    if time_dimension is not None:
        validate_identifier(time_dimension)
        if time_dimension in dimensions:
            raise AnalyticsValidationError(
                "Granular time dimensions must not be duplicated as ordinary dimensions"
            )
    time_mode = rule["time_dimension"]
    valid = rule["min_dimensions"] <= len(dimensions) <= rule["max_dimensions"]
    valid = valid and not (time_mode == "forbidden" and time_dimension is not None)
    valid = valid and not (time_mode == "required" and time_dimension is None)
    if rule["requires_time_granularity"]:
        valid = valid and time_granularity is not None
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
        query = QuerySpec(
            semantic_view=semantic_view,
            dimensions=dimensions,
            metric=metric,
            aggregation=aggregation,
            time_dimension=time_dimension,
            time_granularity=time_granularity,
        )
        validate_query(query, catalog, role)
        governed_metric = resolve_query_metric(query, catalog, role)
        if rule["numeric_metric_required"] and metric_result_type(
            governed_metric, catalog
        ) is not FieldType.NUMBER:
            raise AnalyticsValidationError(
                f"Chart type {chart_type} requires a numeric metric"
            )
        if chart_type != "table":
            table_only = [
                slug
                for slug in dimensions
                if catalog.field(slug, semantic_view).usage == "table_only"
            ]
            if table_only:
                raise AnalyticsValidationError(
                    "Table-only dimensions require chart type table"
                )
        if time_dimension is not None:
            time_field = catalog.field(time_dimension, semantic_view)
            _ensure_query_member(time_field, semantic_view, role)
            if time_field.data_type not in {FieldType.DATE, FieldType.TIME}:
                raise AnalyticsValidationError("Time dimension must be a date or time field")
            if not time_field.time_dimension:
                raise AnalyticsValidationError(
                    "Selected field is not a granular time dimension"
                )


def escape_spreadsheet_formula(value: Any) -> Any:
    """Neutralize values that spreadsheet software could execute as formulas."""

    if isinstance(value, str) and value.startswith(
        ("=", "+", "-", "@", "\t", "\r", "\n")
    ):
        return "'" + value
    return value
