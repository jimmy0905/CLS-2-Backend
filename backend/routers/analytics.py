"""Governed, feature-gated survey analytics APIs.

The router is the public trust boundary for Cube. Client requests contain only
published catalog slugs; raw Cube members and SQL are never accepted.
"""

from __future__ import annotations

from datetime import datetime, timedelta, time as datetime_time
import hashlib
import json
import math
import re
import time
import threading
from typing import Any, Literal
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Body, Depends, Header, HTTPException, Response, status
from fastapi.responses import FileResponse
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import func, or_, text as sql_text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

import config
from models.AnalyticsAuditLog import AnalyticsAuditLog
from models.AnalyticsChart import AnalyticsChart
from models.AnalyticsExportJob import AnalyticsExportJob
from models.AnalyticsField import AnalyticsField
from models.AnalyticsMetric import AnalyticsMetric
from models.AnalyticsModelVersion import AnalyticsModelVersion
from models.AnalyticsQueryLog import AnalyticsQueryLog
from models.User import User
from utils.analytics import (
    Aggregation,
    AnalyticsValidationError,
    CatalogField,
    CatalogMetric,
    FieldType,
    FilterSpec,
    OrderSpec,
    QuerySpec,
    SemanticCatalog,
    Visibility,
    compile_cube_query,
    validate_chart_definition,
    validate_identifier,
    validate_metric,
)
from utils.analytics_cube import CubeClient, CubeQueryError, CubeUnavailableError
from utils.analytics_drilldown import (
    DrilldownSpec,
    build_drilldown_statement,
    execute_drilldown,
)
from utils.analytics_exports import build_export_path, execute_export_job
from utils.analytics_metadata_auth import verify_metadata_signature
from utils.analytics_results import (
    augment_cube_query_with_supports,
    format_query_result,
)
from utils.analytics_records import build_record_query, query_records
from utils.database import get_db
from utils.security import get_current_user, require_admin
from utils.utc import resolve_timezone, utc_now


_SEMANTIC_VIEWS = {
    "survey_responses",
    "survey_topics",
    "survey_departments",
    "survey_keywords",
}
_PROFILE = re.compile(r"^[a-z0-9]+_(?:cls|ecls)$")
_CHART_TYPES = (
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
)

# OpenAPI descriptions deliberately mirror the public analytics contract.  The
# Markdown reference gives examples; these strings keep Swagger/ReDoc useful to
# frontend and integration clients without exposing Cube member names or SQL.
_ENDPOINT_DESCRIPTIONS = {
    "viewer_catalog": "Return the active immutable catalog visible to the current role. "
    "Only published viewer-visible fields, metrics, and chart types are returned; "
    "draft definitions, source keys, and raw payload fields are never exposed.",
    "viewer_availability": "Report field-level non-null counts and availability rates "
    "for one semantic view. Results include only fields visible to the current role "
    "and are cached for up to 15 minutes to avoid repeated reporting scans.",
    "viewer_filter_options": "Return distinct non-null values for one published "
    "dimension, with matching-row counts. Optional governed filters and string search "
    "narrow the list for a frontend filter control; use cursor to page beyond 1,000 values.",
    "viewer_query": "Run one governed aggregate query against exactly one semantic view. "
    "The API validates published member slugs, typed filters, limits, time settings, "
        "and role visibility before forwarding it to private Cube.",
    "viewer_records_query": "Return role-authorized, paginated records from the live database. "
    "Survey records exclude soft-deleted rows, preserve the legacy and canonical "
    "sentiment fields, and use EXISTS predicates for assignment filters so each "
    "survey remains one row.",
    "viewer_charts": "List published charts visible to the current role in the active "
    "catalog. Draft, archived, invalid, and more-restricted charts are omitted.",
    "viewer_chart_data": "Run a published chart by ID. Its defined members stay fixed; "
    "callers may only override safe filters, time settings, ordering, and limit. "
    "The response is shaped for the declared chart type.",
    "viewer_drilldown": "Return cursor-paginated survey-response rows for a governed "
    "drilldown. Only visible core and promoted fields may be selected; unpromoted "
    "raw payload keys are never returned.",
    "viewer_export_create": "Queue an asynchronous CSV or XLSX export for exactly one "
    "governed aggregate query or drilldown. Visibility is revalidated while the job "
    "runs and files expire after 24 hours.",
    "viewer_export_get": "Return export-job status for its owner or an administrator. "
    "Unauthorized callers receive not found rather than information about the job.",
    "viewer_export_download": "Download a completed, unexpired export belonging to the "
    "current user or visible to an administrator. The file response is non-cacheable.",
    "internal_catalog": "Private Cube metadata endpoint. It requires a fresh, "
    "profile-bound HMAC signature and remains available during shadow compilation "
    "even while user analytics is feature-disabled.",
    "admin_candidates": "List upload-discovered raw-column candidates, including type "
    "inference, bounded samples, conflicts, and promotion state. Admin-only because "
    "candidate metadata can contain sensitive source keys.",
    "admin_fields_list": "List all local governed field records, including candidates, "
    "drafts, published records, archival state, and discovery metadata.",
    "admin_field_get": "Return one local governed field record by numeric ID.",
    "admin_field_create": "Create a draft raw-JSON field with a safe slug, typed source "
    "key, semantic view, and visibility. The field must later be published and a "
    "catalog version activated before users can query it.",
    "admin_field_update": "Update a non-archived field. A change returns the field to "
    "draft so it must be revalidated and republished before a future activation.",
    "admin_field_promote": "Promote an upload-discovered candidate by selecting its "
    "governed data type, visibility, and optional display metadata.",
    "admin_field_validate": "Validate a field without activating it. The response reports "
    "a boolean and safe validation errors.",
    "admin_field_publish": "Mark a promoted, valid field published and audit the action. "
    "It becomes visible only after catalog publication succeeds.",
    "admin_field_archive": "Archive a field instead of deleting it. Archiving is rejected "
    "while any published metric or chart references the field.",
    "admin_metrics_list": "List every governed metric, including source/weight references, "
    "operation, confidence configuration, visibility, and lifecycle state.",
    "admin_metric_get": "Return one governed metric by numeric ID.",
    "admin_metric_create": "Create a draft metric over a promoted field or fixed governed "
    "core member. Only declarative metric parameters are accepted; executable SQL or "
    "expressions are rejected.",
    "admin_metric_update": "Update a non-archived metric and reset it to draft, requiring "
    "fresh validation and publication.",
    "admin_metric_validate": "Validate metric source types, operation, weighting, visibility "
    "dependencies, confidence level, and semantic-view compatibility.",
    "admin_metric_publish": "Mark a valid metric published and audit it. Catalog activation "
    "is a separate operation.",
    "admin_metric_archive": "Archive a metric unless it is referenced by a published chart.",
    "admin_charts_list": "List all chart definitions, including drafts, archived charts, "
    "validation errors, visibility, and model-version metadata.",
    "admin_chart_get": "Return one chart definition by numeric ID.",
    "admin_chart_create": "Create a draft frontend chart contract. This defines governed "
    "members and rendering shape; it does not render a chart server-side.",
    "admin_chart_update": "Update a non-archived chart and reset it to draft so it must "
    "be validated and republished.",
    "admin_chart_validate": "Validate chart member visibility, filters, time settings, and "
    "type-specific shape requirements without activating it.",
    "admin_chart_publish": "Validate and publish a chart, then immediately activate "
    "the next catalog version so it is visible to chart consumers.",
    "admin_chart_archive": "Soft-delete a chart and immediately activate the next "
    "catalog version so it is no longer visible. Audit history is retained.",
    "admin_versions": "List immutable catalog-version history without embedding each "
    "potentially large snapshot.",
    "admin_version_get": "Return one catalog version, including its immutable snapshot and "
    "generated Cube metadata. Admin-only because it can contain local source keys.",
    "admin_catalog_publish": "Revalidate all currently published definitions, create an "
    "immutable catalog snapshot, and atomically activate the next catalog version. "
    "Invalid definitions prevent activation.",
}
_CI_OPERATIONS = {
    Aggregation.MEAN_CONFIDENCE_INTERVAL,
    Aggregation.WEIGHTED_MEAN_CONFIDENCE_INTERVAL,
    Aggregation.PROPORTION_CONFIDENCE_INTERVAL,
    Aggregation.WEIGHTED_PROPORTION_CONFIDENCE_INTERVAL,
}
_MAX_CUBE_CATALOG_BYTES = 2 * 1024 * 1024
_DRILLDOWN_SEMAPHORE = threading.BoundedSemaphore(
    config.ANALYTICS_DRILLDOWN_CONCURRENCY
)
_FIELD_AVAILABILITY_CACHE_TTL = timedelta(minutes=15)
_FIELD_AVAILABILITY_CACHE: dict[tuple[object, ...], tuple[datetime, dict[str, Any]]] = {}
_FIELD_AVAILABILITY_CACHE_LOCK = threading.Lock()
_AVAILABILITY_VIEW_NAMES = {
    "survey_responses": "analytics_survey_facts",
    "survey_topics": "analytics_survey_topics",
    "survey_departments": "analytics_survey_departments",
    "survey_keywords": "analytics_survey_keywords",
}
_ASSIGNMENT_AVAILABILITY_ALIASES = {
    "response_id": "id",
    "sentiment": "assignment_sentiment",
    "department": "department_name",
}
_FILTER_OPTION_COUNT_METRICS = {
    "survey_responses": "response_count",
    "survey_topics": "assignment_count",
    "survey_departments": "assignment_count",
    "survey_keywords": "assignment_count",
}


def _core_field(
    slug: str, data_type: FieldType, semantic_view: str = "survey_responses"
) -> CatalogField:
    return CatalogField(
        slug=slug,
        label=slug.replace("_", " ").title(),
        semantic_view=semantic_view,
        data_type=data_type,
    )


_RESPONSE_FIELD_TYPES: dict[str, FieldType] = {
    "id": FieldType.NUMBER,
    "survey_id": FieldType.STRING,
    "respondent_id": FieldType.STRING,
    "reported_at": FieldType.DATE,
    "created_at": FieldType.DATE,
    "updated_at": FieldType.DATE,
    "comment": FieldType.STRING,
    "topic_sentiment": FieldType.STRING,
    "topic_sentiment_score": FieldType.NUMBER,
    "cls": FieldType.NUMBER,
    "store_key": FieldType.NUMBER,
    "store_name": FieldType.STRING,
    "store_name_english": FieldType.STRING,
    "store_name_local": FieldType.STRING,
    "bu_key": FieldType.STRING,
    "area_manager": FieldType.STRING,
    "store_format": FieldType.STRING,
    "store_type": FieldType.STRING,
    "operations_controller": FieldType.STRING,
    "regional_manager": FieldType.STRING,
    "px": FieldType.STRING,
    "csr": FieldType.STRING,
    "dr": FieldType.STRING,
    "mag_type": FieldType.STRING,
    "cf_grouping": FieldType.STRING,
    "store_brand": FieldType.STRING,
    "competitor": FieldType.STRING,
    "region": FieldType.STRING,
    "area": FieldType.STRING,
    "province": FieldType.STRING,
    "territory": FieldType.STRING,
    "toh": FieldType.STRING,
    "district": FieldType.STRING,
    "city": FieldType.STRING,
    "operations_manager": FieldType.STRING,
    "district_manager": FieldType.STRING,
    "sic": FieldType.STRING,
    "soc": FieldType.STRING,
    "tech_life_type": FieldType.STRING,
    "operation_manager_tl": FieldType.STRING,
    "region_manager_tl": FieldType.STRING,
    "relocation": FieldType.STRING,
    "latitude": FieldType.NUMBER,
    "longitude": FieldType.NUMBER,
    "store_open_date": FieldType.DATE,
    "store_close_date": FieldType.DATE,
    "is_closed": FieldType.BOOLEAN,
    "channel_name": FieldType.STRING,
    "channel_id": FieldType.NUMBER,
    "delivery_service_name": FieldType.STRING,
    "delivery_service_id": FieldType.NUMBER,
}

_CORE_FIELDS: tuple[CatalogField, ...] = tuple(
    _core_field(slug, data_type)
    for slug, data_type in _RESPONSE_FIELD_TYPES.items()
)
for _view, _assignment_members in {
    "survey_topics": {"topic_id": FieldType.NUMBER, "topic": FieldType.STRING},
    "survey_departments": {
        "department_id": FieldType.NUMBER,
        "department": FieldType.STRING,
    },
    "survey_keywords": {
        "keyword_id": FieldType.NUMBER,
        "keyword": FieldType.STRING,
    },
}.items():
    # Assignment views contain facts.* at one assignment row per response.
    # Preserve conflicting meanings with explicit response aliases.
    _CORE_FIELDS += (
        _core_field("assignment_id", FieldType.NUMBER, _view),
        _core_field("response_id", FieldType.NUMBER, _view),
        _core_field("sentiment", FieldType.STRING, _view),
    )
    _CORE_FIELDS += tuple(
        _core_field(slug, data_type, _view)
        for slug, data_type in _RESPONSE_FIELD_TYPES.items()
        if slug != "id"
    )
    _CORE_FIELDS += tuple(
        _core_field(slug, data_type, _view)
        for slug, data_type in _assignment_members.items()
    )


