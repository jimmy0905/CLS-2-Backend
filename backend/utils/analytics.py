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
# A chart stops being readable long before a query stops being valid. Closed
# dimensions stay well inside this ceiling (21 topics, 9 departments), while
# open ones such as keyword or store name need the cap.
MAX_SERIES = 50
DEFAULT_SERIES_LIMIT = 10
DEFAULT_SLICE_LIMIT = 12
OTHER_SERIES_LABEL = "Other"

ChartType = Literal[
    "kpi",
    "table",
    "bar",
    "column",
    "stacked_bar",
    "grouped_bar",
    "line",
    "area",
    "pie",
    "donut",
    "heatmap",
]

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
    FILTERED_DISTINCT_COUNT = "filtered_distinct_count"
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
        Aggregation.FILTERED_DISTINCT_COUNT,
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

# Aggregations a governed metric may use while still being reachable as a public
# metric target. The filtered families are how one enum value becomes its own
# measurable target: the value is baked into the metric definition rather than
# consuming a group-by slot or a caller-supplied filter.
FILTERED_METRIC_AGGREGATIONS = frozenset(
    {
        Aggregation.FILTERED_COUNT,
        Aggregation.FILTERED_DISTINCT_COUNT,
    }
)
PUBLIC_METRIC_AGGREGATIONS = SIMPLE_AGGREGATIONS | FILTERED_METRIC_AGGREGATIONS

# Queries choose the smallest grain that can answer their metric and selected
# members. The combination grain is last because it has assignment fan-out.
SEMANTIC_VIEW_PREFERENCE = (
    "survey_responses",
    "survey_topics",
    "survey_departments",
    "survey_keywords",
    "survey_assignments",
)
ASSIGNMENT_DIMENSION_FAMILIES = {
    "keyword": "keyword",
    "keyword_sentiment": "keyword",
    "department": "department",
    "department_sentiment": "department",
    "topic": "topic",
    "topic_assignment_sentiment": "topic",
}
CROSS_ASSIGNMENT_DIMENSIONS = frozenset(ASSIGNMENT_DIMENSION_FAMILIES)


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


def metric_target_candidates(
    catalog: SemanticCatalog,
    semantic_view: str,
    target: str,
    aggregation: QueryAggregation,
    role: str = "viewer",
) -> list[CatalogMetric]:
    """Return the governed measures a logical target/method pair resolves to.

    A published pair resolves to exactly one measure; an empty result means the
    grain cannot answer that goal, which is what makes this usable as a
    capability check as well as a resolver.
    """

    return [
        metric
        for metric in catalog.metrics
        if metric.semantic_view == semantic_view
        and metric.query_target == target
        and metric.public_aggregation is aggregation
        and metric.aggregation in PUBLIC_METRIC_AGGREGATIONS
        and _visible(metric, role)
    ]