def _core_metric(
    slug: str,
    aggregation: Aggregation,
    source_field: str | None = None,
    semantic_view: str = "survey_responses",
    parameters: dict[str, Any] | None = None,
) -> CatalogMetric:
    return CatalogMetric(
        slug=slug,
        label=slug.replace("_", " ").title(),
        semantic_view=semantic_view,
        aggregation=aggregation,
        source_field=source_field,
        parameters=parameters or {},
    )


_CORE_METRICS: tuple[CatalogMetric, ...] = (
    _core_metric("response_count", Aggregation.COUNT),
    _core_metric("distinct_survey_count", Aggregation.DISTINCT_COUNT, "id"),
    _core_metric("cls_sum", Aggregation.SUM, "cls"),
    _core_metric("cls_average", Aggregation.AVERAGE, "cls"),
    _core_metric(
        "topic_sentiment_score_sum", Aggregation.SUM, "topic_sentiment_score"
    ),
    _core_metric(
        "topic_sentiment_score_average",
        Aggregation.AVERAGE,
        "topic_sentiment_score",
    ),
    _core_metric(
        "median_topic_sentiment_score",
        Aggregation.MEDIAN,
        "topic_sentiment_score",
    ),
    _core_metric("first_reported_at", Aggregation.MIN, "reported_at"),
    _core_metric("last_reported_at", Aggregation.MAX, "reported_at"),
    _core_metric("last_updated_at", Aggregation.MAX, "updated_at"),
    # These are standard dashboard measures, not BU-specific local definitions.
    # Keep them core so existing sentiment-breakdown cards work immediately on a
    # new profile without an administrator first publishing four duplicate
    # filtered-count definitions.
    *(
        _core_metric(
            f"topic_sentiment_{sentiment.lower()}_count",
            Aggregation.FILTERED_COUNT,
            "topic_sentiment",
            parameters={
                "filter": {"operator": "equals", "value": sentiment}
            },
        )
        for sentiment in ("POSITIVE", "NEGATIVE", "NEUTRAL", "MIXED")
    ),
)
for _view in ("survey_topics", "survey_departments", "survey_keywords"):
    _prefix = _view.removeprefix("survey_").removesuffix("s")
    _CORE_METRICS += (
        _core_metric("assignment_count", Aggregation.COUNT, semantic_view=_view),
        _core_metric(
            "distinct_survey_count",
            Aggregation.DISTINCT_COUNT,
            "survey_id",
            semantic_view=_view,
        ),
        *(
            _core_metric(
                f"{_prefix}_assignment_{sentiment.lower()}_count",
                Aggregation.FILTERED_COUNT,
                "sentiment",
                semantic_view=_view,
                parameters={
                    "filter": {"operator": "equals", "value": sentiment}
                },
            )
            for sentiment in ("POSITIVE", "NEGATIVE", "NEUTRAL")
        ),
    )


class _StrictInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FieldInput(_StrictInput):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "slug": "overall_score",
                    "label": "Overall score",
                    "description": "Imported survey score from the monthly upload",
                    "data_type": "number",
                    "source_key": "Overall Score",
                    "semantic_view": "survey_responses",
                    "visibility": "viewer",
                }
            ]
        },
    )

    slug: str
    label: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=1_000)
    data_type: FieldType
    source_kind: Literal["raw_json"] = "raw_json"
    source_key: str = Field(min_length=1, max_length=128)
    semantic_view: Literal["survey_responses"] = Field(
        default="survey_responses",
        description="Imported raw fields are projected from one survey response into all assignment views.",
    )
    visibility: Visibility = Visibility.VIEWER
    definition: dict[str, Any] = Field(default_factory=dict)

    @field_validator("slug")
    @classmethod
    def _slug(cls, value: str) -> str:
        return validate_identifier(value)

    @field_validator("label", "source_key")
    @classmethod
    def _strip(cls, value: str) -> str:
        value = value.strip()
        if not value or "\x00" in value:
            raise ValueError("value must not be blank or contain NUL")
        return value

    @field_validator("definition")
    @classmethod
    def _no_executable_definition(cls, value: dict[str, Any]) -> dict[str, Any]:
        if value:
            raise ValueError("Imported fields do not accept executable definitions")
        return value


class CandidatePromotionInput(_StrictInput):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "data_type": "number",
                    "visibility": "viewer",
                    "label": "Overall score",
                    "description": "Normalized imported score",
                }
            ]
        },
    )

    data_type: FieldType
    visibility: Visibility = Visibility.VIEWER
    label: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=1_000)


class MetricInput(_StrictInput):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "slug": "negative_response_rate",
                    "label": "Negative response rate",
                    "semantic_view": "survey_responses",
                    "source_member": "topic_sentiment",
                    "operation": "filtered_rate",
                    "definition": {
                        "filter": {"operator": "equals", "value": "NEGATIVE"}
                    },
                    "visibility": "viewer",
                },
                {
                    "slug": "overall_score_weighted_average",
                    "label": "Weighted overall score",
                    "field_id": 42,
                    "weight_member": "cls",
                    "operation": "weighted_average",
                    "visibility": "admin",
                },
            ]
        },
    )

    slug: str
    label: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=1_000)
    semantic_view: Literal[
        "survey_responses",
        "survey_topics",
        "survey_departments",
        "survey_keywords",
    ] = Field(
        default="survey_responses",
        description=(
            "Metric row grain. survey_responses is one survey; assignment views "
            "are one topic, department, or keyword assignment and expose assignment "
            "sentiment as assignment sentiment plus surveys.topic_sentiment as "
            "the canonical response sentiment."
        ),
    )
    field_id: int | None = None
    source_member: str | None = None
    operation: Aggregation
    weight_field_id: int | None = None
    weight_member: str | None = None
    confidence_level: float | None = Field(default=None, ge=0.8, le=0.999)
    definition: dict[str, Any] = Field(default_factory=dict)
    visibility: Visibility = Visibility.VIEWER

    @field_validator("slug")
    @classmethod
    def _slug(cls, value: str) -> str:
        return validate_identifier(value)

    @field_validator("source_member", "weight_member")
    @classmethod
    def _member(cls, value: str | None) -> str | None:
        return validate_identifier(value) if value is not None else None

    @field_validator("label")
    @classmethod
    def _label(cls, value: str) -> str:
        return value.strip()

    @field_validator("definition")
    @classmethod
    def _declarative_definition(cls, value: dict[str, Any]) -> dict[str, Any]:
        encoded = json.dumps(value, allow_nan=False)
        if len(encoded) > 16_384:
            raise ValueError("Metric parameters are too large")
        forbidden = {"sql", "query", "expression", "javascript", "code"}
        if any(str(key).lower() in forbidden for key in value):
            raise ValueError("Metric definitions cannot contain executable expressions")
        return value

    @model_validator(mode="after")
    def _confidence_contract(self) -> "MetricInput":
        if self.field_id is not None and self.source_member is not None:
            raise ValueError("Metric source uses either field_id or source_member")
        if self.weight_field_id is not None and self.weight_member is not None:
            raise ValueError("Metric weight uses either weight_field_id or weight_member")
        if self.operation in _CI_OPERATIONS and self.confidence_level is None:
            raise ValueError("Confidence-interval metrics require confidence_level")
        if self.operation not in _CI_OPERATIONS and self.confidence_level is not None:
            raise ValueError("confidence_level is limited to confidence-interval metrics")
        return self


class ChartDefinitionInput(_StrictInput):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "dimensions": ["store_format"],
                    "metrics": ["response_count"],
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
                    "order": [{"member": "response_count", "direction": "desc"}],
                    "limit": 100,
                }
            ]
        },
    )

    dimensions: tuple[str, ...] = Field(default=(), max_length=4)
    metrics: tuple[str, ...] = Field(default=(), max_length=5)
    filters: tuple[FilterSpec, ...] = Field(default=(), max_length=20)
    time_dimension: str | None = None
    time_range: tuple[str, str] | None = None
    timezone: str | None = None
    time_granularity: Literal[
        "second", "minute", "hour", "day", "week", "month", "quarter", "year"
    ] | None = None
    order: tuple[OrderSpec, ...] = Field(default=(), max_length=8)
    limit: int = Field(default=1_000, ge=1, le=5_000)

    @field_validator("dimensions", "metrics")
    @classmethod
    def _members(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        for value in values:
            validate_identifier(value)
        if len(values) != len(set(values)):
            raise ValueError("Chart members must not be duplicated")
        return values

    @field_validator("time_dimension")
    @classmethod
    def _time_member(cls, value: str | None) -> str | None:
        return validate_identifier(value) if value else value

    @field_validator("timezone")
    @classmethod
    def _timezone(cls, value: str | None) -> str | None:
        if value is not None:
            resolve_timezone(value)
        return value

    @model_validator(mode="after")
    def _time_contract(self) -> "ChartDefinitionInput":
        if (self.time_range or self.time_granularity) and not self.time_dimension:
            raise ValueError("time range and granularity require a time dimension")
        return self


class ChartInput(_StrictInput):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "slug": "responses_by_store_format",
                    "title": "Responses by store format",
                    "chart_type": "bar",
                    "semantic_view": "survey_responses",
                    "definition": {
                        "dimensions": ["store_format"],
                        "metrics": ["response_count"],
                        "order": [{"member": "response_count", "direction": "desc"}],
                    },
                    "visibility": "viewer",
                }
            ]
        },
    )

    slug: str
    title: str = Field(min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=1_000)
    chart_type: Literal[
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
    ]
    semantic_view: Literal[
        "survey_responses",
        "survey_topics",
        "survey_departments",
        "survey_keywords",
    ] = Field(
        description=(
            "Required chart row grain. Use survey_responses for response-level "
            "analysis; use one assignment view for topic, department, or keyword analysis."
        )
    )
    definition: ChartDefinitionInput
    visibility: Visibility = Visibility.VIEWER

    @field_validator("slug")
    @classmethod
    def _slug(cls, value: str) -> str:
        return validate_identifier(value)


class ChartDataInput(_StrictInput):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "filters": [
                        {
                            "member": "store_format",
                            "operator": "in",
                            "values": ["Mall", "Commercial"],
                        }
                    ],
                    "time_range": ["2026-01-01", "2026-03-31"],
                    "time_granularity": "month",
                    "timezone": "Asia/Hong_Kong",
                    "limit": 100,
                }
            ]
        },
    )

    filters: tuple[FilterSpec, ...] | None = Field(default=None, max_length=20)
    time_range: tuple[str, str] | None = None
    timezone: str | None = None
    time_granularity: Literal[
        "second", "minute", "hour", "day", "week", "month", "quarter", "year"
    ] | None = None
    order: tuple[OrderSpec, ...] | None = Field(default=None, max_length=8)
    limit: int | None = Field(default=None, ge=1, le=5_000)