class SemanticViewResolution(BaseModel):
    """The inferred grain plus details useful when no grain can answer a query."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    semantic_view: str | None = None
    views_with_members: tuple[str, ...] = ()
    assignment_families: tuple[str, ...] = ()

    @property
    def crosses_assignment_families(self) -> bool:
        return len(self.assignment_families) > 1


def resolve_semantic_view(
    catalog: SemanticCatalog,
    *,
    target: str | None,
    aggregation: QueryAggregation | None,
    members: tuple[str, ...] | list[str] = (),
    role: str = "viewer",
) -> SemanticViewResolution:
    """Choose the narrowest grain that can answer a logical aggregate query."""

    if role not in {"viewer", "admin"}:
        raise AnalyticsValidationError("Unknown analytics role")

    members = tuple(members)
    known_views = catalog.views
    preferred_views = tuple(
        view for view in SEMANTIC_VIEW_PREFERENCE if view in known_views
    ) + tuple(sorted(known_views - set(SEMANTIC_VIEW_PREFERENCE)))
    assignment_families = tuple(
        sorted(
            {
                ASSIGNMENT_DIMENSION_FAMILIES[member]
                for member in members
                if member in ASSIGNMENT_DIMENSION_FAMILIES
            }
        )
    )
    views_with_members: list[str] = []
    for semantic_view in preferred_views:
        available = {
            field.slug
            for field in catalog.fields
            if field.semantic_view == semantic_view and _visible(field, role)
        }
        if any(member not in available for member in members):
            continue
        views_with_members.append(semantic_view)
        if target is None or aggregation is None:
            return SemanticViewResolution(
                semantic_view=semantic_view,
                views_with_members=tuple(views_with_members),
                assignment_families=assignment_families,
            )
        if metric_target_candidates(catalog, semantic_view, target, aggregation, role):
            return SemanticViewResolution(
                semantic_view=semantic_view,
                views_with_members=tuple(views_with_members),
                assignment_families=assignment_families,
            )
    return SemanticViewResolution(
        views_with_members=tuple(views_with_members),
        assignment_families=assignment_families,
    )


def resolve_query_metric(
    query: "QuerySpec",
    catalog: SemanticCatalog,
    role: str = "viewer",
) -> CatalogMetric:
    """Resolve a logical metric target/method to one governed Cube measure."""

    if query.semantic_view is None:
        raise AnalyticsValidationError("A semantic view could not be resolved")
    matches = metric_target_candidates(
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
        and metric.aggregation in PUBLIC_METRIC_AGGREGATIONS
        and _visible(metric, role)
    }
    by_target: dict[str, list[MetricAggregationOption]] = {}
    target_labels: dict[str, str] = {}
    target_entities: dict[str, str] = {}
    for target, aggregation in sorted(
        pairs, key=lambda pair: (str(pair[0]), str(pair[1]))
    ):
        assert target is not None and aggregation is not None
        matches = metric_target_candidates(
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
        # An enum-value target counts one entity but is not that entity, so the
        # target slug is what distinguishes it from its siblings.
        label_source = target if target != entity else entity
        target_labels.setdefault(target, label_source.replace("_", " ").title())
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

    semantic_view: str | None = Field(
        default=None,
        json_schema_extra={"deprecated": True},
        description=(
            "Deprecated compatibility field. The server infers the row grain "
            "from the metric, dimensions, time dimension, and filters; any "
            "supplied value is ignored."
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
    chart_type: ChartType | None = Field(
        default=None,
        description=(
            "Optional intended rendering. When present the server validates the "
            "dimension, time, and metric-type shape against the chart contract "
            "and reports the row/column layout with the result."
        ),
    )
    series_limit: int | None = Field(
        default=None,
        ge=1,
        le=MAX_SERIES,
        description=(
            "Optional cap on the number of series a chart renders. Applies to the "
            "column dimension of a cross tabulation and to the series dimension "
            "of a time chart; unbounded dimensions such as keyword need it."
        ),
    )
    fill_empty: bool = Field(
        default=False,
        description=(
            "Complete a cross tabulation into a full grid by adding zero-valued "
            "rows for observed row/column pairs that returned no data."
        ),
    )

    @field_validator("semantic_view")
    @classmethod
    def _view_identifier(cls, value: str | None) -> str | None:
        return validate_identifier(value) if value is not None else None

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

    distinct_field = metric.parameters.get("distinctField")
    if metric.aggregation is Aggregation.FILTERED_DISTINCT_COUNT:
        # Row counting would multiply by the assignment fan-out of a combination
        # grain, so the match projects onto an explicit deduplication key.
        if not isinstance(distinct_field, str):
            raise AnalyticsValidationError(
                f"Metric {metric.slug} requires a distinct field"
            )
        catalog.field(validate_identifier(distinct_field), metric.semantic_view)
    elif distinct_field is not None:
        raise AnalyticsValidationError(
            f"Aggregation {metric.aggregation.value} does not accept a distinct field"
        )

    filtered_operations = {
        Aggregation.FILTERED_COUNT,
        Aggregation.FILTERED_DISTINCT_COUNT,
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
    members = (
        *query.dimensions,
        *(filter_spec.member for filter_spec in query.filters),
        *((query.time_dimension,) if query.time_dimension is not None else ()),
    )
    resolution = resolve_semantic_view(
        catalog,
        target=query.metric,
        aggregation=query.aggregation,
        members=members,
        role=role,
    )
    if resolution.semantic_view is None:
        if resolution.crosses_assignment_families:
            raise AnalyticsValidationError(
                "Crossing assignment families repeats a response once per "
                "combination, so this metric cannot be reported honestly at "
                "that grain. Use a response-level breakdown or a counting metric."
            )
        if resolution.views_with_members:
            raise AnalyticsValidationError(
                f"Metric target {query.metric}/{query.aggregation.value} is not "
                f"published at the {resolution.views_with_members[0]} grain that "
                f"{', '.join(members)} requires."
            )
        raise AnalyticsValidationError(
            "No semantic view contains every selected dimension, time dimension, "
            "and filter member"
        )
    # semantic_view is a deprecated client compatibility field. Always replace it
    # with the resolved grain before validation, compilation, logging, or output.
    query = query.model_copy(update={"semantic_view": resolution.semantic_view})
    validate_query_fields(
        semantic_view=resolution.semantic_view,
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

    if query.chart_type is not None:
        validate_chart_definition(
            query.chart_type,
            query.dimensions,
            query.metric,
            query.aggregation,
            catalog,
            semantic_view=resolution.semantic_view,
            time_dimension=query.time_dimension,
            time_granularity=query.time_granularity,
            role=role,
        )
    layout = chart_layout(query)
    if query.fill_empty and (layout is None or layout.column_dimension is None):
        raise AnalyticsValidationError(
            "Filling empty cells requires a cross tabulation with a column axis"
        )
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
    *,
    _validated: bool = False,
) -> dict[str, Any]:
    """Validate and compile a governed request into Cube's JSON query format."""

    if _validated:
        if not isinstance(query, QuerySpec) or query.semantic_view is None:
            raise ValueError("Validated Cube compilation requires a resolved query")
    else:
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
    # A cross tabulation of two dimensions. grouped_bar compares the second
    # dimension side by side, which suits comparison better than stacking.
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
        for chart_type in ("stacked_bar", "grouped_bar", "heatmap")
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