class FilterOptionsInput(_StrictInput):
    """Request distinct, usable values for one governed filter dimension."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "semantic_view": "survey_responses",
                    "member": "store_format",
                    "metrics": ["topic_sentiment_score_average"],
                    "filters": [
                        {
                            "member": "topic_sentiment",
                            "operator": "equals",
                            "value": "NEGATIVE",
                        }
                    ],
                    "search": "Mall",
                    "timezone": "Asia/Hong_Kong",
                    "limit": 100,
                    "cursor": 0,
                }
            ]
        },
    )

    semantic_view: Literal[
        "survey_responses",
        "survey_topics",
        "survey_departments",
        "survey_keywords",
    ]
    member: str
    metrics: tuple[str, ...] = Field(default=(), max_length=4)
    # Reserve room for the endpoint's non-null filter and optional search.
    filters: tuple[FilterSpec, ...] = Field(default=(), max_length=18)
    search: str | None = Field(default=None, max_length=100)
    timezone: str | None = None
    limit: int = Field(default=100, ge=1, le=1_000)
    cursor: int | None = Field(default=None, ge=0, le=1_000_000)

    @field_validator("metrics")
    @classmethod
    def _metrics(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        for value in values:
            validate_identifier(value)
        if len(values) != len(set(values)):
            raise ValueError("Filter option metrics must not be duplicated")
        return values

    @field_validator("member")
    @classmethod
    def _member(cls, value: str) -> str:
        return validate_identifier(value)

    @field_validator("timezone")
    @classmethod
    def _timezone(cls, value: str | None) -> str | None:
        if value is not None:
            resolve_timezone(value)
        return value

    @field_validator("search")
    @classmethod
    def _search(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value or "\x00" in value:
            raise ValueError("search must not be blank or contain NUL")
        return value


class CatalogPublicationInput(_StrictInput):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"examples": [{"description": "Quarterly metric release"}]},
    )

    description: str | None = Field(default=None, max_length=1_000)


class RecordFilterInput(_StrictInput):
    """A typed filter over one of the live analytics record resources."""

    member: str = Field(validation_alias=AliasChoices("member", "field"))
    operator: Literal[
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
    value: Any = None
    values: tuple[Any, ...] | None = None

    @field_validator("member")
    @classmethod
    def _member(cls, value: str) -> str:
        return validate_identifier(value)


class RecordOrderInput(_StrictInput):
    member: str = Field(validation_alias=AliasChoices("member", "field"))
    direction: Literal["asc", "desc"] = "asc"

    @field_validator("member")
    @classmethod
    def _member(cls, value: str) -> str:
        return validate_identifier(value)


class RecordQueryInput(_StrictInput):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "resource": "surveys",
                    "filters": [
                        {
                            "member": "topic_sentiment",
                            "operator": "equals",
                            "value": "NEGATIVE",
                        }
                    ],
                    "order": [
                        {"member": "reported_at", "direction": "desc"},
                        {"member": "id", "direction": "desc"},
                    ],
                    "page": 1,
                    "size": 100,
                    "timezone": "Asia/Hong_Kong",
                }
            ]
        },
    )

    resource: Literal[
        "surveys",
        "stores",
        "departments",
        "channels",
        "delivery_services",
        "topics",
    ]
    filters: tuple[RecordFilterInput, ...] = Field(default=(), max_length=20)
    order: tuple[RecordOrderInput, ...] = Field(default=(), max_length=3)
    page: int = Field(default=1, ge=1)
    size: int = Field(default=100, ge=1, le=1_000)
    timezone: str | None = None

    @field_validator("timezone")
    @classmethod
    def _timezone(cls, value: str | None) -> str | None:
        if value is not None:
            resolve_timezone(value)
        return value

    @model_validator(mode="after")
    def _unique_order_members(self) -> "RecordQueryInput":
        members = [item.member for item in self.order]
        if len(members) != len(set(members)):
            raise ValueError("Record order fields must not be duplicated")
        return self


class ExportInput(_StrictInput):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "export_format": "xlsx",
                    "query": {
                        "semantic_view": "survey_responses",
                        "dimensions": ["store_format"],
                        "metrics": ["response_count"],
                    },
                },
                {
                    "export_format": "csv",
                    "drilldown": {"fields": ["survey_id", "comment"], "limit": 100},
                },
                {
                    "export_format": "csv",
                    "record_query": {
                        "resource": "surveys",
                        "filters": [],
                        "size": 100,
                    },
                },
            ]
        },
    )

    export_format: Literal["csv", "xlsx"]
    query: QuerySpec | None = None
    drilldown: DrilldownSpec | None = None
    record_query: RecordQueryInput | None = None

    @model_validator(mode="after")
    def _one_request_kind(self) -> "ExportInput":
        request_kinds = sum(
            value is not None
            for value in (self.query, self.drilldown, self.record_query)
        )
        if request_kinds != 1:
            raise ValueError(
                "Export requires exactly one query, drilldown, or record_query"
            )
        return self


def _analytics_enabled() -> None:
    """Evaluate the rollout flag per request so tests and operations can toggle it."""

    if not config.ANALYTICS_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Analytics is not enabled for this profile",
        )


def _analytics_no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store, private"


def _role(user: User) -> str:
    return "admin" if user.role == "admin" else "viewer"


def _active_model_version(db: Session) -> AnalyticsModelVersion | None:
    return (
        db.query(AnalyticsModelVersion)
        .filter(AnalyticsModelVersion.is_active.is_(True))
        .order_by(AnalyticsModelVersion.catalog_version.desc())
        .first()
    )


def _extract_cube_catalog(version: AnalyticsModelVersion | None) -> dict[str, Any]:
    if version is None:
        return {
            "profile": config.DEPLOYMENT_PROFILE,
            # Version zero is the immutable empty bootstrap catalog. The first
            # publication is version one, so a running Cube process always
            # observes a version advance when local definitions first appear.
            "catalogVersion": 0,
            "fields": [],
            "metrics": [],
            "rollups": [],
        }
    snapshot = version.catalog_snapshot or {}
    catalog = snapshot.get("cubeCatalog", snapshot)
    if not isinstance(catalog, dict):
        raise AnalyticsValidationError("Active analytics catalog snapshot is invalid")
    result = dict(catalog)
    result.setdefault(
        "rollups",
        _chart_rollups(snapshot.get("charts", []), result.get("metrics", [])),
    )
    return result


def _catalog(db: Session, role: str) -> SemanticCatalog:
    """Return the active core-plus-local catalog visible to the given role."""

    if role not in {"viewer", "admin"}:
        raise AnalyticsValidationError("Unknown analytics role")
    payload = _extract_cube_catalog(_active_model_version(db))
    local_fields: list[CatalogField] = []
    for item in payload.get("fields", []):
        if role != "admin" and item.get("visibility") != "viewer":
            continue
        local_fields.append(
            CatalogField(
                slug=item["slug"],
                label=item["label"],
                semantic_view=item["semanticView"],
                data_type=item["dataType"],
                visibility=item["visibility"],
            )
        )
    visible_fields = {
        (field.semantic_view, field.slug) for field in (*_CORE_FIELDS, *local_fields)
    }
    local_metrics: list[CatalogMetric] = []
    for item in payload.get("metrics", []):
        if role != "admin" and item.get("visibility") != "viewer":
            continue
        dependencies = (item.get("sourceField"), item.get("weightField"))
        if any(
            dependency
            and (item["semanticView"], dependency) not in visible_fields
            for dependency in dependencies
        ):
            continue
        local_metrics.append(
            CatalogMetric(
                slug=item["slug"],
                label=item["label"],
                semantic_view=item["semanticView"],
                aggregation=item["operation"],
                source_field=item.get("sourceField"),
                weight_field=item.get("weightField"),
                percentile=(item.get("parameters") or {}).get("percentile"),
                confidence_level=item.get("confidenceLevel"),
                parameters=item.get("parameters") or {},
                visibility=item["visibility"],
            )
        )
    return SemanticCatalog(
        fields=(*_CORE_FIELDS, *local_fields),
        metrics=(*_CORE_METRICS, *local_metrics),
    )


def _raw_field_sources(
    db: Session, role: str
) -> dict[str, tuple[str, FieldType]]:
    if role not in {"viewer", "admin"}:
        raise AnalyticsValidationError("Unknown analytics role")
    payload = _extract_cube_catalog(_active_model_version(db))
    result: dict[str, tuple[str, FieldType]] = {}
    for field in payload.get("fields", []):
        if not isinstance(field, dict) or field.get("sourceKind") != "raw_json":
            continue
        if role != "admin" and field.get("visibility") != "viewer":
            continue
        source_key = field.get("sourceKey")
        if not isinstance(source_key, str) or not source_key:
            continue
        result[validate_identifier(str(field.get("slug")))] = (
            source_key,
            FieldType(field.get("dataType")),
        )
    return result


def _availability_expression(
    field: CatalogField,
    raw_fields: dict[str, tuple[str, FieldType]],
    *,
    parameter_name: str,
    parameters: dict[str, Any],
) -> str:
    """Return a trusted SQL expression that is non-null when a field has data."""

    raw_source = raw_fields.get(field.slug)
    if raw_source is not None:
        parameters[parameter_name] = raw_source[0]
        return f"analytics_raw_value(raw_row_data, :{parameter_name})"

    if not any(
        item.semantic_view == field.semantic_view and item.slug == field.slug
        for item in _CORE_FIELDS
    ):
        raise AnalyticsValidationError(
            f"Field {field.slug} has no governed availability source"
        )
    column = field.slug
    if field.semantic_view != "survey_responses":
        column = _ASSIGNMENT_AVAILABILITY_ALIASES.get(column, column)
    return f'"{validate_identifier(column)}"'


def _field_availability(
    db: Session,
    catalog: SemanticCatalog,
    *,
    role: str,
    semantic_view: str,
    catalog_version: int,
) -> dict[str, Any]:
    """Return cached, role-scoped non-null statistics for governed fields.

    Availability is deliberately a separate endpoint rather than part of the
    catalog response: calculating it is a reporting-table scan, not metadata
    lookup. A 15-minute cache matches the analytics freshness objective.
    """

    if semantic_view not in _AVAILABILITY_VIEW_NAMES:
        raise AnalyticsValidationError("Unknown semantic view")
    fields = sorted(
        (
            field
            for field in catalog.fields
            if field.semantic_view == semantic_view
            and (role == "admin" or field.visibility is Visibility.VIEWER)
        ),
        key=lambda field: field.slug,
    )
    cache_key = (
        config.DEPLOYMENT_PROFILE,
        role,
        semantic_view,
        catalog_version,
        tuple((field.slug, field.data_type.value) for field in fields),
    )
    now = utc_now()
    with _FIELD_AVAILABILITY_CACHE_LOCK:
        cached = _FIELD_AVAILABILITY_CACHE.get(cache_key)
    if cached is not None and now - cached[0] < _FIELD_AVAILABILITY_CACHE_TTL:
        return {**cached[1], "cached": True}

    raw_fields = _raw_field_sources(db, role)
    parameters: dict[str, Any] = {}
    select_items = ["COUNT(*) AS total_rows"]
    for index, field in enumerate(fields):
        expression = _availability_expression(
            field,
            raw_fields,
            parameter_name=f"availability_source_{index}",
            parameters=parameters,
        )
        select_items.append(f"COUNT({expression}) AS non_null_{index}")
    view_name = _AVAILABILITY_VIEW_NAMES[semantic_view]
    statement = sql_text(f"SELECT {', '.join(select_items)} FROM {view_name}")
    row = db.execute(statement, parameters).mappings().one()
    total_rows = int(row.get("total_rows") or 0)
    response = {
        "model_version": catalog_version,
        "semantic_view": semantic_view,
        "total_rows": total_rows,
        "fields": [
            {
                "slug": field.slug,
                "label": field.label,
                "data_type": field.data_type.value,
                "non_null_count": int(row.get(f"non_null_{index}") or 0),
                "null_count": total_rows - int(row.get(f"non_null_{index}") or 0),
                "availability_rate": (
                    round(int(row.get(f"non_null_{index}") or 0) / total_rows, 6)
                    if total_rows
                    else 0.0
                ),
                "available": bool(row.get(f"non_null_{index}") or 0),
            }
            for index, field in enumerate(fields)
        ],
        "generated_at": now.isoformat(),
        "cached": False,
    }
    with _FIELD_AVAILABILITY_CACHE_LOCK:
        _FIELD_AVAILABILITY_CACHE[cache_key] = (now, response)
    return response


def _audit(
    db: Session,
    actor: User | None,
    action: str,
    resource_type: str,
    resource_id: str | int,
    payload: dict[str, Any] | None = None,
) -> None:
    db.add(
        AnalyticsAuditLog(
            actor_id=getattr(actor, "id", None),
            action=action,
            resource_type=resource_type,
            resource_id=str(resource_id),
            payload=payload or {},
        )
    )


def _cube_client() -> CubeClient:
    base_url = config.ANALYTICS_CUBE_API_URL.rstrip("/")
    suffix = "/cubejs-api/v1"
    if base_url.endswith(suffix):
        base_url = base_url[: -len(suffix)]
    return CubeClient(
        base_url,
        config.ANALYTICS_CUBE_API_SECRET,
        timeout_seconds=config.ANALYTICS_QUERY_TIMEOUT_SECONDS,
    )


def _column_metadata(query: QuerySpec, catalog: SemanticCatalog) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    dimension_slugs = list(query.dimensions)
    if query.time_dimension and query.time_dimension not in dimension_slugs:
        dimension_slugs.append(query.time_dimension)
    for slug in dimension_slugs:
        field = catalog.field(slug, query.semantic_view)
        result.append(
            {
                "name": slug,
                "label": field.label,
                "type": field.data_type.value,
                "kind": "dimension",
            }
        )
    for slug in query.metrics:
        metric = catalog.metric(slug, query.semantic_view)
        result_type = "number"
        if metric.aggregation in {Aggregation.MIN, Aggregation.MAX} and metric.source_field:
            source_type = catalog.field(
                metric.source_field, query.semantic_view
            ).data_type
            if source_type in {FieldType.DATE, FieldType.TIME}:
                result_type = source_type.value
        result.append(
            {
                "name": slug,
                "label": metric.label,
                "type": result_type,
                "kind": "metric",
            }
        )
    return result


def _local_member_name(key: str, semantic_view: str) -> str:
    prefix = f"{semantic_view}."
    value = key[len(prefix) :] if key.startswith(prefix) else key
    return value.split(".", maxsplit=1)[0]


def _coerce_cube_value(value: Any, column_type: str) -> Any:
    if value is None or not isinstance(value, str):
        return value
    if column_type == "number":
        try:
            number = float(value)
        except ValueError:
            return value
        if not math.isfinite(number):
            return None
        return int(number) if number.is_integer() else number
    if column_type == "boolean" and value.lower() in {"true", "false"}:
        return value.lower() == "true"
    return value


def _format_rows(
    rows: Any, query: QuerySpec, columns: list[dict[str, str]]
) -> list[dict[str, Any]]:
    if not isinstance(rows, list):
        raise CubeUnavailableError("Cube returned invalid analytics rows")
    column_types = {item["name"]: item["type"] for item in columns}
    result: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            raise CubeUnavailableError("Cube returned invalid analytics rows")
        formatted: dict[str, Any] = {}
        for key, value in row.items():
            name = _local_member_name(str(key), query.semantic_view)
            if name in column_types:
                formatted[name] = _coerce_cube_value(value, column_types[name])
        result.append(formatted)
    return result


def _warning_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value[:1_000]]
    if isinstance(value, list):
        return [str(item)[:1_000] for item in value[:20]]
    return []


async def _execute_query(
    query: QuerySpec,
    db: Session,
    current_user: User,
    *,
    cube_query_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate, execute, log, and format a governed Cube query."""

    role = _role(current_user)
    try:
        catalog = _catalog(db, role)
        cube_query = cube_query_override or compile_cube_query(query, catalog, role)
        cube_query = augment_cube_query_with_supports(cube_query, query, catalog)
    except (AnalyticsValidationError, ValueError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    version = _active_model_version(db)
    query_id = str(uuid.uuid4())
    query_log = AnalyticsQueryLog(
        id=query_id,
        requested_by_id=current_user.id,
        model_version_id=version.id if version else None,
        semantic_view=query.semantic_view,
        request=query.model_dump(mode="json"),
        cube_query=cube_query,
        status="pending",
    )
    db.add(query_log)
    db.commit()
    started = time.monotonic()
    try:
        result = await _cube_client().execute(
            cube_query,
            profile_id=config.DEPLOYMENT_PROFILE,
            role=role,
            request_id=query_id,
        )
        formatted_result = format_query_result(result, query, catalog)
        columns = _column_metadata(query, catalog)
        rows = _format_rows(formatted_result["rows"], query, columns)
    except CubeQueryError as error:
        query_log.status = "failed"
        query_log.error_message = str(error)[:1_000]
        query_log.completed_at = utc_now()
        query_log.duration_ms = round((time.monotonic() - started) * 1_000)
        db.commit()
        raise HTTPException(
            status_code=422,
            detail={
                "code": "analytics_query_rejected",
                "message": "The analytics query could not be executed",
            },
        ) from error
    except (CubeUnavailableError, ValueError) as error:
        query_log.status = "failed"
        query_log.error_message = "Analytics service unavailable"
        query_log.completed_at = utc_now()
        query_log.duration_ms = round((time.monotonic() - started) * 1_000)
        db.commit()
        raise HTTPException(
            status_code=503,
            detail={
                "code": "analytics_unavailable",
                "message": "Analytics service is temporarily unavailable",
            },
        ) from error

    freshness = result.get("lastRefreshTime") or result.get("last_refresh_time")
    query_log.status = "completed"
    query_log.row_count = len(rows)
    query_log.duration_ms = round((time.monotonic() - started) * 1_000)
    query_log.completed_at = utc_now()
    if isinstance(freshness, str):
        try:
            query_log.freshness_at = datetime.fromisoformat(
                freshness.replace("Z", "+00:00")
            )
        except ValueError:
            freshness = None
    db.commit()
    return {
        "query_id": query_id,
        "model_version": version.catalog_version if version else 0,
        "timezone": query.timezone or "UTC",
        "columns": columns,
        "rows": rows,
        "confidence": formatted_result["confidence"],
        "warnings": [
            *formatted_result["warnings"],
            *_warning_list(result.get("warnings") or result.get("warning")),
        ],
        "freshness_time": freshness,
    }


def _catalog_response(catalog: SemanticCatalog, model_version: int) -> dict[str, Any]:
    return {
        "model_version": model_version,
        "semantic_views": sorted(catalog.views),
        "fields": [
            {
                "slug": field.slug,
                "label": field.label,
                "semantic_view": field.semantic_view,
                "data_type": field.data_type.value,
                "visibility": field.visibility.value,
            }
            for field in catalog.fields
        ],
        "metrics": [
            {
                "slug": metric.slug,
                "label": metric.label,
                "semantic_view": metric.semantic_view,
                "operation": metric.aggregation.value,
                "visibility": metric.visibility.value,
            }
            for metric in catalog.metrics
        ],
        "chart_types": list(_CHART_TYPES),
    }


def _snapshot_charts(version: AnalyticsModelVersion | None, role: str) -> list[dict[str, Any]]:
    if version is None:
        return []
    snapshot = version.catalog_snapshot or {}
    charts = snapshot.get("charts", [])
    if not isinstance(charts, list):
        return []
    result: list[dict[str, Any]] = []
    for chart in charts:
        if (
            not isinstance(chart, dict)
            or chart.get("status") != "published"
            or (role != "admin" and chart.get("visibility") != "viewer")
        ):
            continue
        # Snapshots are immutable. The database linkage is assigned after the
        # snapshot is built, so exposing its old value confuses API consumers.
        # Report the active catalog version instead.
        item = {
            key: value
            for key, value in chart.items()
            if key != "published_model_version_id"
        }
        item["model_version"] = version.catalog_version
        result.append(item)
    return result


def _chart_query(
    chart: dict[str, Any],
    override: ChartDataInput | None,
    catalog: SemanticCatalog,
    role: str,
) -> tuple[QuerySpec, dict[str, Any]]:
    definition = ChartDefinitionInput.model_validate(chart.get("definition") or {})
    update = override.model_dump(exclude_none=True, mode="json") if override else {}
    values = definition.model_dump(mode="json")
    values.update(update)
    dimensions = tuple(values["dimensions"])
    metrics = tuple(values["metrics"])
    validate_chart_definition(
        chart["chart_type"],
        dimensions,
        metrics,
        catalog,
        semantic_view=chart["semantic_view"],
        time_dimension=values.get("time_dimension"),
        role=role,
    )

    requested_limit = int(values["limit"])
    query_limit = min(requested_limit, 1_000)
    if chart["chart_type"] in {"pie", "donut"}:
        # The chart contract is always metric-desc top 12; an additional
        # governed aggregate query computes the remaining categories.
        values["order"] = ({"member": metrics[0], "direction": "desc"},)
        # Fetch one sentinel group so exactly twelve categories can be
        # distinguished from a real tail that must be represented as Other.
        query_limit = 13
    if chart["chart_type"] != "store_map":
        query = QuerySpec(
            semantic_view=chart["semantic_view"],
            dimensions=dimensions,
            metrics=metrics,
            filters=values["filters"],
            time_dimension=values.get("time_dimension"),
            time_range=values.get("time_range"),
            timezone=values.get("timezone"),
            time_granularity=values.get("time_granularity"),
            order=values["order"],
            limit=query_limit,
        )
        return query, compile_cube_query(query, catalog, role)

    # Store maps have four fixed location dimensions, while free exploration is
    # intentionally limited to three. Validate the fourth member independently.
    first_three = dimensions[:3]
    fourth = dimensions[3]
    query = QuerySpec(
        semantic_view=chart["semantic_view"],
        dimensions=first_three,
        metrics=metrics,
        filters=values["filters"],
        time_dimension=values.get("time_dimension"),
        time_range=values.get("time_range"),
        timezone=values.get("timezone"),
        time_granularity=values.get("time_granularity"),
        order=values["order"],
        limit=query_limit,
    )
    compile_cube_query(
        QuerySpec(
            semantic_view=chart["semantic_view"], dimensions=(fourth,), limit=1
        ),
        catalog,
        role,
    )
    cube_query = compile_cube_query(query, catalog, role)
    cube_query["dimensions"].append(f"{chart['semantic_view']}.{fourth}")
    cube_query["limit"] = min(requested_limit, 5_000)
    # model_copy deliberately carries the already validated fourth map member
    # through result formatting without relaxing QuerySpec for ad-hoc requests.
    query = query.model_copy(
        update={"dimensions": dimensions, "limit": cube_query["limit"]}
    )
    return query, cube_query


def _shape_chart_rows(
    chart: dict[str, Any],
    response: dict[str, Any],
    other_value: Any = None,
    other_response: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if chart["chart_type"] not in {"pie", "donut"}:
        return response
    definition = chart.get("definition") or {}
    dimensions = list(definition.get("dimensions") or [])
    metrics = list(definition.get("metrics") or [])
    rows = response.get("rows") or []
    if len(dimensions) != 1 or len(metrics) != 1:
        return response
    dimension, metric = dimensions[0], metrics[0]
    shaped = rows[:12]
    has_other = isinstance(other_value, (int, float)) and not isinstance(
        other_value, bool
    )
    if has_other:
        other_total = float(other_value)
    else:
        other_total = 0.0
    if has_other:
        shaped.append(
            {
                dimension: "Other",
                metric: int(other_total) if other_total.is_integer() else other_total,
            }
        )
        other_index = len(shaped) - 1
        if other_response:
            for key in ("confidence", "warnings"):
                metadata = other_response.get(key)
                if not isinstance(metadata, list):
                    continue
                response.setdefault(key, []).extend(
                    {
                        **item,
                        "row_index": other_index,
                        "category": "Other",
                    }
                    for item in metadata
                    if isinstance(item, dict)
                )
    response["rows"] = shaped
    return response


def _current_published_records(
    db: Session,
) -> tuple[list[AnalyticsField], list[AnalyticsMetric], list[AnalyticsChart]]:
    fields = (
        db.query(AnalyticsField)
        .filter(
            AnalyticsField.status == "published",
            AnalyticsField.is_promoted.is_(True),
            AnalyticsField.archived_at.is_(None),
        )
        .order_by(AnalyticsField.slug.asc())
        .all()
    )
    metrics = (
        db.query(AnalyticsMetric)
        .filter(
            AnalyticsMetric.status == "published",
            AnalyticsMetric.archived_at.is_(None),
        )
        .order_by(AnalyticsMetric.slug.asc())
        .all()
    )
    charts = (
        db.query(AnalyticsChart)
        .filter(
            AnalyticsChart.status == "published",
            AnalyticsChart.archived_at.is_(None),
        )
        .order_by(AnalyticsChart.slug.asc())
        .all()
    )
    return fields, metrics, charts


def _catalog_from_records(
    fields: list[AnalyticsField], metrics: list[AnalyticsMetric], role: str = "admin"
) -> SemanticCatalog:
    local_fields = [
        CatalogField(
            slug=field.slug,
            label=field.label,
            semantic_view=semantic_view,
            data_type=field.data_type,
            visibility=field.visibility,
        )
        for field in fields
        if role == "admin" or field.visibility == "viewer"
        for semantic_view in _field_semantic_views(field)
    ]
    field_by_id = {field.id: field for field in fields}
    local_metrics: list[CatalogMetric] = []
    for metric in metrics:
        if role != "admin" and metric.visibility != "viewer":
            continue
        source = field_by_id.get(metric.field_id)
        weight = field_by_id.get(metric.weight_field_id)
        source_slug = source.slug if source else metric.source_member
        weight_slug = weight.slug if weight else metric.weight_member
        local_metrics.append(
            CatalogMetric(
                slug=metric.slug,
                label=metric.label,
                semantic_view=metric.semantic_view,
                aggregation=metric.operation,
                source_field=source_slug,
                weight_field=weight_slug,
                percentile=(metric.definition or {}).get("percentile"),
                confidence_level=metric.confidence_level,
                parameters=metric.definition or {},
                visibility=metric.visibility,
            )
        )
    return SemanticCatalog(
        fields=(*_CORE_FIELDS, *local_fields),
        metrics=(*_CORE_METRICS, *local_metrics),
    )


def _validate_field_record(field: AnalyticsField) -> None:
    validate_identifier(field.slug)
    if field.semantic_view not in _SEMANTIC_VIEWS:
        raise AnalyticsValidationError("Unknown semantic view")
    FieldType(field.data_type)
    Visibility(field.visibility)
    if field.source_kind not in {"core", "raw_json"}:
        raise AnalyticsValidationError("Unsupported field source")
    if field.source_kind == "raw_json" and (
        not field.source_key or len(field.source_key) > 128 or "\x00" in field.source_key
    ):
        raise AnalyticsValidationError("Raw fields require a safe source key")
    if any(
        item.slug == field.slug
        and item.semantic_view in _field_semantic_views(field)
        for item in _CORE_FIELDS
    ):
        raise AnalyticsValidationError("Local field collides with a core dimension")


def _field_semantic_views(field: AnalyticsField) -> tuple[str, ...]:
    if field.source_kind == "raw_json" and field.semantic_view == "survey_responses":
        return tuple(sorted(_SEMANTIC_VIEWS))
    return (field.semantic_view,)


def _validate_metric_record(
    metric: AnalyticsMetric, fields: list[AnalyticsField], catalog: SemanticCatalog
) -> None:
    field_by_id = {field.id: field for field in fields}
    source = field_by_id.get(metric.field_id)
    weight = field_by_id.get(metric.weight_field_id)
    if metric.field_id is not None and metric.source_member is not None:
        raise AnalyticsValidationError(
            "Metric source uses either a promoted field or a core member"
        )
    if metric.weight_field_id is not None and metric.weight_member is not None:
        raise AnalyticsValidationError(
            "Metric weight uses either a promoted field or a core member"
        )
    if metric.field_id is not None and source is None:
        raise AnalyticsValidationError("Metric source field is not published")
    if metric.weight_field_id is not None and weight is None:
        raise AnalyticsValidationError("Metric weight field is not published")
    for member, label in (
        (metric.source_member, "source"),
        (metric.weight_member, "weight"),
    ):
        if member is not None and not any(
            field.slug == member and field.semantic_view == metric.semantic_view
            for field in _CORE_FIELDS
        ):
            raise AnalyticsValidationError(f"Metric core {label} member is unknown")
    source_slug = source.slug if source else metric.source_member
    weight_slug = weight.slug if weight else metric.weight_member
    candidate = CatalogMetric(
        slug=metric.slug,
        label=metric.label,
        semantic_view=metric.semantic_view,
        aggregation=metric.operation,
        source_field=source_slug,
        weight_field=weight_slug,
        percentile=(metric.definition or {}).get("percentile"),
        confidence_level=metric.confidence_level,
        parameters=metric.definition or {},
        visibility=metric.visibility,
    )
    validate_metric(candidate, catalog)
    operation = Aggregation(metric.operation)
    source_definition = (
        catalog.field(source_slug, metric.semantic_view) if source_slug else None
    )
    _validate_metric_filter(operation, metric.definition or {}, source_definition)
    if operation in _CI_OPERATIONS:
        if metric.confidence_level is None or not 0.8 <= metric.confidence_level <= 0.999:
            raise AnalyticsValidationError(
                "Confidence level must be between 0.8 and 0.999"
            )
    elif metric.confidence_level is not None:
        raise AnalyticsValidationError(
            "confidence_level is limited to confidence-interval metrics"
        )
    if metric.visibility == "viewer":
        for dependency_slug in (source_slug, weight_slug):
            if dependency_slug and catalog.field(
                dependency_slug, metric.semantic_view
            ).visibility is not Visibility.VIEWER:
                raise AnalyticsValidationError(
                    "Viewer metrics cannot depend on admin-only fields"
                )


def _metric_filter_value_is_valid(value: Any, field_type: str) -> bool:
    if value is None:
        return False
    if field_type == FieldType.NUMBER.value:
        return (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(float(value))
        )
    if field_type == FieldType.BOOLEAN.value:
        return isinstance(value, bool)
    if not isinstance(value, str) or len(value) > 500:
        return False
    if field_type == FieldType.DATE.value:
        try:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return False
    elif field_type == FieldType.TIME.value:
        try:
            datetime_time.fromisoformat(value)
        except ValueError:
            return False
    return True


def _validate_metric_filter(
    operation: Aggregation,
    definition: dict[str, Any],
    source: AnalyticsField | CatalogField | None,
) -> None:
    filtered_operations = {
        Aggregation.FILTERED_COUNT,
        Aggregation.FILTERED_RATE,
        Aggregation.WEIGHTED_FILTERED_RATE,
        Aggregation.PROPORTION_CONFIDENCE_INTERVAL,
        Aggregation.WEIGHTED_PROPORTION_CONFIDENCE_INTERVAL,
    }
    filter_definition = definition.get("filter")
    if operation not in filtered_operations:
        if filter_definition is not None:
            raise AnalyticsValidationError(
                "Only filtered metrics accept filter parameters"
            )
        return
    if source is None:
        raise AnalyticsValidationError("Filtered metrics require a source field")
    if not isinstance(filter_definition, dict):
        raise AnalyticsValidationError(
            "Filtered metrics require a structured filter"
        )
    allowed_keys = {"operator", "value", "values"}
    if set(filter_definition) - allowed_keys:
        raise AnalyticsValidationError("Filtered metric contains unknown filter keys")
    operator = filter_definition.get("operator")
    single_value = {
        "equals",
        "not_equals",
        "greater_than",
        "greater_than_or_equal",
        "less_than",
        "less_than_or_equal",
    }
    no_value = {"is_null", "is_not_null"}
    if operator in no_value:
        if "value" in filter_definition or "values" in filter_definition:
            raise AnalyticsValidationError(
                f"Filter {operator} does not accept values"
            )
        return
    if operator == "in":
        values = filter_definition.get("values")
        if (
            not isinstance(values, list)
            or not 1 <= len(values) <= 100
            or "value" in filter_definition
        ):
            raise AnalyticsValidationError("Filtered metric has an invalid values list")
    elif operator in single_value:
        if "value" not in filter_definition or "values" in filter_definition:
            raise AnalyticsValidationError(
                f"Filter {operator} requires exactly one value"
            )
        values = [filter_definition["value"]]
    else:
        raise AnalyticsValidationError("Filtered metric has an invalid operator")
    source_type = (
        source.data_type.value
        if isinstance(source.data_type, FieldType)
        else str(source.data_type)
    )
    if not all(_metric_filter_value_is_valid(value, source_type) for value in values):
        raise AnalyticsValidationError(
            f"Filtered metric requires {source_type} values"
        )


def _validate_chart_record(chart: AnalyticsChart, catalog: SemanticCatalog) -> None:
    definition = ChartDefinitionInput.model_validate(chart.definition or {})
    role = "viewer" if chart.visibility == "viewer" else "admin"
    chart_payload = {
        "chart_type": chart.chart_type,
        "semantic_view": chart.semantic_view,
        "definition": definition.model_dump(mode="json"),
    }
    _chart_query(chart_payload, None, catalog, role)


def _cube_catalog_payload(
    fields: list[AnalyticsField],
    metrics: list[AnalyticsMetric],
    catalog_version: int,
) -> dict[str, Any]:
    field_by_id = {field.id: field for field in fields}
    return {
        "profile": config.DEPLOYMENT_PROFILE,
        "catalogVersion": catalog_version,
        "fields": [
            {
                "slug": field.slug,
                "label": field.label,
                "semanticView": semantic_view,
                "dataType": field.data_type,
                "sourceKind": field.source_kind,
                "sourceKey": field.source_key,
                "visibility": field.visibility,
            }
            for field in fields
            for semantic_view in _field_semantic_views(field)
        ],
        "metrics": [
            {
                "slug": metric.slug,
                "label": metric.label,
                "semanticView": metric.semantic_view,
                "operation": metric.operation,
                "sourceField": field_by_id[metric.field_id].slug
                if metric.field_id is not None and metric.field_id in field_by_id
                else metric.source_member,
                "weightField": field_by_id[metric.weight_field_id].slug
                if metric.weight_field_id is not None
                and metric.weight_field_id in field_by_id
                else metric.weight_member,
                "confidenceLevel": metric.confidence_level,
                "parameters": metric.definition or {},
                "visibility": metric.visibility,
            }
            for metric in metrics
        ],
    }


def _chart_rollups(
    charts: Any, metrics: Any
) -> list[dict[str, Any]]:
    """Compile stable chart-specific pre-aggregation metadata.

    The active chart snapshot is already catalog-validated. This function still
    fails closed on malformed legacy snapshots and never emits raw SQL.
    """

    if not isinstance(charts, list) or not isinstance(metrics, list):
        return []
    operation_by_metric = {
        item.get("slug"): item.get("operation")
        for item in metrics
        if isinstance(item, dict)
    }
    additive = {
        Aggregation.COUNT.value,
        Aggregation.FILTERED_COUNT.value,
        Aggregation.SUM.value,
        Aggregation.WEIGHTED_SUM.value,
        Aggregation.MIN.value,
        Aggregation.MAX.value,
    }
    rollups: list[dict[str, Any]] = []
    for chart in charts:
        if not isinstance(chart, dict) or chart.get("status") != "published":
            continue
        definition = chart.get("definition") or {}
        if not isinstance(definition, dict):
            continue
        dimensions = definition.get("dimensions") or []
        measures = definition.get("metrics") or []
        if (
            not isinstance(dimensions, list)
            or not isinstance(measures, list)
            or not measures
            or len(dimensions) > 3
            or len(measures) > 5
        ):
            # Store maps use four dimensions and intentionally fall back to the
            # database unless a narrower map aggregation is defined.
            continue
        try:
            view = validate_identifier(str(chart["semantic_view"]))
            safe_dimensions = [validate_identifier(str(item)) for item in dimensions]
            safe_measures = [validate_identifier(str(item)) for item in measures]
        except (KeyError, AnalyticsValidationError):
            continue
        time_dimension = definition.get("time_dimension")
        if time_dimension is not None:
            try:
                time_dimension = validate_identifier(str(time_dimension))
            except AnalyticsValidationError:
                continue
        configured_granularity = definition.get("time_granularity")
        if time_dimension is not None and configured_granularity not in {
            "day",
            "month",
        }:
            # Only exact daily/monthly chart grains are materialized. Other
            # granularities deliberately fall back to PostgreSQL.
            continue
        granularity = (
            configured_granularity
            if configured_granularity in {"day", "month"}
            else None
        )
        identity = json.dumps(
            {
                "chart_id": chart.get("id"),
                "view": view,
                "dimensions": safe_dimensions,
                "measures": safe_measures,
                "time_dimension": time_dimension,
                "granularity": granularity,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:12]
        chart_id = chart.get("id")
        id_component = str(chart_id) if isinstance(chart_id, int) and chart_id > 0 else "local"
        name = validate_identifier(f"chart_{id_component}_{digest}")
        rollup = {
            "name": name,
            "semanticView": view,
            "measures": safe_measures,
            "dimensions": safe_dimensions,
            "timeDimension": time_dimension,
            "granularity": granularity,
            "nonAdditive": any(
                operation_by_metric.get(metric) not in additive
                for metric in safe_measures
            ),
        }
        if granularity is not None:
            rollup["partitionGranularity"] = (
                "year" if granularity == "month" else "month"
            )
        rollups.append(rollup)
    return rollups


viewer_router = APIRouter(
    prefix="/analytics",
    tags=["analytics"],
    dependencies=[Depends(_analytics_enabled), Depends(_analytics_no_store)],
)
admin_router = APIRouter(
    prefix="/admin/analytics",
    tags=["admin analytics"],
    dependencies=[
        Depends(_analytics_enabled),
        Depends(_analytics_no_store),
        Depends(require_admin),
    ],
)
# The first rollout exposes only chart authoring. Field/metric/catalog lifecycle
# handlers remain private implementation support for existing catalog records;
# they are deliberately not included in the public application router.
admin_chart_router = APIRouter(
    prefix="/admin/analytics",
    tags=["admin analytics"],
    dependencies=[
        Depends(_analytics_enabled),
        Depends(_analytics_no_store),
        Depends(require_admin),
    ],
)
internal_router = APIRouter(
    prefix="/internal/analytics",
    tags=["internal analytics"],
    dependencies=[Depends(_analytics_no_store)],
)


@viewer_router.get(
    "/catalog", summary="Get the active analytics catalog", description=_ENDPOINT_DESCRIPTIONS["viewer_catalog"]
)
async def get_catalog(
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
) -> dict[str, Any]:
    role = _role(current_user)
    try:
        catalog = _catalog(db, role)
    except (AnalyticsValidationError, ValueError) as error:
        raise HTTPException(status_code=503, detail="Analytics catalog is invalid") from error
    version = _active_model_version(db)
    return _catalog_response(catalog, version.catalog_version if version else 0)


@viewer_router.get(
    "/catalog/availability",
    summary="Get field data availability",
    description=_ENDPOINT_DESCRIPTIONS["viewer_availability"],
)
async def get_catalog_availability(
    semantic_view: Literal[
        "survey_responses",
        "survey_topics",
        "survey_departments",
        "survey_keywords",
    ] = "survey_responses",
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    role = _role(current_user)
    try:
        catalog = _catalog(db, role)
        version = _active_model_version(db)
        return _field_availability(
            db,
            catalog,
            role=role,
            semantic_view=semantic_view,
            catalog_version=version.catalog_version if version else 0,
        )
    except (AnalyticsValidationError, ValueError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except SQLAlchemyError as error:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "analytics_availability_unavailable",
                "message": "Field availability is temporarily unavailable",
            },
        ) from error


@viewer_router.post(
    "/filter-options",
    summary="List available filter values",
    description=_ENDPOINT_DESCRIPTIONS["viewer_filter_options"],
)
async def get_filter_options(
    payload: FilterOptionsInput,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Build a role-scoped filter dropdown from the governed semantic catalog."""

    role = _role(current_user)
    try:
        catalog = _catalog(db, role)
        field = catalog.field(payload.member, payload.semantic_view)
        count_metric = _FILTER_OPTION_COUNT_METRICS[payload.semantic_view]
        optional_metrics: list[str] = []
        for metric_slug in payload.metrics:
            if metric_slug == count_metric:
                raise AnalyticsValidationError(
                    "The fixed filter option count metric must not be requested"
                )
            catalog.metric(metric_slug, payload.semantic_view)
            optional_metrics.append(metric_slug)
        filters: tuple[FilterSpec, ...] = (
            *payload.filters,
            FilterSpec(member=payload.member, operator="set"),
        )
        if payload.search is not None:
            if field.data_type is not FieldType.STRING:
                raise AnalyticsValidationError("search is available only for string fields")
            filters = (
                *filters,
                FilterSpec(
                    member=payload.member,
                    operator="contains",
                    value=payload.search,
                ),
            )
        query = QuerySpec(
            semantic_view=payload.semantic_view,
            dimensions=(payload.member,),
            metrics=(count_metric, *optional_metrics),
            filters=filters,
            timezone=payload.timezone,
            order=(
                OrderSpec(member=count_metric, direction="desc"),
                OrderSpec(member=payload.member, direction="asc"),
            ),
            limit=payload.limit,
        )
        cube_query = compile_cube_query(query, catalog, role)
        cube_query["offset"] = payload.cursor or 0
    except (AnalyticsValidationError, ValueError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    result = await _execute_query(
        query, db, current_user, cube_query_override=cube_query
    )
    values = [
        {
            "value": row.get(payload.member),
            "count": row.get(count_metric, 0),
            "metrics": {
                metric_slug: row.get(metric_slug)
                for metric_slug in payload.metrics
            },
        }
        for row in result["rows"]
        if row.get(payload.member) is not None
    ]
    cursor = payload.cursor or 0
    has_more = len(values) == payload.limit
    return {
        "query_id": result["query_id"],
        "model_version": result["model_version"],
        "timezone": query.timezone or "UTC",
        "semantic_view": payload.semantic_view,
        "member": payload.member,
        "label": field.label,
        "data_type": field.data_type.value,
        "metric_columns": [
            column
            for column in _column_metadata(
                QuerySpec(
                    semantic_view=payload.semantic_view,
                    dimensions=(payload.member,),
                    metrics=tuple(payload.metrics),
                ),
                catalog,
            )
            if column["kind"] == "metric"
        ],
        "values": values,
        "cursor": cursor,
        "next_cursor": cursor + len(values) if has_more else None,
        "has_more": has_more,
        "warnings": result["warnings"],
        "freshness_time": result["freshness_time"],
    }


@viewer_router.post(
    "/query", summary="Run a governed aggregate query", description=_ENDPOINT_DESCRIPTIONS["viewer_query"]
)
async def query_analytics(
    payload: QuerySpec,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    return await _execute_query(payload, db, current_user)


@viewer_router.post(
    "/records/query",
    summary="Query governed analytics records",
    description=_ENDPOINT_DESCRIPTIONS["viewer_records_query"],
)
async def query_analytics_records(
    payload: RecordQueryInput,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    max_size = 100 if payload.resource == "surveys" else 1_000
    if payload.size > max_size:
        raise HTTPException(
            status_code=422,
            detail=f"Record pages for {payload.resource} are capped at {max_size} rows",
        )
    try:
        return query_records(
            db,
            payload.resource,
            tuple(payload.filters),
            tuple(payload.order),
            payload.page,
            payload.size,
            payload.timezone,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except SQLAlchemyError as error:
        db.rollback()
        raise HTTPException(
            status_code=503,
            detail={
                "code": "analytics_records_unavailable",
                "message": "Analytics records are temporarily unavailable",
            },
        ) from error


@viewer_router.get(
    "/charts/published", summary="List published charts", description=_ENDPOINT_DESCRIPTIONS["viewer_charts"]
)
async def get_published_charts(
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
) -> list[dict[str, Any]]:
    return _snapshot_charts(_active_model_version(db), _role(current_user))


@viewer_router.post(
    "/charts/{chart_id}/data", summary="Run published chart data", description=_ENDPOINT_DESCRIPTIONS["viewer_chart_data"]
)
async def get_published_chart_data(
    chart_id: int,
    payload: ChartDataInput | None = Body(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    role = _role(current_user)
    chart = next(
        (
            item
            for item in _snapshot_charts(_active_model_version(db), role)
            if item.get("id") == chart_id
        ),
        None,
    )
    if chart is None:
        raise HTTPException(status_code=404, detail="Published chart not found")
    try:
        catalog = _catalog(db, role)
        query, cube_query = _chart_query(chart, payload, catalog, role)
    except (AnalyticsValidationError, ValueError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    response = await _execute_query(
        query, db, current_user, cube_query_override=cube_query
    )
    response["chart"] = chart
    other_value: Any = None
    other_response: dict[str, Any] | None = None
    if chart["chart_type"] in {"pie", "donut"} and len(response.get("rows") or []) > 12:
        definition = chart.get("definition") or {}
        dimension = definition["dimensions"][0]
        metric = definition["metrics"][0]
        top_values = tuple(
            row.get(dimension)
            for row in response["rows"][:12]
            if row.get(dimension) is not None
        )
        if top_values:
            remainder_query = query.model_copy(
                update={
                    "dimensions": (),
                    "filters": (
                        *query.filters,
                        FilterSpec(
                            member=dimension,
                            operator="not_in",
                            values=top_values,
                        ),
                    ),
                    "time_granularity": None,
                    "order": (),
                    "limit": 1,
                }
            )
            remainder_cube_query = compile_cube_query(
                remainder_query, catalog, role
            )
            # Cube combines top-level filters with AND. The tail must include
            # both non-top values and the NULL category, so make just this
            # governed exclusion an explicit OR group.
            exclusion = remainder_cube_query["filters"].pop()
            remainder_cube_query["filters"].append(
                {
                    "or": [
                        exclusion,
                        {
                            "member": f"{chart['semantic_view']}.{dimension}",
                            "operator": "notSet",
                        },
                    ]
                }
            )
            remainder = await _execute_query(
                remainder_query,
                db,
                current_user,
                cube_query_override=remainder_cube_query,
            )
            if remainder.get("rows"):
                other_value = remainder["rows"][0].get(metric)
                other_response = remainder
    return _shape_chart_rows(chart, response, other_value, other_response)


def _metadata_now() -> int:
    return int(time.time())


def _next_catalog_version(current_max: int | None) -> int:
    """Return the next monotonic catalog version, beginning at version one."""
    return int(current_max or 0) + 1


def _validate_cube_catalog_size(payload: dict[str, Any]) -> None:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    ).encode("utf-8")
    if len(encoded) > _MAX_CUBE_CATALOG_BYTES:
        raise AnalyticsValidationError(
            "Published analytics catalog exceeds the Cube compiler size limit"
        )


def _export_admission_lock_key(profile: str) -> int:
    digest = hashlib.sha256(f"analytics-exports:{profile}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=True)


def _lock_export_admission(db: Session) -> None:
    """Serialize profile-local quota admission until the transaction commits."""
    bind = db.get_bind()
    if bind.dialect.name == "postgresql":
        db.execute(
            sql_text("SELECT pg_advisory_xact_lock(:lock_key)"),
            {"lock_key": _export_admission_lock_key(config.DEPLOYMENT_PROFILE)},
        )


@internal_router.get(
    "/catalog", summary="Get signed Cube catalog metadata", description=_ENDPOINT_DESCRIPTIONS["internal_catalog"]
)
async def get_internal_catalog(
    response: Response,
    x_analytics_profile: str = Header(alias="X-Analytics-Profile"),
    x_analytics_timestamp: str = Header(alias="X-Analytics-Timestamp"),
    x_analytics_signature: str = Header(alias="X-Analytics-Signature"),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    if x_analytics_profile != config.DEPLOYMENT_PROFILE:
        raise HTTPException(status_code=403, detail="Analytics profile mismatch")
    if not verify_metadata_signature(
        config.ANALYTICS_INTERNAL_METADATA_SECRET,
        x_analytics_profile,
        x_analytics_timestamp,
        x_analytics_signature,
        now=_metadata_now(),
    ):
        raise HTTPException(status_code=401, detail="Invalid analytics metadata signature")
    response.headers["Cache-Control"] = "no-store, private"
    return _extract_cube_catalog(_active_model_version(db))


def _record_or_404(db: Session, model: Any, record_id: int, label: str) -> Any:
    record = db.query(model).filter(model.id == record_id).first()
    if record is None:
        raise HTTPException(status_code=404, detail=f"{label} not found")
    return record


def _chart_dimension_dependencies(definition: dict[str, Any]) -> set[str]:
    result = {
        str(member) for member in definition.get("dimensions", []) if isinstance(member, str)
    }
    time_dimension = definition.get("time_dimension")
    if isinstance(time_dimension, str):
        result.add(time_dimension)
    for key in ("filters", "order"):
        for item in definition.get(key, []) or []:
            if isinstance(item, dict) and isinstance(item.get("member"), str):
                result.add(item["member"])
    return result


def _ensure_unique_slug(
    db: Session, model: Any, slug: str, excluding_id: int | None = None
) -> None:
    query = db.query(model).filter(model.slug == slug)
    if excluding_id is not None:
        query = query.filter(model.id != excluding_id)
    if query.first() is not None:
        raise HTTPException(status_code=409, detail="Slug already exists")


@admin_router.get(
    "/candidates", summary="List discovered field candidates", description=_ENDPOINT_DESCRIPTIONS["admin_candidates"]
)
async def list_candidates(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    records = (
        db.query(AnalyticsField)
        .filter(AnalyticsField.status == "candidate")
        .order_by(AnalyticsField.updated_at.desc())
        .all()
    )
    return [record.to_dict() for record in records]


@admin_router.get(
    "/fields", summary="List governed fields", description=_ENDPOINT_DESCRIPTIONS["admin_fields_list"]
)
async def list_fields(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    return [
        record.to_dict()
        for record in db.query(AnalyticsField)
        .order_by(AnalyticsField.updated_at.desc())
        .all()
    ]


@admin_router.get(
    "/fields/{field_id}", summary="Get governed field", description=_ENDPOINT_DESCRIPTIONS["admin_field_get"]
)
async def get_field(field_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    return _record_or_404(db, AnalyticsField, field_id, "Field").to_dict()


@admin_router.post(
    "/fields", status_code=201, summary="Create governed field", description=_ENDPOINT_DESCRIPTIONS["admin_field_create"]
)
async def create_field(
    payload: FieldInput,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> dict[str, Any]:
    _ensure_unique_slug(db, AnalyticsField, payload.slug)
    field = AnalyticsField(
        **payload.model_dump(mode="json"),
        status="draft",
        is_promoted=True,
        promoted_at=utc_now(),
        created_by_id=current_user.id,
    )
    try:
        _validate_field_record(field)
    except (AnalyticsValidationError, ValueError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    db.add(field)
    db.flush()
    _audit(db, current_user, "field.created", "field", field.id, {"slug": field.slug})
    db.commit()
    db.refresh(field)
    return field.to_dict()


@admin_router.put(
    "/fields/{field_id}", summary="Update governed field", description=_ENDPOINT_DESCRIPTIONS["admin_field_update"]
)
async def update_field(
    field_id: int,
    payload: FieldInput,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> dict[str, Any]:
    field = _record_or_404(db, AnalyticsField, field_id, "Field")
    if field.status == "archived":
        raise HTTPException(status_code=409, detail="Archived fields cannot be changed")
    _ensure_unique_slug(db, AnalyticsField, payload.slug, field_id)
    for key, value in payload.model_dump(mode="json").items():
        setattr(field, key, value)
    field.status = "draft"
    field.published_at = None
    _validate_field_record(field)
    _audit(db, current_user, "field.updated", "field", field.id)
    db.commit()
    db.refresh(field)
    return field.to_dict()


@admin_router.post(
    "/fields/{field_id}/promote", summary="Promote field candidate", description=_ENDPOINT_DESCRIPTIONS["admin_field_promote"]
)
async def promote_candidate(
    field_id: int,
    payload: CandidatePromotionInput,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> dict[str, Any]:
    field = _record_or_404(db, AnalyticsField, field_id, "Field")
    if field.status == "archived":
        raise HTTPException(status_code=409, detail="Archived fields cannot be promoted")
    field.data_type = payload.data_type.value
    field.visibility = payload.visibility.value
    if payload.label:
        field.label = payload.label.strip()
    if payload.description is not None:
        field.description = payload.description
    field.is_promoted = True
    field.promoted_at = utc_now()
    field.status = "draft"
    if field.created_by_id is None:
        field.created_by_id = current_user.id
    _validate_field_record(field)
    _audit(db, current_user, "field.promoted", "field", field.id)
    db.commit()
    db.refresh(field)
    return field.to_dict()


@admin_router.post(
    "/fields/{field_id}/validate", summary="Validate governed field", description=_ENDPOINT_DESCRIPTIONS["admin_field_validate"]
)
async def validate_field(
    field_id: int, db: Session = Depends(get_db)
) -> dict[str, Any]:
    field = _record_or_404(db, AnalyticsField, field_id, "Field")
    try:
        _validate_field_record(field)
    except (AnalyticsValidationError, ValueError) as error:
        return {"valid": False, "errors": [str(error)]}
    return {"valid": True, "errors": []}


@admin_router.post(
    "/fields/{field_id}/publish", summary="Publish governed field", description=_ENDPOINT_DESCRIPTIONS["admin_field_publish"]
)
async def publish_field(
    field_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> dict[str, Any]:
    field = _record_or_404(db, AnalyticsField, field_id, "Field")
    if not field.is_promoted:
        raise HTTPException(status_code=422, detail="Field must be promoted first")
    try:
        _validate_field_record(field)
    except (AnalyticsValidationError, ValueError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    field.status = "published"
    field.published_at = utc_now()
    _audit(db, current_user, "field.published", "field", field.id)
    db.commit()
    db.refresh(field)
    return field.to_dict()


@admin_router.post(
    "/fields/{field_id}/archive", summary="Archive governed field", description=_ENDPOINT_DESCRIPTIONS["admin_field_archive"]
)
async def archive_field(
    field_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> dict[str, Any]:
    field = _record_or_404(db, AnalyticsField, field_id, "Field")
    dependency = (
        db.query(AnalyticsMetric)
        .filter(
            AnalyticsMetric.status == "published",
            or_(
                AnalyticsMetric.field_id == field.id,
                AnalyticsMetric.weight_field_id == field.id,
            ),
        )
        .first()
    )
    published_charts = (
        db.query(AnalyticsChart)
        .filter(AnalyticsChart.status == "published")
        .all()
    )
    directly_referenced = any(
        field.slug in _chart_dimension_dependencies(chart.definition or {})
        for chart in published_charts
    )
    if dependency is not None or directly_referenced:
        raise HTTPException(
            status_code=409, detail="Field is referenced by a published definition"
        )
    field.status = "archived"
    field.archived_at = utc_now()
    field.is_promoted = False
    _audit(db, current_user, "field.archived", "field", field.id)
    db.commit()
    db.refresh(field)
    return field.to_dict()


@admin_router.get(
    "/metrics", summary="List governed metrics", description=_ENDPOINT_DESCRIPTIONS["admin_metrics_list"]
)
async def list_metrics(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    return [
        record.to_dict()
        for record in db.query(AnalyticsMetric)
        .order_by(AnalyticsMetric.updated_at.desc())
        .all()
    ]


@admin_router.get(
    "/metrics/{metric_id}", summary="Get governed metric", description=_ENDPOINT_DESCRIPTIONS["admin_metric_get"]
)
async def get_metric(metric_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    return _record_or_404(db, AnalyticsMetric, metric_id, "Metric").to_dict()


def _assign_metric(metric: AnalyticsMetric, payload: MetricInput) -> None:
    for key, value in payload.model_dump(mode="json").items():
        setattr(metric, key, value)


@admin_router.post(
    "/metrics", status_code=201, summary="Create governed metric", description=_ENDPOINT_DESCRIPTIONS["admin_metric_create"]
)
async def create_metric(
    payload: MetricInput,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> dict[str, Any]:
    _ensure_unique_slug(db, AnalyticsMetric, payload.slug)
    metric = AnalyticsMetric(created_by_id=current_user.id, status="draft")
    _assign_metric(metric, payload)
    db.add(metric)
    db.flush()
    _audit(db, current_user, "metric.created", "metric", metric.id, {"slug": metric.slug})
    db.commit()
    db.refresh(metric)
    return metric.to_dict()


@admin_router.put(
    "/metrics/{metric_id}", summary="Update governed metric", description=_ENDPOINT_DESCRIPTIONS["admin_metric_update"]
)
async def update_metric(
    metric_id: int,
    payload: MetricInput,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> dict[str, Any]:
    metric = _record_or_404(db, AnalyticsMetric, metric_id, "Metric")
    if metric.status == "archived":
        raise HTTPException(status_code=409, detail="Archived metrics cannot be changed")
    _ensure_unique_slug(db, AnalyticsMetric, payload.slug, metric_id)
    _assign_metric(metric, payload)
    metric.status = "draft"
    metric.published_at = None
    metric.published_model_version_id = None
    _audit(db, current_user, "metric.updated", "metric", metric.id)
    db.commit()
    db.refresh(metric)
    return metric.to_dict()


def _validate_metric_for_admin(db: Session, metric: AnalyticsMetric) -> None:
    fields = (
        db.query(AnalyticsField)
        .filter(
            AnalyticsField.status == "published",
            AnalyticsField.is_promoted.is_(True),
            AnalyticsField.archived_at.is_(None),
        )
        .all()
    )
    catalog = _catalog_from_records(fields, [metric])
    _validate_metric_record(metric, fields, catalog)


@admin_router.post(
    "/metrics/{metric_id}/validate", summary="Validate governed metric", description=_ENDPOINT_DESCRIPTIONS["admin_metric_validate"]
)
async def validate_metric_endpoint(
    metric_id: int, db: Session = Depends(get_db)
) -> dict[str, Any]:
    metric = _record_or_404(db, AnalyticsMetric, metric_id, "Metric")
    try:
        _validate_metric_for_admin(db, metric)
    except (AnalyticsValidationError, ValueError) as error:
        return {"valid": False, "errors": [str(error)]}
    return {"valid": True, "errors": []}


@admin_router.post(
    "/metrics/{metric_id}/publish", summary="Publish governed metric", description=_ENDPOINT_DESCRIPTIONS["admin_metric_publish"]
)
async def publish_metric(
    metric_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> dict[str, Any]:
    metric = _record_or_404(db, AnalyticsMetric, metric_id, "Metric")
    try:
        _validate_metric_for_admin(db, metric)
    except (AnalyticsValidationError, ValueError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    metric.status = "published"
    metric.published_at = utc_now()
    _audit(db, current_user, "metric.published", "metric", metric.id)
    db.commit()
    db.refresh(metric)
    return metric.to_dict()


@admin_router.post(
    "/metrics/{metric_id}/archive", summary="Archive governed metric", description=_ENDPOINT_DESCRIPTIONS["admin_metric_archive"]
)
async def archive_metric(
    metric_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> dict[str, Any]:
    metric = _record_or_404(db, AnalyticsMetric, metric_id, "Metric")
    charts = (
        db.query(AnalyticsChart)
        .filter(AnalyticsChart.status == "published")
        .all()
    )
    if any(
        metric.slug in set((chart.definition or {}).get("metrics", []))
        for chart in charts
    ):
        raise HTTPException(
            status_code=409, detail="Metric is referenced by a published chart"
        )
    metric.status = "archived"
    metric.archived_at = utc_now()
    _audit(db, current_user, "metric.archived", "metric", metric.id)
    db.commit()
    db.refresh(metric)
    return metric.to_dict()


@admin_chart_router.get(
    "/charts", summary="List chart definitions", description=_ENDPOINT_DESCRIPTIONS["admin_charts_list"]
)
async def list_charts(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    return [
        record.to_dict()
        for record in db.query(AnalyticsChart)
        .order_by(AnalyticsChart.updated_at.desc())
        .all()
    ]


@admin_chart_router.get(
    "/charts/{chart_id}", summary="Get chart definition", description=_ENDPOINT_DESCRIPTIONS["admin_chart_get"]
)
async def get_chart(chart_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    return _record_or_404(db, AnalyticsChart, chart_id, "Chart").to_dict()


def _assign_chart(chart: AnalyticsChart, payload: ChartInput) -> None:
    values = payload.model_dump(mode="json")
    values["definition"] = payload.definition.model_dump(mode="json")
    for key, value in values.items():
        setattr(chart, key, value)


@admin_chart_router.post(
    "/charts", status_code=201, summary="Create chart definition", description=_ENDPOINT_DESCRIPTIONS["admin_chart_create"]
)
async def create_chart(
    payload: ChartInput,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> dict[str, Any]:
    _ensure_unique_slug(db, AnalyticsChart, payload.slug)
    chart = AnalyticsChart(created_by_id=current_user.id, status="draft")
    _assign_chart(chart, payload)
    db.add(chart)
    db.flush()
    _audit(db, current_user, "chart.created", "chart", chart.id, {"slug": chart.slug})
    db.commit()
    db.refresh(chart)
    return chart.to_dict()


@admin_chart_router.put(
    "/charts/{chart_id}", summary="Update chart definition", description=_ENDPOINT_DESCRIPTIONS["admin_chart_update"]
)
async def update_chart(
    chart_id: int,
    payload: ChartInput,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> dict[str, Any]:
    chart = _record_or_404(db, AnalyticsChart, chart_id, "Chart")
    if chart.status == "archived":
        raise HTTPException(status_code=409, detail="Archived charts cannot be changed")
    _ensure_unique_slug(db, AnalyticsChart, payload.slug, chart_id)
    _assign_chart(chart, payload)
    chart.status = "draft"
    chart.validation_errors = []
    chart.validated_at = None
    chart.published_at = None
    chart.published_model_version_id = None
    _audit(db, current_user, "chart.updated", "chart", chart.id)
    db.commit()
    db.refresh(chart)
    return chart.to_dict()


def _validate_chart_for_admin(db: Session, chart: AnalyticsChart) -> None:
    fields, metrics, _ = _current_published_records(db)
    catalog = _catalog_from_records(fields, metrics)
    _validate_chart_record(chart, catalog)


@admin_router.post(
    "/charts/{chart_id}/validate", summary="Validate chart definition", description=_ENDPOINT_DESCRIPTIONS["admin_chart_validate"]
)
async def validate_chart_endpoint(
    chart_id: int, db: Session = Depends(get_db)
) -> dict[str, Any]:
    chart = _record_or_404(db, AnalyticsChart, chart_id, "Chart")
    try:
        _validate_chart_for_admin(db, chart)
    except (AnalyticsValidationError, ValueError) as error:
        chart.validation_errors = [str(error)]
        chart.validated_at = utc_now()
        db.commit()
        return {"valid": False, "errors": chart.validation_errors}
    chart.validation_errors = []
    chart.validated_at = utc_now()
    db.commit()
    return {"valid": True, "errors": []}


@admin_chart_router.post(
    "/charts/{chart_id}/publish", summary="Publish chart definition", description=_ENDPOINT_DESCRIPTIONS["admin_chart_publish"]
)
async def publish_chart(
    chart_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> dict[str, Any]:
    chart = _record_or_404(db, AnalyticsChart, chart_id, "Chart")
    if chart.status == "archived":
        raise HTTPException(
            status_code=409,
            detail="Archived charts cannot be published; create a replacement chart",
        )
    try:
        _validate_chart_for_admin(db, chart)
    except (AnalyticsValidationError, ValueError) as error:
        chart.validation_errors = [str(error)]
        chart.validated_at = utc_now()
        db.commit()
        raise HTTPException(status_code=422, detail=str(error)) from error
    chart.status = "published"
    chart.validation_errors = []
    chart.validated_at = utc_now()
    chart.published_at = utc_now()
    # Older deployments allowed an archived chart to be published without
    # clearing this timestamp. A published chart must be eligible for the
    # active snapshot, so repair that inconsistent legacy state on publish.
    chart.archived_at = None
    _audit(db, current_user, "chart.published", "chart", chart.id)
    # SessionLocal intentionally does not rely on implicit autoflush. The
    # catalog builder queries the database, so persist this lifecycle change
    # before it selects published charts for the immutable snapshot.
    db.flush()
    # Charts are the only administrator-managed semantic objects in the
    # simplified rollout. Activation is therefore part of publication rather
    # than a second, easy-to-miss administrative action.
    try:
        version = await publish_catalog_version(
            CatalogPublicationInput(description=f"Publish chart {chart.slug}"),
            db,
            current_user,
        )
    except HTTPException:
        # Catalog activation can still be blocked by another, older chart.
        # Do not leave this chart marked published when it was never added to
        # an active catalog snapshot.
        chart.status = "draft"
        chart.published_at = None
        chart.published_model_version_id = None
        _audit(db, current_user, "chart.publish_failed", "chart", chart.id)
        db.commit()
        raise
    db.refresh(chart)
    return {**chart.to_dict(), "model_version": version["catalog_version"]}


@admin_chart_router.delete(
    "/charts/{chart_id}", summary="Delete chart definition", description=_ENDPOINT_DESCRIPTIONS["admin_chart_archive"]
)
async def delete_chart(
    chart_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> dict[str, Any]:
    chart = _record_or_404(db, AnalyticsChart, chart_id, "Chart")
    chart.status = "archived"
    chart.archived_at = utc_now()
    _audit(db, current_user, "chart.archived", "chart", chart.id)
    # Exclude the chart from the catalog snapshot being activated below.
    db.flush()
    version = await publish_catalog_version(
        CatalogPublicationInput(description=f"Delete chart {chart.slug}"),
        db,
        current_user,
    )
    db.refresh(chart)
    return {**chart.to_dict(), "model_version": version["catalog_version"]}


@admin_router.get(
    "/catalog/versions", summary="List catalog versions", description=_ENDPOINT_DESCRIPTIONS["admin_versions"]
)
async def list_catalog_versions(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    versions = (
        db.query(AnalyticsModelVersion)
        .order_by(AnalyticsModelVersion.catalog_version.desc())
        .all()
    )
    return [version.to_dict() for version in versions]


@admin_router.get(
    "/catalog/versions/{version_id}", summary="Get catalog version", description=_ENDPOINT_DESCRIPTIONS["admin_version_get"]
)
async def get_catalog_version(
    version_id: int, db: Session = Depends(get_db)
) -> dict[str, Any]:
    return _record_or_404(
        db, AnalyticsModelVersion, version_id, "Catalog version"
    ).to_dict(include_snapshot=True)


@admin_router.post(
    "/catalog/publish", status_code=201, summary="Activate a catalog version", description=_ENDPOINT_DESCRIPTIONS["admin_catalog_publish"]
)
async def publish_catalog_version(
    payload: CatalogPublicationInput,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> dict[str, Any]:
    if _PROFILE.fullmatch(config.DEPLOYMENT_PROFILE) is None:
        raise HTTPException(status_code=422, detail="Invalid analytics deployment profile")
    fields, metrics, charts = _current_published_records(db)
    errors: list[dict[str, Any]] = []
    try:
        for field in fields:
            _validate_field_record(field)
        catalog = _catalog_from_records(fields, metrics)
        for metric in metrics:
            _validate_metric_record(metric, fields, catalog)
    except (AnalyticsValidationError, ValueError) as error:
        errors.append({"resource": "catalog", "error": str(error)})
        catalog = None

    if catalog is not None:
        for chart in charts:
            try:
                _validate_chart_record(chart, catalog)
            except (AnalyticsValidationError, ValueError) as error:
                chart.validation_errors = [str(error)]
                chart.validated_at = utc_now()
                errors.append(
                    {"resource": "chart", "id": chart.id, "error": str(error)}
                )
            else:
                chart.validation_errors = []
                chart.validated_at = utc_now()
    if errors:
        _audit(
            db,
            current_user,
            "catalog.validation_failed",
            "catalog",
            "pending",
            {"error_count": len(errors)},
        )
        db.commit()
        raise HTTPException(
            status_code=422,
            detail={"message": "Catalog validation failed", "errors": errors},
        )

    current_max = db.query(func.max(AnalyticsModelVersion.catalog_version)).scalar()
    next_version = _next_catalog_version(current_max)
    cube_catalog = _cube_catalog_payload(fields, metrics, next_version)
    chart_snapshot = [chart.to_dict() for chart in charts]
    cube_catalog["rollups"] = _chart_rollups(
        chart_snapshot, cube_catalog["metrics"]
    )
    try:
        _validate_cube_catalog_size(cube_catalog)
    except AnalyticsValidationError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    snapshot = {"cubeCatalog": cube_catalog, "charts": chart_snapshot}
    definition_hash = hashlib.sha256(
        json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    now = utc_now()
    for active in (
        db.query(AnalyticsModelVersion)
        .filter(AnalyticsModelVersion.is_active.is_(True))
        .all()
    ):
        active.is_active = False
        active.status = "superseded"
        active.archived_at = now
    # The schema permits only one active catalog. Flush the deactivations
    # before inserting the replacement so publication does not depend on ORM
    # statement ordering under PostgreSQL's partial unique index.
    db.flush()
    version = AnalyticsModelVersion(
        catalog_version=next_version,
        status="published",
        definition_hash=definition_hash,
        catalog_snapshot=snapshot,
        validation_errors=[],
        is_active=True,
        created_by_id=current_user.id,
        published_at=now,
        activated_at=now,
    )
    db.add(version)
    try:
        db.flush()
        for metric in metrics:
            metric.published_model_version_id = version.id
        for chart in charts:
            chart.published_model_version_id = version.id
        _audit(
            db,
            current_user,
            "catalog.published",
            "catalog_version",
            version.id,
            {
                "catalog_version": next_version,
                "definition_hash": definition_hash,
                "description": payload.description,
            },
        )
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(
            status_code=409, detail="Catalog publication conflicted; retry"
        ) from error
    db.refresh(version)
    return version.to_dict(include_snapshot=True)


@viewer_router.post(
    "/drilldown", summary="Drill down to survey responses", description=_ENDPOINT_DESCRIPTIONS["viewer_drilldown"]
)
def drilldown_analytics(
    payload: DrilldownSpec,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    if not _DRILLDOWN_SEMAPHORE.acquire(blocking=False):
        raise HTTPException(
            status_code=429,
            detail={
                "code": "analytics_drilldown_capacity",
                "message": "Too many analytics drilldowns are already running",
            },
            headers={"Retry-After": "2"},
        )
    role = _role(current_user)
    query_id = str(uuid.uuid4())
    started = time.monotonic()
    try:
        catalog = _catalog(db, role)
        result = execute_drilldown(
            db,
            payload,
            catalog,
            role=role,
            raw_fields=_raw_field_sources(db, role),
        )
    except (AnalyticsValidationError, ValueError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except SQLAlchemyError as error:
        db.rollback()
        raise HTTPException(
            status_code=503,
            detail={
                "code": "analytics_drilldown_unavailable",
                "message": "Analytics drilldown is temporarily unavailable",
            },
        ) from error
    finally:
        _DRILLDOWN_SEMAPHORE.release()

    version = _active_model_version(db)
    db.add(
        AnalyticsQueryLog(
            id=query_id,
            requested_by_id=current_user.id,
            model_version_id=version.id if version else None,
            semantic_view=payload.semantic_view,
            request={"kind": "drilldown", **payload.model_dump(mode="json")},
            status="completed",
            row_count=len(result["rows"]),
            duration_ms=round((time.monotonic() - started) * 1_000),
            created_at=utc_now(),
            completed_at=utc_now(),
        )
    )
    _audit(
        db,
        current_user,
        "drilldown.executed",
        "query",
        query_id,
        {"row_count": len(result["rows"])},
    )
    db.commit()
    return {
        "query_id": query_id,
        "model_version": version.catalog_version if version else 0,
        "timezone": payload.timezone or "UTC",
        **result,
    }


@viewer_router.post(
    "/exports", status_code=201, summary="Queue analytics export", description=_ENDPOINT_DESCRIPTIONS["viewer_export_create"]
)
async def create_analytics_export(
    payload: ExportInput,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    role = _role(current_user)
    _lock_export_admission(db)
    outstanding_statuses = ("queued", "processing")
    user_outstanding = (
        db.query(func.count(AnalyticsExportJob.id))
        .filter(
            AnalyticsExportJob.requested_by_id == current_user.id,
            AnalyticsExportJob.status.in_(outstanding_statuses),
        )
        .scalar()
        or 0
    )
    profile_outstanding = (
        db.query(func.count(AnalyticsExportJob.id))
        .filter(AnalyticsExportJob.status.in_(outstanding_statuses))
        .scalar()
        or 0
    )
    if (
        user_outstanding >= config.ANALYTICS_EXPORT_MAX_OUTSTANDING_PER_USER
        or profile_outstanding >= config.ANALYTICS_EXPORT_MAX_OUTSTANDING_PROFILE
    ):
        raise HTTPException(
            status_code=429,
            detail={
                "code": "analytics_export_capacity",
                "message": "Too many analytics exports are already queued",
            },
            headers={"Retry-After": "30"},
        )
    version = _active_model_version(db)
    cube_query: dict[str, Any] | None = None
    semantic_view: str
    request_payload: dict[str, Any]
    try:
        catalog = _catalog(db, role)
        if payload.query is not None:
            semantic_view = payload.query.semantic_view
            cube_query = augment_cube_query_with_supports(
                compile_cube_query(payload.query, catalog, role),
                payload.query,
                catalog,
            )
            request_payload = {
                "mode": "query",
                "role": role,
                "semantic_query": payload.query.model_dump(mode="json"),
                "cube_query": cube_query,
            }
        else:
            if payload.drilldown is not None:
                semantic_view = payload.drilldown.semantic_view
                build_drilldown_statement(
                    payload.drilldown,
                    catalog,
                    role=role,
                    raw_fields=_raw_field_sources(db, role),
                )
                request_payload = {
                    "mode": "drilldown",
                    "role": role,
                    "drilldown": payload.drilldown.model_dump(mode="json"),
                }
            else:
                assert payload.record_query is not None
                semantic_view = payload.record_query.resource
                # Validate all allowlists, operators, and typed values at
                # admission time. The worker repeats this validation before
                # reading the live database.
                build_record_query(
                    db,
                    payload.record_query.resource,
                    tuple(payload.record_query.filters),
                    tuple(payload.record_query.order),
                    payload.record_query.timezone,
                )
                request_payload = {
                    "mode": "record_query",
                    "role": role,
                    "record_query": payload.record_query.model_dump(mode="json"),
                }
    except (AnalyticsValidationError, ValueError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    query_id = str(uuid.uuid4())
    job_id = str(uuid.uuid4())
    query_log = AnalyticsQueryLog(
        id=query_id,
        requested_by_id=current_user.id,
        model_version_id=version.id if version else None,
        semantic_view=semantic_view,
        request={"kind": "export", **request_payload},
        cube_query=cube_query,
        status="pending",
    )
    job = AnalyticsExportJob(
        id=job_id,
        requested_by_id=current_user.id,
        query_log_id=query_id,
        model_version_id=version.id if version else None,
        request=request_payload,
        export_format=payload.export_format,
        status="queued",
        expires_at=utc_now() + timedelta(hours=config.ANALYTICS_EXPORT_EXPIRY_HOURS),
    )
    db.add(query_log)
    db.add(job)
    _audit(
        db,
        current_user,
        "export.queued",
        "export_job",
        job_id,
        {"format": payload.export_format, "kind": request_payload["mode"]},
    )
    db.commit()
    background_tasks.add_task(execute_export_job, job_id)
    return job.to_dict()


def _export_job_for_user(
    db: Session, job_id: str, current_user: User
) -> AnalyticsExportJob:
    job = (
        db.query(AnalyticsExportJob)
        .filter(AnalyticsExportJob.id == job_id)
        .first()
    )
    if job is None or (
        current_user.role != "admin" and job.requested_by_id != current_user.id
    ):
        raise HTTPException(status_code=404, detail="Analytics export not found")
    requested_role = (job.request or {}).get("role")
    if requested_role == "admin" and current_user.role != "admin":
        # Do not expose the existence of an artifact that was produced from
        # members the now-demoted owner can no longer see.
        raise HTTPException(status_code=404, detail="Analytics export not found")
    return job


@viewer_router.get(
    "/exports/{job_id}", summary="Get analytics export status", description=_ENDPOINT_DESCRIPTIONS["viewer_export_get"]
)
async def get_analytics_export(
    job_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    return _export_job_for_user(db, job_id, current_user).to_dict()


@viewer_router.get(
    "/exports/{job_id}/download", summary="Download analytics export", description=_ENDPOINT_DESCRIPTIONS["viewer_export_download"]
)
async def download_analytics_export(
    job_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> FileResponse:
    job = _export_job_for_user(db, job_id, current_user)
    if job.expires_at <= utc_now():
        raise HTTPException(status_code=410, detail="Analytics export has expired")
    if job.status != "completed" or not job.storage_path:
        raise HTTPException(status_code=409, detail="Analytics export is not ready")
    expected_path = build_export_path(
        config.ANALYTICS_EXPORT_DIR, job.id, job.export_format
    )
    actual_path = Path(job.storage_path).resolve()
    if actual_path != expected_path or not actual_path.is_file():
        raise HTTPException(status_code=410, detail="Analytics export file is unavailable")
    job.downloaded_at = utc_now()
    _audit(
        db,
        current_user,
        "export.downloaded",
        "export_job",
        job.id,
        {"format": job.export_format, "row_count": job.row_count},
    )
    db.commit()
    return FileResponse(
        actual_path,
        media_type=job.content_type,
        filename=f"analytics-{job.id}.{job.export_format}",
        headers={"Cache-Control": "no-store, private"},
    )


router = APIRouter()
router.include_router(viewer_router)
router.include_router(admin_chart_router)
router.include_router(internal_router)