_SLICE_CHART_TYPES = frozenset({"pie", "donut"})
_CROSS_TAB_CHART_TYPES = frozenset({"stacked_bar", "grouped_bar", "heatmap"})
_SERIES_CHART_TYPES = frozenset({"line", "area"})


class ChartLayout(BaseModel):
    """How a long-format result maps onto a chart's axes."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    chart_type: ChartType | None = None
    row_dimension: str | None = None
    column_dimension: str | None = None
    value_key: str = "value"
    series_limit: int | None = None
    truncated_series: bool = False
    other_series_label: str | None = None
    filled_cells: int = 0


def chart_layout(query: "QuerySpec") -> ChartLayout | None:
    """Describe the row and column axes so a client need not infer them.

    A cross tabulation puts the first dimension on rows and the second on
    columns. A time chart puts the time bucket on rows and the remaining
    dimension on columns, which is what makes each of its values one line.
    """

    if query.time_dimension is not None and query.time_granularity is not None:
        column = query.dimensions[0] if query.dimensions else None
        return ChartLayout(
            chart_type=query.chart_type,
            row_dimension=query.time_dimension,
            column_dimension=column,
        )
    if len(query.dimensions) == 2:
        return ChartLayout(
            chart_type=query.chart_type,
            row_dimension=query.dimensions[0],
            column_dimension=query.dimensions[1],
        )
    if len(query.dimensions) == 1:
        return ChartLayout(
            chart_type=query.chart_type,
            row_dimension=query.dimensions[0],
        )
    return None


def _numeric(value: Any) -> float:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0.0


def _ranked_values(
    rows: list[dict[str, Any]], member: str, value_key: str
) -> list[Any]:
    totals: dict[Any, float] = {}
    for row in rows:
        totals[row.get(member)] = totals.get(row.get(member), 0.0) + _numeric(
            row.get(value_key)
        )
    return [
        value
        for value, _ in sorted(totals.items(), key=lambda item: (-item[1], str(item[0])))
    ]


def _series_limit_for(query: "QuerySpec") -> int | None:
    if query.series_limit is not None:
        return query.series_limit
    if query.chart_type in _SLICE_CHART_TYPES:
        return DEFAULT_SLICE_LIMIT
    if query.chart_type in _SERIES_CHART_TYPES or query.chart_type in _CROSS_TAB_CHART_TYPES:
        return DEFAULT_SERIES_LIMIT
    return None


def shape_chart_rows(
    rows: list[dict[str, Any]], query: "QuerySpec"
) -> tuple[list[dict[str, Any]], ChartLayout | None]:
    """Cap series and complete the grid so the result suits the chart type.

    Capping keeps an unbounded dimension such as keyword from producing hundreds
    of unreadable series. A slice chart aggregates the remainder into one bucket
    because its parts must still sum to the whole; other chart types drop it,
    since an "Other" line or column would be a meaningless aggregate.
    """

    layout = chart_layout(query)
    if layout is None or not rows:
        return rows, layout

    result = rows
    limit = _series_limit_for(query)
    truncated = False
    other_label: str | None = None

    if limit is not None:
        # A slice chart has no column axis, so its own dimension is what gets cut.
        member = (
            layout.row_dimension
            if query.chart_type in _SLICE_CHART_TYPES
            else layout.column_dimension
        )
        if member is not None:
            ranked = _ranked_values(result, member, layout.value_key)
            if len(ranked) > limit:
                truncated = True
                kept = set(ranked[:limit])
                if query.chart_type in _SLICE_CHART_TYPES:
                    other_label = OTHER_SERIES_LABEL
                    remainder = sum(
                        _numeric(row.get(layout.value_key))
                        for row in result
                        if row.get(member) not in kept
                    )
                    result = [row for row in result if row.get(member) in kept]
                    result.append({member: other_label, layout.value_key: remainder})
                else:
                    result = [row for row in result if row.get(member) in kept]

    filled = 0
    if query.fill_empty and layout.column_dimension is not None:
        result, filled = _fill_cross_tab(result, layout)

    return result, layout.model_copy(
        update={
            "series_limit": limit,
            "truncated_series": truncated,
            "other_series_label": other_label,
            "filled_cells": filled,
        }
    )


def _fill_cross_tab(
    rows: list[dict[str, Any]], layout: ChartLayout
) -> tuple[list[dict[str, Any]], int]:
    row_member = layout.row_dimension
    column_member = layout.column_dimension
    if row_member is None or column_member is None:
        return rows, 0

    row_values: list[Any] = []
    column_values: list[Any] = []
    for row in rows:
        if row.get(row_member) not in row_values:
            row_values.append(row.get(row_member))
        if row.get(column_member) not in column_values:
            column_values.append(row.get(column_member))

    present = {(row.get(row_member), row.get(column_member)) for row in rows}
    template = {key: None for key in rows[0]}
    added = [
        {
            **template,
            row_member: row_value,
            column_member: column_value,
            layout.value_key: 0,
        }
        for row_value in row_values
        for column_value in column_values
        if (row_value, column_value) not in present
    ]
    return [*rows, *added], len(added)


def escape_spreadsheet_formula(value: Any) -> Any:
    """Neutralize values that spreadsheet software could execute as formulas."""

    if isinstance(value, str) and value.startswith(
        ("=", "+", "-", "@", "\t", "\r", "\n")
    ):
        return "'" + value
    return value
