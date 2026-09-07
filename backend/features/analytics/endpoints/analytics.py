"""Governed, feature-gated survey analytics APIs.

The router is the public trust boundary for Cube. Client requests contain only
published catalog slugs; raw Cube members and SQL are never accepted.
"""

from __future__ import annotations

from copy import deepcopy
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
from sqlalchemy import func, text as sql_text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

import core.config as config
from core.time import resolve_timezone, utc_now
from core.security import ActorContext
from features.analytics.model.semantic import (
    ASSIGNMENT_DIMENSION_FAMILIES,
    Aggregation,
    AnalyticsValidationError,
    CatalogField,
    CatalogMetric,
    FieldType,
    FilterControl,
    FilterSpec,
    MAX_AGGREGATE_ROWS,
    MAX_DIMENSIONS,
    MAX_FILTERS,
    OrderSpec,
    QueryAggregation,
    QuerySpec,
    SEMANTIC_VIEW_PREFERENCE,
    SemanticCatalog,
    Visibility,
    allowed_filter_operators,
    compile_cube_query,
    metric_result_type,
    metric_target_candidates,
    metric_targets,
    resolve_query_metric,
    resolve_semantic_view,
    validate_query_fields,
    validate_identifier,
    validate_metric,
    validate_query,
)
from features.analytics.repository.records import (
    DEFAULT_PROJECTED_RECORD_FIELDS,
    build_projected_record_statement,
    build_record_query,
    execute_projected_records,
    query_records,
)
from features.analytics.service.exports import build_export_path, execute_export_job
from features.analytics.service.results import (
    augment_cube_query_with_supports,
    format_query_result,
)
from infrastructure.integrations.analytics_metadata_auth import verify_metadata_signature
from infrastructure.integrations.cube import (
    CubeClient,
    CubePreAggregationNotReadyError,
    CubeQueryError,
    CubeQueryPendingError,
    CubeUnavailableError,
)
from infrastructure.database.dbo.AnalyticsAuditLog import AnalyticsAuditLog
from infrastructure.database.dbo.AnalyticsChart import AnalyticsChart
from infrastructure.database.dbo.AnalyticsExportJob import AnalyticsExportJob
from infrastructure.database.dbo.AnalyticsField import AnalyticsField
from infrastructure.database.dbo.AnalyticsMetric import AnalyticsMetric
from infrastructure.database.dbo.AnalyticsModelVersion import AnalyticsModelVersion
from infrastructure.database.dbo.AnalyticsQueryLog import AnalyticsQueryLog
# Register every mapped database object before AnalyticsQueryLog construction
# triggers SQLAlchemy's relationship resolution. In particular, AnalyticsField
# refers to AnalyticsFieldValue by name and the latter is not otherwise needed
# by this endpoint module.
from infrastructure.database import registry as _database_registry
from infrastructure.database.session import get_db
from features.feedback.model.sentiment import Sentiment, TopicSentiment
from features.identity.service.security import get_current_actor, require_admin


_SEMANTIC_VIEWS = {
    "survey_responses",
    "survey_topics",
    "survey_departments",
    "survey_keywords",
    "survey_assignments",
}
# One alias keeps every request schema in step when a grain is added; the set
# above stays the runtime membership check for stored records.
SemanticView = Literal[
    "survey_responses",
    "survey_topics",
    "survey_departments",
    "survey_keywords",
    "survey_assignments",
]

_PROFILE = re.compile(r"^[a-z0-9]+_(?:cls|ecls)$")
# OpenAPI descriptions deliberately mirror the public analytics contract.  The
# Markdown reference gives examples; these strings keep Swagger/ReDoc useful to
# frontend and integration clients without exposing Cube member names or SQL.
_ENDPOINT_DESCRIPTIONS = {
    "viewer_catalog": "Return the active immutable catalog visible to the current role. "
    "It includes published fields and logical metric targets plus machine-readable semantic-view, "
    "and query-limit combination rules. Draft definitions, source keys, "
    "and raw payload fields are never exposed.",
    "viewer_availability": "Report field-level non-null counts and availability rates "
    "for one semantic view. Results include only fields visible to the current role "
    "and are cached for up to 15 minutes to avoid repeated reporting scans.",
    "viewer_query_combinations": "Return a finite, curated collection of executable "
    "aggregate query templates. Every template is validated against the active, "
    "role-visible catalog and identifies the request fields that a frontend may safely override.",
    "viewer_filter_options": "Return distinct non-null values for one published "
    "dimension, with matching-row counts. Optional governed filters and string search "
    "narrow the list for a frontend filter control; use cursor to page beyond 1,000 values.",
    "viewer_query": "Run one governed aggregate query against exactly one semantic view. "
    "The API validates published member slugs, typed filters, limits, time settings, "
        "and role visibility before forwarding it to private Cube.",
    "viewer_query_capabilities": "Resolve one logical metric target and aggregation "
    "against the active catalog, then return the exact dimensions, filters, typed operators, "
    "and granular time fields that the same caller may use in an aggregate query.",
    "viewer_builder_options": "Report what remains selectable for a partial analytics "
    "builder selection, in any order. The response resolves the narrowest row grain that "
    "can answer the selection, lists the still-valid breakdowns, series, time fields and "
    "intervals, and returns the executable query once the selection is complete.",
    "viewer_builder_query": "Run a complete analytics builder selection. The server chooses "
    "the narrowest row grain that answers it and returns governed long-format rows.",
    "viewer_records_query": "Return role-authorized records from the live database. Full mode "
    "preserves nested page-based survey and master-data responses; projected mode returns "
    "cursor-paginated flat survey fields from the governed catalog. Survey filters use "
    "EXISTS predicates for assignments so each survey remains one row.",
    "viewer_charts": "List published charts visible to the current role in the active "
    "catalog. Draft, archived, invalid, and more-restricted charts are omitted. Each "
    "chart includes its immutable overview-dashboard grid placement.",
    "viewer_chart_data": "Run a published chart by ID. Its defined members stay fixed; "
    "callers may only override safe filters, time settings, ordering, and limit. "
    "The response is shaped for the declared chart type.",
    "viewer_export_create": "Queue an asynchronous CSV or XLSX export for exactly one "
    "governed aggregate or record query. Visibility is revalidated while the job "
    "runs and files expire after 24 hours.",
    "viewer_export_get": "Return export-job status for its owner or an administrator. "
    "Unauthorized callers receive not found rather than information about the job.",
    "viewer_export_download": "Download a completed, unexpired export belonging to the "
    "current user or visible to an administrator. The file response is non-cacheable.",
    "internal_catalog": "Private Cube metadata endpoint. It requires a fresh, "
    "profile-bound HMAC signature and remains available during shadow compilation "
    "even while user analytics is feature-disabled.",
    "admin_charts_list": "List all chart definitions, including drafts, archived charts, "
    "validation errors, visibility, and model-version metadata.",
    "admin_chart_get": "Return one chart definition by numeric ID.",
    "admin_chart_create": "Create a draft frontend chart contract. This defines governed "
    "members and rendering shape; it does not render a chart server-side.",
    "admin_chart_update": "Update a non-archived chart and reset it to draft so it must "
    "be validated and republished.",
    "admin_chart_publish": "Validate and publish a chart, then immediately activate "
    "the next catalog version so it is visible to chart consumers.",
    "admin_chart_archive": "Soft-delete a chart and immediately activate the next "
    "catalog version so it is no longer visible. Audit history is retained.",
    "admin_dashboard_layout_publish": "Validate and atomically publish the complete "
    "12-column overview-dashboard layout. The caller must identify the active model "
    "version it edited so concurrent chart or layout changes cannot be overwritten.",
}
_CI_OPERATIONS = {
    Aggregation.MEAN_CONFIDENCE_INTERVAL,
    Aggregation.WEIGHTED_MEAN_CONFIDENCE_INTERVAL,
    Aggregation.PROPORTION_CONFIDENCE_INTERVAL,
    Aggregation.WEIGHTED_PROPORTION_CONFIDENCE_INTERVAL,
}
_MAX_CUBE_CATALOG_BYTES = 2 * 1024 * 1024
_DASHBOARD_COLUMNS = 12
_DASHBOARD_MAX_ROWS = 10_000
_DASHBOARD_MAX_ITEM_HEIGHT = 12
_PROJECTED_RECORDS_SEMAPHORE = threading.BoundedSemaphore(
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
    "survey_assignments": "analytics_survey_assignments",
}
_ASSIGNMENT_AVAILABILITY_ALIASES = {
    "response_id": "id",
    "sentiment": "assignment_sentiment",
    "department": "department_name",
}
_FILTER_OPTION_METRIC_TARGETS = {
    "survey_responses": "survey",
    "survey_topics": "topic_assignment",
    "survey_departments": "department_assignment",
    "survey_keywords": "keyword_assignment",
    # The combination grain repeats a response once per assignment product, so
    # option counts must come from a deduplicated survey count.
    "survey_assignments": "survey",
}
_SEMANTIC_VIEW_GRAINS = {
    "survey_responses": "one non-deleted survey response",
    "survey_topics": "one survey-to-topic assignment",
    "survey_departments": "one survey-to-department assignment",
    "survey_keywords": "one survey-to-keyword assignment",
    "survey_assignments": (
        "one survey-to-(keyword, department, topic) assignment combination"
    ),
}
_ASSIGNMENT_DIMENSIONS = {
    "survey_responses": None,
    "survey_topics": "topic",
    "survey_departments": "department",
    "survey_keywords": "keyword",
    # No single assignment dimension defines this grain; see
    # _SEMANTIC_VIEW_ASSIGNMENT_DIMENSIONS for the full set.
    "survey_assignments": None,
}
_SEMANTIC_VIEW_ASSIGNMENT_DIMENSIONS: dict[str, tuple[str, ...]] = {
    "survey_responses": (),
    "survey_topics": ("topic",),
    "survey_departments": ("department",),
    "survey_keywords": ("keyword",),
    "survey_assignments": ("keyword", "department", "topic"),
}
_ASSIGNMENT_SENTIMENT_DIMENSIONS: dict[str, str | None] = {
    "survey_responses": None,
    "survey_topics": "sentiment",
    "survey_departments": "sentiment",
    "survey_keywords": "sentiment",
    # Three assignment families coexist here, so each keeps its own column.
    "survey_assignments": None,
}
# Assignment dimensions that only the combination grain can cross with each
# other, mapped to the sentiment column recorded on that assignment.
_COMBINATION_ASSIGNMENT_SENTIMENTS = {
    "keyword": "keyword_sentiment",
    "department": "department_sentiment",
    "topic": "topic_assignment_sentiment",
}

_COMMON_QUERY_OVERRIDES = ("filters", "timezone", "order", "limit")
_TIME_QUERY_OVERRIDES = (
    "filters",
    "time_range",
    "timezone",
    "order",
    "limit",
)

_QUERY_COMBINATION_DEFINITIONS: tuple[dict[str, Any], ...] = (
    {
        "slug": "responses_total",
        "label": "Total responses",
        "description": "Count non-deleted survey responses.",
        "query": {
            "semantic_view": "survey_responses",
            "metric": "survey",
            "aggregation": "count",
            "limit": 100,
        },
        "allowed_overrides": _COMMON_QUERY_OVERRIDES,
    },
    {
        "slug": "responses_by_sentiment",
        "label": "Responses by sentiment",
        "description": "Count responses by the response-level topic sentiment.",
        "query": {
            "semantic_view": "survey_responses",
            "dimensions": ["topic_sentiment"],
            "metric": "survey",
            "aggregation": "count",
            "limit": 100,
        },
        "allowed_overrides": _COMMON_QUERY_OVERRIDES,
    },
    {
        "slug": "responses_by_store_format",
        "label": "Responses by store format",
        "description": "Count responses by store format.",
        "query": {
            "semantic_view": "survey_responses",
            "dimensions": ["store_format"],
            "metric": "survey",
            "aggregation": "count",
            "limit": 100,
        },
        "allowed_overrides": _COMMON_QUERY_OVERRIDES,
    },
    {
        "slug": "responding_stores_total",
        "label": "Total responding stores",
        "description": "Count distinct stores having at least one matching response.",
        "query": {
            "semantic_view": "survey_responses",
            "metric": "store",
            "aggregation": "count",
            "limit": 100,
        },
        "allowed_overrides": _COMMON_QUERY_OVERRIDES,
    },
    {
        "slug": "responding_stores_by_region",
        "label": "Responding stores by region",
        "description": "Count distinct responding stores by region.",
        "query": {
            "semantic_view": "survey_responses",
            "dimensions": ["region"],
            "metric": "store",
            "aggregation": "count",
            "limit": 100,
        },
        "allowed_overrides": _COMMON_QUERY_OVERRIDES,
    },
    {
        "slug": "responding_stores_by_store_format",
        "label": "Responding stores by store format",
        "description": "Count distinct responding stores by store format.",
        "query": {
            "semantic_view": "survey_responses",
            "dimensions": ["store_format"],
            "metric": "store",
            "aggregation": "count",
            "limit": 100,
        },
        "allowed_overrides": _COMMON_QUERY_OVERRIDES,
    },
    {
        "slug": "responses_by_channel",
        "label": "Responses by channel",
        "description": "Count responses by channel.",
        "query": {
            "semantic_view": "survey_responses",
            "dimensions": ["channel_name"],
            "metric": "survey",
            "aggregation": "count",
            "limit": 100,
        },
        "allowed_overrides": _COMMON_QUERY_OVERRIDES,
    },
    {
        "slug": "responses_by_day",
        "label": "Daily response trend",
        "description": "Count responses in daily reported-at buckets.",
        "query": {
            "semantic_view": "survey_responses",
            "dimensions": [],
            "metric": "survey",
            "aggregation": "count",
            "time_dimension": "reported_at",
            "time_granularity": "day",
            "limit": 100,
        },
        "allowed_overrides": _TIME_QUERY_OVERRIDES,
    },
    {
        "slug": "responses_by_sentiment_by_day",
        "label": "Daily response sentiment trend",
        "description": "Count responses by response sentiment and reported-at day.",
        "query": {
            "semantic_view": "survey_responses",
            "dimensions": ["topic_sentiment"],
            "metric": "survey",
            "aggregation": "count",
            "time_dimension": "reported_at",
            "time_granularity": "day",
            "limit": 100,
        },
        "allowed_overrides": _TIME_QUERY_OVERRIDES,
    },
    {
        "slug": "average_cls_by_store_format",
        "label": "Average CLS by store format",
        "description": "Compare response-level average CLS across store formats.",
        "query": {
            "semantic_view": "survey_responses",
            "dimensions": ["store_format"],
            "metric": "cls",
            "aggregation": "average",
            "limit": 100,
        },
        "allowed_overrides": _COMMON_QUERY_OVERRIDES,
    },
    *tuple(
        combination
        for semantic_view, singular, dimension in (
            ("survey_topics", "topic", "topic"),
            ("survey_departments", "department", "department"),
            ("survey_keywords", "keyword", "keyword"),
        )
        for combination in (
            {
                "slug": f"{singular}_assignments_by_{singular}",
                "label": f"{singular.title()} assignments by {singular}",
                "description": f"Count {singular} assignment rows by {singular}.",
                "query": {
                    "semantic_view": semantic_view,
                    "dimensions": [dimension],
                    "metric": f"{singular}_assignment",
                    "aggregation": "count",
                    "limit": 100,
                },
                "allowed_overrides": _COMMON_QUERY_OVERRIDES,
            },
            {
                "slug": f"{singular}_assignments_by_sentiment",
                "label": f"{singular.title()} assignments by sentiment",
                "description": f"Count {singular} assignments by assignment sentiment.",
                "query": {
                    "semantic_view": semantic_view,
                    "dimensions": ["sentiment"],
                    "metric": f"{singular}_assignment",
                    "aggregation": "count",
                    "limit": 100,
                },
                "allowed_overrides": _COMMON_QUERY_OVERRIDES,
            },
            {
                "slug": f"distinct_surveys_by_{singular}",
                "label": f"Distinct surveys by {singular}",
                "description": (
                    f"Count surveys having at least one matching {singular} assignment."
                ),
                "query": {
                    "semantic_view": semantic_view,
                    "dimensions": [dimension],
                    "metric": "survey",
                    "aggregation": "count",
                    "limit": 100,
                },
                "allowed_overrides": _COMMON_QUERY_OVERRIDES,
            },
            {
                "slug": f"{singular}_assignments_by_day",
                "label": f"Daily {singular} assignment trend",
                "description": f"Count {singular} assignments by reported-at day.",
                "query": {
                    "semantic_view": semantic_view,
                    "dimensions": [],
                    "metric": f"{singular}_assignment",
                    "aggregation": "count",
                    "time_dimension": "reported_at",
                    "time_granularity": "day",
                    "limit": 100,
                },
                "allowed_overrides": _TIME_QUERY_OVERRIDES,
            },
        )
    ),
)


_ASSIGNMENT_SCOPE_FIELDS = {
    "assignment_id",
    "sentiment",
    "topic_id",
    "topic",
    "department_id",
    "department",
    "keyword_id",
    "keyword",
    "combination_id",
    "keyword_sentiment",
    "department_sentiment",
    "topic_assignment_sentiment",
}
_SEARCH_FILTER_FIELDS = {"keyword"}
_INPUT_FILTER_FIELDS = {
    "id",
    "survey_id",
    "respondent_id",
    "comment",
    "latitude",
    "longitude",
    "assignment_id",
    "response_id",
    "combination_id",
    "topic_id",
    "department_id",
    "keyword_id",
}


def _core_filter_control(slug: str) -> tuple[FilterControl, int]:
    """Return the safe option-discovery policy for a core dimension."""

    if slug in _SEARCH_FILTER_FIELDS:
        return "search", 2
    if slug in _INPUT_FILTER_FIELDS:
        return "input", 0
    return "select", 0


def _core_field(
    slug: str, data_type: FieldType, semantic_view: str = "survey_responses"
) -> CatalogField:
    filter_control, minimum_search_length = _core_filter_control(slug)
    return CatalogField(
        slug=slug,
        label=slug.replace("_", " ").title(),
        semantic_view=semantic_view,
        data_type=data_type,
        scope=(
            "assignment"
            if semantic_view != "survey_responses" and slug in _ASSIGNMENT_SCOPE_FIELDS
            else "response"
        ),
        filterable=True,
        filter_control=filter_control,
        minimum_search_length=minimum_search_length,
        time_dimension=data_type in {FieldType.DATE, FieldType.TIME},
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
        CatalogField(
            slug="sentiment_score",
            label="Assignment Sentiment Score",
            semantic_view=_view,
            data_type=FieldType.NUMBER,
            scope="assignment",
            published=False,
            filterable=False,
        ),
        CatalogField(
            slug="distinct_survey_id",
            label="Distinct Survey ID",
            semantic_view=_view,
            data_type=FieldType.NUMBER,
            visibility=Visibility.ADMIN,
            published=False,
            filterable=False,
        ),
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

# The combination grain carries all three assignment families at once, so each
# keeps a distinctly named sentiment column instead of a shared "sentiment".
_CORE_FIELDS += (
    _core_field("combination_id", FieldType.STRING, "survey_assignments"),
    _core_field("response_id", FieldType.NUMBER, "survey_assignments"),
    CatalogField(
        slug="distinct_survey_id",
        label="Distinct Survey ID",
        semantic_view="survey_assignments",
        data_type=FieldType.NUMBER,
        visibility=Visibility.ADMIN,
        published=False,
        filterable=False,
    ),
)
_CORE_FIELDS += tuple(
    _core_field(slug, data_type, "survey_assignments")
    for slug, data_type in _RESPONSE_FIELD_TYPES.items()
    if slug != "id"
)
_CORE_FIELDS += tuple(
    _core_field(slug, data_type, "survey_assignments")
    for slug, data_type in {
        "keyword_id": FieldType.NUMBER,
        "keyword": FieldType.STRING,
        "keyword_sentiment": FieldType.STRING,
        "department_id": FieldType.NUMBER,
        "department": FieldType.STRING,
        "department_sentiment": FieldType.STRING,
        "topic_id": FieldType.NUMBER,
        "topic": FieldType.STRING,
        "topic_assignment_sentiment": FieldType.STRING,
    }.items()
)


# Enum-valued dimensions the builder may expand into one measurable target per
# value, so a user can measure "topic sentiment is MIXED" directly instead of
# spending a group-by slot on the sentiment breakdown. Only declared enums are
# expanded; an arbitrary string dimension has no closed value set.
_ENUM_DIMENSION_VALUES: dict[str, tuple[str, ...]] = {
    "topic_sentiment": tuple(member.value for member in TopicSentiment),
    "sentiment": tuple(member.value for member in Sentiment),
    "keyword_sentiment": tuple(member.value for member in Sentiment),
    "department_sentiment": tuple(member.value for member in Sentiment),
    "topic_assignment_sentiment": tuple(member.value for member in Sentiment),
}


def enum_dimension_values(slug: str) -> tuple[str, ...]:
    """Return the closed value set of a declared enum dimension."""

    return _ENUM_DIMENSION_VALUES.get(slug, ())


def enum_metric_target(field_slug: str, value: str) -> str:
    """Return the logical metric target naming one enum value of a dimension."""

    return validate_identifier(f"{field_slug}_{value.lower()}")


def _core_metric(
    slug: str,
    aggregation: Aggregation,
    source_field: str | None = None,
    semantic_view: str = "survey_responses",
    parameters: dict[str, Any] | None = None,
    *,
    query_target: str | None = None,
    public_aggregation: QueryAggregation | None = None,
    entity: str | None = None,
    label: str | None = None,
) -> CatalogMetric:
    return CatalogMetric(
        slug=slug,
        label=label or slug.replace("_", " ").title(),
        semantic_view=semantic_view,
        aggregation=aggregation,
        source_field=source_field,
        query_target=query_target,
        public_aggregation=public_aggregation,
        entity=entity,
        parameters=parameters or {},
    )


_CORE_METRICS: tuple[CatalogMetric, ...] = (
    _core_metric(
        "survey_count",
        Aggregation.COUNT,
        "id",
        query_target="survey",
        public_aggregation=QueryAggregation.COUNT,
        entity="survey",
        label="Survey Count",
    ),
    _core_metric(
        "responding_store_count",
        Aggregation.DISTINCT_COUNT,
        "store_key",
        query_target="store",
        public_aggregation=QueryAggregation.COUNT,
        entity="store",
        label="Responding Store Count",
    ),
    _core_metric(
        "cls_sum",
        Aggregation.SUM,
        "cls",
        query_target="cls",
        public_aggregation=QueryAggregation.SUM,
        entity="cls",
        label="CLS Sum",
    ),
    _core_metric(
        "cls_average",
        Aggregation.AVERAGE,
        "cls",
        query_target="cls",
        public_aggregation=QueryAggregation.AVERAGE,
        entity="cls",
        label="Average CLS",
    ),
    _core_metric(
        "topic_sentiment_score_sum",
        Aggregation.SUM,
        "topic_sentiment_score",
        query_target="topic_sentiment_score",
        public_aggregation=QueryAggregation.SUM,
        entity="topic_sentiment_score",
        label="Topic Sentiment Score Sum",
    ),
    _core_metric(
        "topic_sentiment_score_average",
        Aggregation.AVERAGE,
        "topic_sentiment_score",
        query_target="topic_sentiment_score",
        public_aggregation=QueryAggregation.AVERAGE,
        entity="topic_sentiment_score",
        label="Average Topic Sentiment Score",
    ),
    _core_metric(
        "median_topic_sentiment_score",
        Aggregation.MEDIAN,
        "topic_sentiment_score",
        query_target="topic_sentiment_score",
        public_aggregation=QueryAggregation.MEDIAN,
        entity="topic_sentiment_score",
        label="Median Topic Sentiment Score",
    ),
    _core_metric(
        "first_reported_at",
        Aggregation.MIN,
        "reported_at",
        query_target="reported_at",
        public_aggregation=QueryAggregation.MIN,
        entity="reported_at",
        label="First Reported At",
    ),
    _core_metric(
        "last_reported_at",
        Aggregation.MAX,
        "reported_at",
        query_target="reported_at",
        public_aggregation=QueryAggregation.MAX,
        entity="reported_at",
        label="Last Reported At",
    ),
    _core_metric(
        "last_updated_at",
        Aggregation.MAX,
        "updated_at",
        query_target="updated_at",
        public_aggregation=QueryAggregation.MAX,
        entity="updated_at",
        label="Last Updated At",
    ),
    # These are standard dashboard measures, not BU-specific local definitions.
    # Keep them core so existing sentiment-breakdown cards work immediately on a
    # new profile without an administrator first publishing four duplicate
    # filtered-count definitions.  Each also publishes an enum-value metric
    # target so the builder can measure one sentiment without spending a
    # group-by slot on the sentiment dimension.
    *(
        _core_metric(
            f"topic_sentiment_{sentiment.lower()}_count",
            Aggregation.FILTERED_COUNT,
            "topic_sentiment",
            parameters={
                "filter": {"operator": "equals", "value": sentiment}
            },
            query_target=enum_metric_target("topic_sentiment", sentiment),
            public_aggregation=QueryAggregation.COUNT,
            entity="survey",
            label=f"{sentiment.title()} Topic Sentiment Responses",
        )
        for sentiment in enum_dimension_values("topic_sentiment")
    ),
)
_ASSIGNMENT_SENTIMENT_TARGETS = {
    "survey_topics": "topic_assignment_sentiment",
    "survey_departments": "department_sentiment",
    "survey_keywords": "keyword_sentiment",
}

for _view, _sentiment_target in _ASSIGNMENT_SENTIMENT_TARGETS.items():
    _prefix = _view.removeprefix("survey_").removesuffix("s")
    _CORE_METRICS += (
        _core_metric(
            "assignment_count",
            Aggregation.COUNT,
            "assignment_id",
            semantic_view=_view,
            query_target=f"{_prefix}_assignment",
            public_aggregation=QueryAggregation.COUNT,
            entity=f"{_prefix}_assignment",
            label=f"{_prefix.title()} Assignment Count",
        ),
        _core_metric(
            "survey_count",
            Aggregation.DISTINCT_COUNT,
            "distinct_survey_id",
            semantic_view=_view,
            query_target="survey",
            public_aggregation=QueryAggregation.COUNT,
            entity="survey",
            label="Unique Survey Count",
        ),
        _core_metric(
            f"{_sentiment_target}_average",
            Aggregation.AVERAGE,
            "sentiment_score",
            semantic_view=_view,
            query_target=_sentiment_target,
            public_aggregation=QueryAggregation.AVERAGE,
            entity=f"{_prefix}_assignment",
            label=f"Average {_prefix.title()} Assignment Sentiment",
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
                query_target=enum_metric_target("sentiment", sentiment),
                public_aggregation=QueryAggregation.COUNT,
                entity=f"{_prefix}_assignment",
                label=f"{sentiment.title()} {_prefix.title()} Assignments",
            )
            for sentiment in enum_dimension_values("sentiment")
        ),
        *(
            _core_metric(
                f"topic_sentiment_{sentiment.lower()}_survey_count",
                Aggregation.FILTERED_DISTINCT_COUNT,
                "topic_sentiment",
                semantic_view=_view,
                parameters={
                    "filter": {"operator": "equals", "value": sentiment},
                    "distinctField": "response_id",
                },
                query_target=enum_metric_target("topic_sentiment", sentiment),
                public_aggregation=QueryAggregation.COUNT,
                entity="survey",
                label=f"{sentiment.title()} Topic Sentiment Surveys",
            )
            for sentiment in enum_dimension_values("topic_sentiment")
        ),
    )

# The combination grain fans a response out once per assignment product, so every
# measure here deduplicates on the response key. Response-level sums and averages
# such as CLS are deliberately absent: they would be weighted by that product.
_CORE_METRICS += (
    _core_metric(
        "survey_count",
        Aggregation.DISTINCT_COUNT,
        "distinct_survey_id",
        semantic_view="survey_assignments",
        query_target="survey",
        public_aggregation=QueryAggregation.COUNT,
        entity="survey",
        label="Unique Survey Count",
    ),
    _core_metric(
        "responding_store_count",
        Aggregation.DISTINCT_COUNT,
        "store_key",
        semantic_view="survey_assignments",
        query_target="store",
        public_aggregation=QueryAggregation.COUNT,
        entity="store",
        label="Responding Store Count",
    ),
)
for _enum_field in (
    "topic_sentiment",
    "keyword_sentiment",
    "department_sentiment",
    "topic_assignment_sentiment",
):
    _CORE_METRICS += tuple(
        _core_metric(
            f"{_enum_field}_{_value.lower()}_survey_count",
            Aggregation.FILTERED_DISTINCT_COUNT,
            _enum_field,
            semantic_view="survey_assignments",
            parameters={
                "filter": {"operator": "equals", "value": _value},
                "distinctField": "distinct_survey_id",
            },
            query_target=enum_metric_target(_enum_field, _value),
            public_aggregation=QueryAggregation.COUNT,
            entity="survey",
            label=(
                f"{_value.title()} "
                f"{_enum_field.replace('_', ' ').title()} Surveys"
            ),
        )
        for _value in enum_dimension_values(_enum_field)
    )


class _StrictInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _StrictOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CatalogFieldOutput(_StrictOutput):
    slug: str
    label: str
    semantic_view: str
    data_type: FieldType
    visibility: Visibility
    scope: Literal["response", "assignment"]
    filterable: bool
    filter_control: FilterControl
    minimum_search_length: int
    time_dimension: bool


class MetricAggregationOutput(_StrictOutput):
    method: QueryAggregation
    label: str
    result_type: FieldType


class MetricTargetOutput(_StrictOutput):
    metric: str
    label: str
    entity: str
    aggregations: tuple[MetricAggregationOutput, ...]


class QueryCombinationRulesOutput(_StrictOutput):
    max_dimensions: int
    exact_metric_count: Literal[1]
    max_filters: int
    requires_single_semantic_view: bool
    members_must_belong_to_semantic_view: bool
    order_members_must_be_selected: bool
    time_dimension_must_not_be_dimension: bool


class SemanticViewCombinationOutput(_StrictOutput):
    semantic_view: str
    grain: str
    dimensions: tuple[str, ...]
    assignment_dimension: str | None
    response_sentiment_dimension: str
    assignment_sentiment_dimension: str | None
    # The combination grain carries several assignment families at once, so it
    # reports the whole set and leaves the single-family fields null.
    assignment_dimensions: tuple[str, ...] = ()
    assignment_sentiment_dimensions: dict[str, str] = Field(default_factory=dict)


class CatalogCombinationsOutput(_StrictOutput):
    query: QueryCombinationRulesOutput
    semantic_views: tuple[SemanticViewCombinationOutput, ...]


class AnalyticsCatalogResponse(_StrictOutput):
    model_version: int
    semantic_views: tuple[str, ...]
    fields: tuple[CatalogFieldOutput, ...]
    metric_targets: dict[str, tuple[MetricTargetOutput, ...]]
    combinations: CatalogCombinationsOutput


class QueryCombinationOutput(_StrictOutput):
    slug: str
    label: str
    description: str
    semantic_view: str
    grain: str
    query: QuerySpec
    allowed_overrides: tuple[
        Literal["filters", "time_range", "timezone", "order", "limit"], ...
    ]


class QueryCombinationsResponse(_StrictOutput):
    model_version: int
    count: int
    combinations: tuple[QueryCombinationOutput, ...]


class QueryCapabilitiesInput(_StrictInput):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "semantic_view": "survey_keywords",
                    "metric": "survey",
                    "aggregation": "count",
                }
            ]
        },
    )

    semantic_view: SemanticView
    metric: str
    aggregation: QueryAggregation

    @field_validator("metric")
    @classmethod
    def _metric(cls, value: str) -> str:
        return validate_identifier(value)


class SelectedMetricTargetOutput(_StrictOutput):
    metric: str
    label: str
    entity: str
    aggregation: QueryAggregation
    aggregation_label: str
    result_type: FieldType


class FilterMemberCapabilityOutput(_StrictOutput):
    field: str
    label: str
    type: FieldType
    scope: Literal["response", "assignment"]
    filter_control: FilterControl
    minimum_search_length: int
    operators: tuple[str, ...]


class QueryCapabilitiesResponse(_StrictOutput):
    model_version: int
    semantic_view: str
    metric: SelectedMetricTargetOutput
    allowed_dimensions: tuple[CatalogFieldOutput, ...]
    filter_members: tuple[FilterMemberCapabilityOutput, ...]
    allowed_time_dimensions: tuple[CatalogFieldOutput, ...]
    result_type: FieldType
    warnings: tuple[str, ...]


# --- Chart builder -------------------------------------------------------
#
# The builder is a column-first facade over the goal-first query contract. A
# caller picks what to measure, how to break it down, how to aggregate, and how
# to draw it, in any order; the server resolves which semantic view can answer
# that combination and reports what remains selectable.


class BuilderMeasureInput(_StrictInput):
    """What to measure. An enum dimension is measurable one value at a time."""

    field: str
    enum_value: str | None = Field(
        default=None,
        max_length=64,
        description=(
            "Required for an enum dimension and rejected otherwise. Selecting "
            "one value measures just that value instead of spending a group-by "
            "slot on the whole breakdown."
        ),
    )

    @field_validator("field")
    @classmethod
    def _field_identifier(cls, value: str) -> str:
        return validate_identifier(value)


class BuilderTimeSeriesInput(_StrictInput):
    field: str
    interval: Literal["day", "week", "month", "quarter", "year"]

    @field_validator("field")
    @classmethod
    def _field_identifier(cls, value: str) -> str:
        return validate_identifier(value)


class BuilderSeriesInput(_StrictInput):
    """The second breakdown: either another column or a time interval."""

    dimension: str | None = None
    time: BuilderTimeSeriesInput | None = None

    @field_validator("dimension")
    @classmethod
    def _dimension_identifier(cls, value: str | None) -> str | None:
        return validate_identifier(value) if value is not None else None

    @model_validator(mode="after")
    def _exactly_one(self) -> "BuilderSeriesInput":
        if (self.dimension is None) == (self.time is None):
            raise ValueError("A series is either one dimension or one time interval")
        return self


class BuilderSelectionInput(_StrictInput):
    measure: BuilderMeasureInput | None = None
    aggregation: QueryAggregation | None = None
    breakdown: str | None = Field(
        default=None,
        description="Primary group-by dimension; the 'for every X' of a request.",
    )
    series: BuilderSeriesInput | None = None
    filters: tuple[FilterSpec, ...] = Field(default=(), max_length=MAX_FILTERS)
    time_range: tuple[str, str] | None = None
    timezone: str | None = None

    @field_validator("breakdown")
    @classmethod
    def _breakdown_identifier(cls, value: str | None) -> str | None:
        return validate_identifier(value) if value is not None else None


class BuilderQueryInput(BuilderSelectionInput):
    order: tuple[OrderSpec, ...] = Field(default=(), max_length=8)
    limit: int = Field(default=MAX_AGGREGATE_ROWS, ge=1, le=MAX_AGGREGATE_ROWS)

    @model_validator(mode="after")
    def _requires_a_measure(self) -> "BuilderQueryInput":
        if self.measure is None or self.aggregation is None:
            raise ValueError("A builder query requires a measure and an aggregation")
        return self


class BuilderAggregationOutput(_StrictOutput):
    method: QueryAggregation
    label: str
    result_type: FieldType


class BuilderMeasureOutput(_StrictOutput):
    key: str
    label: str
    field: str
    enum_value: str | None
    semantic_views: tuple[str, ...]
    aggregations: tuple[BuilderAggregationOutput, ...]
    result_type: FieldType
    # A response-level average is distorted by the assignment fan-out of the
    # combination grain, so such a measure cannot cross assignment families.
    supports_cross_assignment: bool


class BuilderDimensionOutput(_StrictOutput):
    slug: str
    label: str
    data_type: FieldType
    scope: Literal["response", "assignment"]
    enum_values: tuple[str, ...]


class BuilderOptionsResponse(_StrictOutput):
    model_version: int
    semantic_view: str | None
    grain: str | None
    selection_complete: bool
    available_measures: tuple[BuilderMeasureOutput, ...]
    available_aggregations: tuple[BuilderAggregationOutput, ...]
    available_breakdowns: tuple[BuilderDimensionOutput, ...]
    available_series_dimensions: tuple[BuilderDimensionOutput, ...]
    available_time_fields: tuple[BuilderDimensionOutput, ...]
    available_intervals: tuple[str, ...]
    query: QuerySpec | None
    warnings: tuple[str, ...]


class ChartDefinitionInput(_StrictInput):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "dimensions": ["store_format"],
                    "metric": "survey",
                    "aggregation": "count",
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
                    "limit": 100,
                }
            ]
        },
    )

    dimensions: tuple[str, ...] = Field(default=(), max_length=MAX_DIMENSIONS)
    metric: str
    aggregation: QueryAggregation
    filters: tuple[FilterSpec, ...] = Field(default=(), max_length=20)
    time_dimension: str | None = None
    time_range: tuple[str, str] | None = None
    timezone: str | None = None
    time_granularity: Literal[
        "second", "minute", "hour", "day", "week", "month", "quarter", "year"
    ] | None = None
    order: tuple[OrderSpec, ...] = Field(default=(), max_length=8)
    limit: int = Field(default=1_000, ge=1, le=5_000)

    @field_validator("dimensions")
    @classmethod
    def _members(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        for value in values:
            validate_identifier(value)
        if len(values) != len(set(values)):
            raise ValueError("Chart members must not be duplicated")
        return values

    @field_validator("metric")
    @classmethod
    def _metric(cls, value: str) -> str:
        return validate_identifier(value)

    @field_validator("aggregation")
    @classmethod
    def _aggregation(cls, value: QueryAggregation) -> QueryAggregation:
        return value

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
        if "value" in self.dimensions or self.time_dimension == "value":
            raise ValueError("value is the reserved output key for the selected metric")
        if (self.time_range or self.time_granularity) and not self.time_dimension:
            raise ValueError("time range and granularity require a time dimension")
        if self.time_dimension in self.dimensions:
            raise ValueError("time dimension must not also be an ordinary dimension")
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
                        "metric": "survey",
                        "aggregation": "count",
                        "order": [{"member": "value", "direction": "desc"}],
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
        "grouped_bar",
        "line",
        "area",
        "pie",
        "donut",
        "polar_area",
        "radar",
        "heatmap",
    ]
    semantic_view: SemanticView = Field(
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


class DashboardLayoutItemInput(_StrictInput):
    chart_id: int = Field(gt=0)
    x: int = Field(ge=0, lt=_DASHBOARD_COLUMNS)
    y: int = Field(ge=0, le=_DASHBOARD_MAX_ROWS)
    w: int = Field(ge=1, le=_DASHBOARD_COLUMNS)
    h: int = Field(ge=1, le=_DASHBOARD_MAX_ITEM_HEIGHT)


class DashboardLayoutPublicationInput(_StrictInput):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "dashboard": "overview",
                    "expected_model_version": 24,
                    "items": [
                        {"chart_id": 41, "x": 0, "y": 0, "w": 3, "h": 2},
                        {"chart_id": 42, "x": 0, "y": 2, "w": 12, "h": 5},
                    ],
                }
            ]
        },
    )

    dashboard: Literal["overview"] = "overview"
    expected_model_version: int = Field(gt=0)
    items: tuple[DashboardLayoutItemInput, ...] = Field(max_length=500)


class DashboardLayoutItemOutput(_StrictOutput):
    chart_id: int
    x: int
    y: int
    w: int
    h: int


class DashboardLayoutPublicationOutput(_StrictOutput):
    dashboard: Literal["overview"]
    columns: Literal[12]
    items: tuple[DashboardLayoutItemOutput, ...]
    changed: bool
    model_version: int


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

    semantic_view: SemanticView
    member: str
    # Reserve room for the endpoint's non-null filter and optional search.
    filters: tuple[FilterSpec, ...] = Field(default=(), max_length=18)
    search: str | None = Field(default=None, max_length=100)
    timezone: str | None = None
    limit: int = Field(default=100, ge=1, le=1_000)
    cursor: int | None = Field(default=None, ge=0, le=1_000_000)

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
                    "representation": "projected",
                    "fields": ["survey_id", "reported_at", "comment"],
                    "filters": [
                        {
                            "member": "topic_sentiment",
                            "operator": "equals",
                            "value": "NEGATIVE",
                        }
                    ],
                    "cursor": 100,
                    "size": 250,
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
    representation: Literal["full", "projected"] = "full"
    fields: tuple[str, ...] | None = Field(default=None, max_length=50)
    filters: tuple[RecordFilterInput, ...] = Field(default=(), max_length=20)
    order: tuple[RecordOrderInput, ...] = Field(default=(), max_length=3)
    page: int = Field(default=1, ge=1)
    size: int = Field(default=100, ge=1, le=1_000)
    cursor: int | None = Field(default=None, ge=0)
    timezone: str | None = None

    @field_validator("fields")
    @classmethod
    def _safe_unique_fields(
        cls, values: tuple[str, ...] | None
    ) -> tuple[str, ...] | None:
        if values is None:
            return None
        if not values:
            raise ValueError("Projected records require at least one field")
        for value in values:
            validate_identifier(value)
        if len(set(values)) != len(values):
            raise ValueError("Projected record fields must be unique")
        return values

    @field_validator("timezone")
    @classmethod
    def _timezone(cls, value: str | None) -> str | None:
        if value is not None:
            resolve_timezone(value)
        return value

    @model_validator(mode="after")
    def _representation_contract(self) -> "RecordQueryInput":
        members = [item.member for item in self.order]
        if len(members) != len(set(members)):
            raise ValueError("Record order fields must not be duplicated")
        if self.representation == "full":
            if self.fields is not None or self.cursor is not None:
                raise ValueError("Full record queries do not accept fields or cursor")
            if self.resource == "surveys" and self.size > 100:
                raise ValueError("Full survey record pages are capped at 100 rows")
            return self
        if self.resource != "surveys":
            raise ValueError("Projected records only support the surveys resource")
        if self.page != 1:
            raise ValueError("Projected record queries do not accept page greater than 1")
        if self.order:
            raise ValueError("Projected record queries use fixed id ascending order")
        if self.size > 250:
            raise ValueError("Projected survey record pages are capped at 250 rows")
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
                        "metric": "survey",
                        "aggregation": "count",
                    },
                },
                {
                    "export_format": "csv",
                    "record_query": {
                        "resource": "surveys",
                        "representation": "projected",
                        "fields": ["survey_id", "comment"],
                        "filters": [],
                        "size": 250,
                    },
                },
            ]
        },
    )

    export_format: Literal["csv", "xlsx"]
    query: QuerySpec | None = None
    record_query: RecordQueryInput | None = None

    @model_validator(mode="after")
    def _one_request_kind(self) -> "ExportInput":
        request_kinds = sum(
            value is not None
            for value in (self.query, self.record_query)
        )
        if request_kinds != 1:
            raise ValueError("Export requires exactly one query or record_query")
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


def _role(user: ActorContext) -> str:
    return "admin" if user.role == "admin" else "viewer"


def _actor_snapshot(actor: Any, prefix: str) -> dict[str, str | None]:
    subject = getattr(actor, "subject", getattr(actor, "id", None))
    label = getattr(actor, "label", getattr(actor, "username", subject))
    return {
        f"{prefix}_subject": subject,
        f"{prefix}_label": label,
        f"{prefix}_role": _role(actor) if actor is not None else None,
    }


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


def _catalog_from_version(
    version: AnalyticsModelVersion | None, role: str
) -> SemanticCatalog:
    """Build the core-plus-local catalog from one immutable model version."""
    if role not in {"viewer", "admin"}:
        raise AnalyticsValidationError("Unknown analytics role")
    payload = _extract_cube_catalog(version)
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
                scope=item.get("scope", "response"),
                filterable=item.get("filterable", True),
                filter_control=item.get("filterControl", "input"),
                minimum_search_length=item.get("minimumSearchLength", 0),
                time_dimension=item.get(
                    "timeDimension", item["dataType"] in {"date", "time"}
                ),
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
                query_target=item.get("queryTarget"),
                public_aggregation=item.get("publicAggregation"),
                entity=item.get("entity"),
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


def _catalog(db: Session, role: str) -> SemanticCatalog:
    """Return the active core-plus-local catalog visible to the given role."""

    return _catalog_from_version(_active_model_version(db), role)


def _raw_field_sources_from_version(
    version: AnalyticsModelVersion | None, role: str
) -> dict[str, tuple[str, FieldType]]:
    if role not in {"viewer", "admin"}:
        raise AnalyticsValidationError("Unknown analytics role")
    payload = _extract_cube_catalog(version)
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
    model_version: AnalyticsModelVersion | None = None,
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
            and field.published
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

    raw_fields = _raw_field_sources_from_version(model_version, role)
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
    actor: ActorContext | None,
    action: str,
    resource_type: str,
    resource_id: str | int,
    payload: dict[str, Any] | None = None,
) -> None:
    db.add(
        AnalyticsAuditLog(
            **_actor_snapshot(actor, "actor"),
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


def _query_schema(
    query: QuerySpec, catalog: SemanticCatalog, role: str
) -> dict[str, Any]:
    dimensions = [
        {
            "field": slug,
            "label": catalog.field(slug, query.semantic_view).label,
            "type": catalog.field(slug, query.semantic_view).data_type.value,
            "key": slug,
            # Preserve the semantic axis order for renderers without adding
            # renderer-specific layout to the query contract. A third
            # dimension remains explicit so table-only result shapes do not
            # need to infer or discard it.
            "group_role": (
                "primary"
                if index == 0
                else "secondary"
                if index == 1
                else "additional"
            ),
        }
        for index, slug in enumerate(query.dimensions)
    ]
    time_dimension = None
    if query.time_dimension:
        field = catalog.field(query.time_dimension, query.semantic_view)
        time_dimension = {
            "field": query.time_dimension,
            "label": field.label,
            "type": field.data_type.value,
            "granularity": query.time_granularity,
            "key": query.time_dimension,
        }
    governed_metric = resolve_query_metric(query, catalog, role)
    result_type = metric_result_type(governed_metric, catalog).value
    return {
        "dimensions": dimensions,
        "time_dimension": time_dimension,
        "metric": {
            "target": query.metric,
            "aggregation": query.aggregation.value,
            "label": governed_metric.label,
            "type": result_type,
            "key": "value",
        },
    }


def _column_metadata(schema: dict[str, Any]) -> list[dict[str, str]]:
    columns = [
        {"name": item["key"], "type": item["type"]}
        for item in schema["dimensions"]
    ]
    if schema["time_dimension"] is not None:
        item = schema["time_dimension"]
        columns.append({"name": item["key"], "type": item["type"]})
    columns.append(
        {"name": schema["metric"]["key"], "type": schema["metric"]["type"]}
    )
    return columns


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


class _AnalyticsCatalogChangedError(RuntimeError):
    """The active immutable catalog changed while Cube was executing."""


def _version_id(version: AnalyticsModelVersion | None) -> int | None:
    return version.id if version is not None else None


async def _execute_query(
    query: QuerySpec,
    db: Session,
    current_user: ActorContext,
    *,
    cube_query_override: dict[str, Any] | None = None,
    pinned_version: AnalyticsModelVersion | None = None,
    pinned_catalog: SemanticCatalog | None = None,
    query_is_validated: bool = False,
) -> dict[str, Any]:
    """Validate, execute, log, and format a governed Cube query."""

    role = _role(current_user)
    try:
        if pinned_catalog is None:
            version = _active_model_version(db)
            catalog = _catalog_from_version(version, role)
        else:
            version = pinned_version
            catalog = pinned_catalog
            if _version_id(_active_model_version(db)) != _version_id(version):
                raise _AnalyticsCatalogChangedError
        # Most aggregate requests resolve their grain from the chosen members.
        # A filter-options request is intentionally different: its caller has
        # already validated the explicit selector view, so do not resolve it to
        # a narrower assignment grain while formatting the result.
        if not query_is_validated:
            query = validate_query(query, catalog, role)
        cube_query = cube_query_override or compile_cube_query(
            query, catalog, role, _validated=True
        )
        cube_query = augment_cube_query_with_supports(cube_query, query, catalog, role)
    except _AnalyticsCatalogChangedError as error:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "analytics_catalog_changed",
                "message": "Analytics catalog changed; retry the query",
            },
        ) from error
    except (AnalyticsValidationError, ValueError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    model_version_id = _version_id(version)
    model_version = version.catalog_version if version else 0
    query_id = str(uuid.uuid4())
    query_log = AnalyticsQueryLog(
        id=query_id,
        **_actor_snapshot(current_user, "requested_by"),
        model_version_id=model_version_id,
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
        if _version_id(_active_model_version(db)) != model_version_id:
            raise _AnalyticsCatalogChangedError
        formatted_result = format_query_result(result, query, catalog, role)
        schema = _query_schema(query, catalog, role)
        columns = _column_metadata(schema)
        rows = _format_rows(formatted_result["rows"], query, columns)
    except _AnalyticsCatalogChangedError as error:
        query_log.status = "failed"
        query_log.error_message = "Analytics catalog changed during query execution"
        query_log.completed_at = utc_now()
        query_log.duration_ms = round((time.monotonic() - started) * 1_000)
        db.commit()
        raise HTTPException(
            status_code=409,
            detail={
                "code": "analytics_catalog_changed",
                "message": "Analytics catalog changed; retry the query",
            },
        ) from error
    except CubeQueryPendingError as error:
        query_log.status = "failed"
        query_log.error_message = "Cube query exceeded the long-poll retry deadline"
        query_log.completed_at = utc_now()
        query_log.duration_ms = round((time.monotonic() - started) * 1_000)
        db.commit()
        raise HTTPException(
            status_code=503,
            detail={
                "code": "analytics_query_pending",
                "message": "The analytics query is still processing; retry shortly",
            },
            headers={"Retry-After": "2"},
        ) from error
    except CubePreAggregationNotReadyError as error:
        query_log.status = "failed"
        query_log.error_message = "Cube pre-aggregations are still preparing"
        query_log.completed_at = utc_now()
        query_log.duration_ms = round((time.monotonic() - started) * 1_000)
        db.commit()
        raise HTTPException(
            status_code=503,
            detail={
                "code": "analytics_warming",
                "message": "Analytics data is preparing; retry shortly",
            },
            headers={"Retry-After": "2"},
        ) from error
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
        "model_version": model_version,
        "semantic_view": query.semantic_view,
        "timezone": query.timezone or "UTC",
        "schema": schema,
        "rows": rows,
        "row_count": len(rows),
        "warnings": [
            *formatted_result["warnings"],
            *_warning_list(result.get("warnings") or result.get("warning")),
        ],
        "freshness_time": freshness,
    }


_BUILDER_INTERVALS = ("day", "week", "month", "quarter", "year")


def _builder_measure_key(field_slug: str, enum_value: str | None) -> str:
    return field_slug if enum_value is None else f"{field_slug}:{enum_value}"


def _builder_measure_label(field_slug: str, enum_value: str | None) -> str:
    field_label = field_slug.replace("_", " ").title()
    if enum_value is None:
        return field_label
    return f"{field_label} is {enum_value}"


def _measure_target(measure: BuilderMeasureInput) -> str:
    """Map a builder measure onto the logical metric target that answers it."""

    if measure.enum_value is None:
        return measure.field
    values = enum_dimension_values(measure.field)
    if not values:
        raise AnalyticsValidationError(
            f"Dimension {measure.field} has no enumerated values to measure"
        )
    if measure.enum_value not in values:
        raise AnalyticsValidationError(
            f"{measure.enum_value} is not a value of {measure.field}"
        )
    return enum_metric_target(measure.field, measure.enum_value)


def _cross_assignment_safe(
    catalog: SemanticCatalog,
    target: str,
    aggregation: QueryAggregation,
    role: str = "viewer",
) -> bool:
    """Report whether the combination grain can answer this goal honestly.

    Only metrics that deduplicate on the response key survive the fan-out. The
    grain publishes exactly those, so presence there is the check.
    """

    return bool(
        metric_target_candidates(
            catalog, "survey_assignments", target, aggregation, role
        )
    )


def _builder_measures(
    catalog: SemanticCatalog, role: str
) -> tuple[BuilderMeasureOutput, ...]:
    """List every measurable target across all grains, enum values expanded.

    Flattening across grains is what lets a caller start from "what do I want to
    see" rather than having to know which row grain can answer it.
    """

    by_key: dict[str, dict[str, Any]] = {}
    for semantic_view in SEMANTIC_VIEW_PREFERENCE:
        for target in metric_targets(catalog, semantic_view, role):
            field_slug, _, enum_value = _split_enum_target(target.metric)
            key = _builder_measure_key(field_slug, enum_value)
            entry = by_key.setdefault(
                key,
                {
                    "field": field_slug,
                    "enum_value": enum_value,
                    "target": target.metric,
                    "views": [],
                    "aggregations": {},
                },
            )
            entry["views"].append(semantic_view)
            for option in target.aggregations:
                entry["aggregations"].setdefault(
                    option.method,
                    BuilderAggregationOutput(
                        method=option.method,
                        label=option.label,
                        result_type=option.result_type,
                    ),
                )

    result: list[BuilderMeasureOutput] = []
    for key, entry in sorted(by_key.items()):
        aggregations = tuple(
            entry["aggregations"][method]
            for method in sorted(entry["aggregations"], key=lambda item: item.value)
        )
        if not aggregations:
            continue
        result.append(
            BuilderMeasureOutput(
                key=key,
                label=_builder_measure_label(entry["field"], entry["enum_value"]),
                field=entry["field"],
                enum_value=entry["enum_value"],
                semantic_views=tuple(entry["views"]),
                aggregations=aggregations,
                result_type=aggregations[0].result_type,
                supports_cross_assignment="survey_assignments" in entry["views"],
            )
        )
    return tuple(result)


def _split_enum_target(target: str) -> tuple[str, str | None, str | None]:
    """Recover the (field, target, enum value) behind a metric target slug."""

    for field_slug, values in _ENUM_DIMENSION_VALUES.items():
        for value in values:
            if target == enum_metric_target(field_slug, value):
                return field_slug, target, value
    return target, target, None


def _selected_members(selection: BuilderSelectionInput) -> tuple[str, ...]:
    members: list[str] = []
    if selection.breakdown is not None:
        members.append(selection.breakdown)
    if selection.series is not None and selection.series.dimension is not None:
        members.append(selection.series.dimension)
    if selection.series is not None and selection.series.time is not None:
        members.append(selection.series.time.field)
    members.extend(item.member for item in selection.filters)
    return tuple(members)


def _resolve_builder_view(
    selection: BuilderSelectionInput, catalog: SemanticCatalog, role: str
) -> tuple[str | None, list[str]]:
    """Pick the narrowest grain that holds every selected member and the goal."""

    warnings: list[str] = []
    members = _selected_members(selection)
    target = (
        _measure_target(selection.measure) if selection.measure is not None else None
    )
    # Nothing has been chosen yet, so no grain is implied and the caller should
    # still see every dimension any grain could offer.
    if target is None and not members:
        return None, warnings

    resolution = resolve_semantic_view(
        catalog,
        target=target,
        aggregation=selection.aggregation,
        members=members,
        role=role,
    )
    if resolution.semantic_view is not None:
        return resolution.semantic_view, warnings
    if target is None or selection.aggregation is None:
        return None, warnings
    if resolution.crosses_assignment_families:
        warnings.append(
            "Crossing assignment families repeats a response once per "
            "combination, so this measure cannot be reported honestly at that "
            "grain. Use a response-level breakdown or a counting measure."
        )
    elif resolution.views_with_members:
        # Some grain holds the breakdowns, but none of those grains publishes
        # this goal. Naming the grain is what makes the refusal actionable.
        assert selection.measure is not None
        label = _builder_measure_label(
            selection.measure.field, selection.measure.enum_value
        )
        warnings.append(
            f"{selection.aggregation.value} of {label} is not published at the "
            f"{resolution.views_with_members[0]} grain that {', '.join(members)} requires."
        )
    return None, warnings


def _distinct_by_slug(fields: Any) -> list[CatalogField]:
    """Collapse the same dimension repeated across grains into one entry."""

    seen: dict[str, CatalogField] = {}
    for field in fields:
        seen.setdefault(field.slug, field)
    return list(seen.values())


def _builder_dimension_output(
    field: CatalogField,
) -> BuilderDimensionOutput:
    return BuilderDimensionOutput(
        slug=field.slug,
        label=field.label,
        data_type=field.data_type,
        scope=field.scope,
        enum_values=enum_dimension_values(field.slug),
    )


def _builder_query(
    selection: BuilderQueryInput, semantic_view: str
) -> QuerySpec:
    """Compile a builder selection into the governed aggregate query."""

    assert selection.measure is not None and selection.aggregation is not None
    dimensions: list[str] = []
    if selection.breakdown is not None:
        dimensions.append(selection.breakdown)
    time_dimension: str | None = None
    time_granularity: str | None = None
    if selection.series is not None:
        if selection.series.dimension is not None:
            dimensions.append(selection.series.dimension)
        else:
            assert selection.series.time is not None
            time_dimension = selection.series.time.field
            time_granularity = selection.series.time.interval

    return QuerySpec(
        semantic_view=semantic_view,
        dimensions=tuple(dimensions),
        metric=_measure_target(selection.measure),
        aggregation=selection.aggregation,
        filters=selection.filters,
        time_dimension=time_dimension,
        time_range=selection.time_range,
        timezone=selection.timezone,
        time_granularity=time_granularity,
        order=selection.order,
        limit=selection.limit,
    )


def _breakdown_is_honest(
    selection: BuilderSelectionInput,
    catalog: SemanticCatalog,
    field: CatalogField,
    role: str,
) -> bool:
    """Reject a dimension that would force a grain the measure cannot survive.

    Adding a second assignment family moves the query to the combination grain,
    where a response repeats once per combination. A measure that only exists as
    a sum or average of response values would then be silently weighted by that
    repetition, so it is not offered.
    """

    family = ASSIGNMENT_DIMENSION_FAMILIES.get(field.slug)
    if family is None:
        return True
    if selection.measure is None or selection.aggregation is None:
        return True

    existing_families = {
        ASSIGNMENT_DIMENSION_FAMILIES[member]
        for member in _selected_members(selection)
        if member in ASSIGNMENT_DIMENSION_FAMILIES
    }
    if not existing_families or family in existing_families:
        return True
    try:
        target = _measure_target(selection.measure)
    except AnalyticsValidationError:
        return False
    return _cross_assignment_safe(catalog, target, selection.aggregation)


def _builder_options(
    selection: BuilderSelectionInput,
    catalog: SemanticCatalog,
    model_version: int,
    role: str,
) -> BuilderOptionsResponse:
    """Report what is still selectable, whatever order the caller chose in."""

    measures = _builder_measures(catalog, role)
    semantic_view, warnings = _resolve_builder_view(selection, catalog, role)

    aggregations: tuple[BuilderAggregationOutput, ...] = ()
    if selection.measure is not None:
        key = _builder_measure_key(
            selection.measure.field, selection.measure.enum_value
        )
        chosen = next((item for item in measures if item.key == key), None)
        if chosen is None:
            raise AnalyticsValidationError(
                f"{key} is not a measurable target in the active catalog"
            )
        aggregations = chosen.aggregations
        if selection.aggregation is not None and selection.aggregation not in {
            option.method for option in aggregations
        }:
            raise AnalyticsValidationError(
                f"{selection.aggregation.value} is not available for {key}"
            )

    query: QuerySpec | None = None

    # Offer dimensions from every grain. A current narrow selection can still
    # add another assignment family when the metric survives the combination
    # grain; _breakdown_is_honest filters unsafe additions below.
    scoped_views = SEMANTIC_VIEW_PREFERENCE
    selectable_dimensions = _distinct_by_slug(
        field
        for view in scoped_views
        for field in catalog.fields
        if field.semantic_view == view
            and field.published
        and (role == "admin" or field.visibility is Visibility.VIEWER)
    )
    series_dimension = (
        selection.series.dimension if selection.series is not None else None
    )
    # A dimension already used on one axis cannot also occupy the other.
    breakdowns = tuple(
        _builder_dimension_output(field)
        for field in selectable_dimensions
        if field.slug != series_dimension
        and _breakdown_is_honest(selection, catalog, field, role)
    )
    series_dimensions = tuple(
        _builder_dimension_output(field)
        for field in selectable_dimensions
        if field.slug != selection.breakdown
        and _breakdown_is_honest(selection, catalog, field, role)
    )
    time_fields = tuple(
        _builder_dimension_output(field)
        for field in _distinct_by_slug(
            field
            for view in scoped_views
            for field in catalog.fields
            if field.semantic_view == view
            and field.published
            and field.time_dimension
            and (role == "admin" or field.visibility is Visibility.VIEWER)
        )
    )

    selection_complete = (
        semantic_view is not None
        and selection.measure is not None
        and selection.aggregation is not None
    )
    if selection_complete:
        assert semantic_view is not None
        try:
            candidate = _builder_query(
                BuilderQueryInput.model_validate(
                    {
                        **selection.model_dump(mode="json"),
                        "limit": MAX_AGGREGATE_ROWS,
                    }
                ),
                semantic_view,
            )
            query = validate_query(candidate, catalog, role)
        except (AnalyticsValidationError, ValueError) as error:
            warnings.append(str(error))
            query = None

    return BuilderOptionsResponse(
        model_version=model_version,
        semantic_view=semantic_view,
        grain=_SEMANTIC_VIEW_GRAINS.get(semantic_view) if semantic_view else None,
        selection_complete=query is not None,
        available_measures=measures,
        available_aggregations=aggregations,
        available_breakdowns=breakdowns,
        available_series_dimensions=series_dimensions,
        available_time_fields=time_fields,
        available_intervals=_BUILDER_INTERVALS,
        query=query,
        warnings=tuple(warnings),
    )


def _field_is_visible(field: CatalogField, role: str) -> bool:
    return field.published and (
        role == "admin" or field.visibility is Visibility.VIEWER
    )


def _semantic_view_combination(
    catalog: SemanticCatalog, semantic_view: str, role: str
) -> SemanticViewCombinationOutput:
    dimensions = tuple(
        field.slug
        for field in catalog.fields
        if field.semantic_view == semantic_view
        and field.slug != "value"
        and _field_is_visible(field, role)
    )
    assignment_dimensions = _SEMANTIC_VIEW_ASSIGNMENT_DIMENSIONS[semantic_view]
    return SemanticViewCombinationOutput(
        semantic_view=semantic_view,
        grain=_SEMANTIC_VIEW_GRAINS[semantic_view],
        dimensions=dimensions,
        assignment_dimension=_ASSIGNMENT_DIMENSIONS[semantic_view],
        response_sentiment_dimension="topic_sentiment",
        assignment_sentiment_dimension=_ASSIGNMENT_SENTIMENT_DIMENSIONS[semantic_view],
        assignment_dimensions=assignment_dimensions,
        assignment_sentiment_dimensions=(
            dict(_COMBINATION_ASSIGNMENT_SENTIMENTS)
            if semantic_view == "survey_assignments"
            else {
                dimension: "sentiment" for dimension in assignment_dimensions
            }
        ),
    )


def _catalog_response(
    catalog: SemanticCatalog, model_version: int, role: str = "viewer"
) -> AnalyticsCatalogResponse:
    fields = tuple(
        CatalogFieldOutput(
            slug=field.slug,
            label=field.label,
            semantic_view=field.semantic_view,
            data_type=field.data_type,
            visibility=field.visibility,
            scope=field.scope,
            filterable=field.filterable,
            filter_control=field.filter_control,
            minimum_search_length=field.minimum_search_length,
            time_dimension=field.time_dimension,
        )
        for field in catalog.fields
        if _field_is_visible(field, role)
    )
    targets = {
        semantic_view: tuple(
            MetricTargetOutput(
                metric=target.metric,
                label=target.label,
                entity=target.entity,
                aggregations=tuple(
                    MetricAggregationOutput(
                        method=aggregation.method,
                        label=aggregation.label,
                        result_type=aggregation.result_type,
                    )
                    for aggregation in target.aggregations
                ),
            )
            for target in metric_targets(catalog, semantic_view, role)
        )
        for semantic_view in sorted(catalog.views)
    }
    semantic_view_combinations = tuple(
        _semantic_view_combination(catalog, semantic_view, role)
        for semantic_view in sorted(catalog.views)
    )
    return AnalyticsCatalogResponse(
        model_version=model_version,
        semantic_views=tuple(sorted(catalog.views)),
        fields=fields,
        metric_targets=targets,
        combinations=CatalogCombinationsOutput(
            query=QueryCombinationRulesOutput(
                max_dimensions=MAX_DIMENSIONS,
                exact_metric_count=1,
                max_filters=MAX_FILTERS,
                requires_single_semantic_view=True,
                members_must_belong_to_semantic_view=True,
                order_members_must_be_selected=True,
                time_dimension_must_not_be_dimension=True,
            ),
            semantic_views=semantic_view_combinations,
        ),
    )


def _query_capabilities_response(
    payload: QueryCapabilitiesInput,
    catalog: SemanticCatalog,
    model_version: int,
    role: str,
) -> QueryCapabilitiesResponse:
    targets = {
        target.metric: target
        for target in metric_targets(catalog, payload.semantic_view, role)
    }
    target = targets.get(payload.metric)
    if target is None:
        raise AnalyticsValidationError(
            f"Metric target {payload.metric}/{payload.aggregation.value} is not "
            f"published at the {payload.semantic_view} grain"
        )
    aggregation = next(
        (
            item
            for item in target.aggregations
            if item.method is payload.aggregation
        ),
        None,
    )
    if aggregation is None:
        raise AnalyticsValidationError(
            f"Metric target {payload.metric}/{payload.aggregation.value} is not "
            f"published at the {payload.semantic_view} grain"
        )
    governed_candidates = metric_target_candidates(
        catalog,
        payload.semantic_view,
        payload.metric,
        payload.aggregation,
        role,
    )
    if len(governed_candidates) != 1:
        raise AnalyticsValidationError(
            f"Metric target {payload.metric}/{payload.aggregation.value} is "
            f"ambiguous at the {payload.semantic_view} grain"
        )
    governed = validate_metric(governed_candidates[0], catalog)
    result_type = metric_result_type(governed, catalog)
    fields = tuple(
        sorted(
            (
                field
                for field in catalog.fields
                if field.semantic_view == payload.semantic_view
                and _field_is_visible(field, role)
            ),
            key=lambda field: field.slug,
        )
    )

    def output(field: CatalogField) -> CatalogFieldOutput:
        return CatalogFieldOutput(
            slug=field.slug,
            label=field.label,
            semantic_view=field.semantic_view,
            data_type=field.data_type,
            visibility=field.visibility,
            scope=field.scope,
            filterable=field.filterable,
            filter_control=field.filter_control,
            minimum_search_length=field.minimum_search_length,
            time_dimension=field.time_dimension,
        )

    return QueryCapabilitiesResponse(
        model_version=model_version,
        semantic_view=payload.semantic_view,
        metric=SelectedMetricTargetOutput(
            metric=target.metric,
            label=target.label,
            entity=target.entity,
            aggregation=payload.aggregation,
            aggregation_label=aggregation.label,
            result_type=result_type,
        ),
        allowed_dimensions=tuple(output(field) for field in fields),
        filter_members=tuple(
            FilterMemberCapabilityOutput(
                field=field.slug,
                label=field.label,
                type=field.data_type,
                scope=field.scope,
                filter_control=field.filter_control,
                minimum_search_length=field.minimum_search_length,
                operators=allowed_filter_operators(field.data_type),
            )
            for field in fields
            if field.filterable
        ),
        allowed_time_dimensions=tuple(
            output(field) for field in fields if field.time_dimension
        ),
        result_type=result_type,
        warnings=(),
    )


def _query_combinations_response(
    catalog: SemanticCatalog,
    model_version: int,
    role: str,
    semantic_view: str | None = None,
) -> QueryCombinationsResponse:
    combinations: list[QueryCombinationOutput] = []
    for definition in _QUERY_COMBINATION_DEFINITIONS:
        query = QuerySpec.model_validate(definition["query"])
        if semantic_view is not None and query.semantic_view != semantic_view:
            continue
        try:
            query = validate_query(query, catalog, role)
        except AnalyticsValidationError:
            # A catalog may hide or retire a member for this role. Never advertise
            # a combination that the same caller cannot send to POST /query.
            continue

        combinations.append(
            QueryCombinationOutput(
                slug=definition["slug"],
                label=definition["label"],
                description=definition["description"],
                semantic_view=query.semantic_view,
                grain=_SEMANTIC_VIEW_GRAINS[query.semantic_view],
                query=query,
                allowed_overrides=definition["allowed_overrides"],
            )
        )

    return QueryCombinationsResponse(
        model_version=model_version,
        count=len(combinations),
        combinations=tuple(combinations),
    )


def _dashboard_item_minimum(chart: dict[str, Any]) -> tuple[int, int]:
    chart_type = chart.get("chart_type")
    if chart_type == "kpi":
        return 3, 2
    if chart_type == "table":
        return 6, 3
    return 4, 3


def _dashboard_items_overlap(left: dict[str, int], right: dict[str, int]) -> bool:
    return not (
        left["x"] + left["w"] <= right["x"]
        or right["x"] + right["w"] <= left["x"]
        or left["y"] + left["h"] <= right["y"]
        or right["y"] + right["h"] <= left["y"]
    )


def _dashboard_item_dict(item: DashboardLayoutItemInput | dict[str, Any]) -> dict[str, int]:
    values = item.model_dump(mode="json") if isinstance(item, DashboardLayoutItemInput) else item
    return {
        "chart_id": int(values["chart_id"]),
        "x": int(values["x"]),
        "y": int(values["y"]),
        "w": int(values["w"]),
        "h": int(values["h"]),
    }


def _validate_dashboard_layout(
    charts: list[dict[str, Any]],
    items: tuple[DashboardLayoutItemInput, ...] | list[dict[str, Any]],
) -> list[dict[str, int]]:
    charts_by_id = {int(chart["id"]): chart for chart in charts}
    normalized = [_dashboard_item_dict(item) for item in items]
    item_ids = [item["chart_id"] for item in normalized]
    expected_ids = set(charts_by_id)
    actual_ids = set(item_ids)
    if len(item_ids) != len(actual_ids):
        raise AnalyticsValidationError("Dashboard layout contains duplicate chart IDs")
    if actual_ids != expected_ids:
        missing = sorted(expected_ids - actual_ids)
        unknown = sorted(actual_ids - expected_ids)
        details = []
        if missing:
            details.append(f"missing chart IDs {missing}")
        if unknown:
            details.append(f"unknown chart IDs {unknown}")
        raise AnalyticsValidationError(f"Dashboard layout must contain every published chart exactly once: {', '.join(details)}")

    for item in normalized:
        chart = charts_by_id[item["chart_id"]]
        min_width, min_height = _dashboard_item_minimum(chart)
        if item["x"] < 0 or item["y"] < 0:
            raise AnalyticsValidationError("Dashboard positions must not be negative")
        if item["w"] < min_width or item["h"] < min_height:
            raise AnalyticsValidationError(
                f"Chart {item['chart_id']} requires at least {min_width} columns by {min_height} rows"
            )
        if item["w"] > _DASHBOARD_COLUMNS or item["x"] + item["w"] > _DASHBOARD_COLUMNS:
            raise AnalyticsValidationError(f"Chart {item['chart_id']} extends beyond the 12-column dashboard")
        if item["h"] > _DASHBOARD_MAX_ITEM_HEIGHT or item["y"] > _DASHBOARD_MAX_ROWS:
            raise AnalyticsValidationError(f"Chart {item['chart_id']} exceeds dashboard layout limits")

    for index, item in enumerate(normalized):
        for other in normalized[index + 1 :]:
            if _dashboard_items_overlap(item, other):
                raise AnalyticsValidationError(
                    f"Dashboard charts {item['chart_id']} and {other['chart_id']} overlap"
                )
    return sorted(normalized, key=lambda item: (item["y"], item["x"], item["chart_id"]))


def _default_dashboard_layout(charts: list[dict[str, Any]]) -> list[dict[str, int]]:
    items: list[dict[str, int]] = []
    kpis = [chart for chart in charts if chart.get("chart_type") == "kpi"]
    visualizations = [chart for chart in charts if chart.get("chart_type") != "kpi"]
    for index, chart in enumerate(kpis):
        items.append(
            {
                "chart_id": int(chart["id"]),
                "x": (index % 4) * 3,
                "y": (index // 4) * 2,
                "w": 3,
                "h": 2,
            }
        )
    cursor_y = math.ceil(len(kpis) / 4) * 2
    primary_index = next(
        (
            index
            for index, chart in enumerate(visualizations)
            if chart.get("chart_type") in {"line", "area"}
        ),
        None,
    )
    if primary_index is not None:
        primary = visualizations.pop(primary_index)
        items.append(
            {"chart_id": int(primary["id"]), "x": 0, "y": cursor_y, "w": 12, "h": 3}
        )
        cursor_y += 3
    for index, chart in enumerate(visualizations):
        items.append(
            {
                "chart_id": int(chart["id"]),
                "x": (index % 2) * 6,
                "y": cursor_y + (index // 2) * 3,
                "w": 6,
                "h": 3,
            }
        )
    return sorted(items, key=lambda item: (item["y"], item["x"], item["chart_id"]))


def _dashboard_layout_from_snapshot(
    version: AnalyticsModelVersion | None,
    charts: list[dict[str, Any]],
) -> list[dict[str, int]]:
    if not charts:
        return []
    snapshot = version.catalog_snapshot if version is not None else {}
    stored_layout = snapshot.get("dashboard_layout", {}) if isinstance(snapshot, dict) else {}
    stored_items = stored_layout.get("items", []) if isinstance(stored_layout, dict) else []
    if not isinstance(stored_items, list) or not stored_items:
        return _default_dashboard_layout(charts)
    try:
        return _validate_dashboard_layout(charts, stored_items)
    except (AnalyticsValidationError, KeyError, TypeError, ValueError):
        pass

    charts_by_id = {int(chart["id"]): chart for chart in charts}
    retained: list[dict[str, int]] = []
    seen: set[int] = set()
    for candidate in stored_items:
        try:
            item = _dashboard_item_dict(candidate)
            chart = charts_by_id[item["chart_id"]]
            min_width, min_height = _dashboard_item_minimum(chart)
            valid = (
                item["chart_id"] not in seen
                and item["x"] >= 0
                and item["y"] >= 0
                and item["w"] >= min_width
                and item["h"] >= min_height
                and item["x"] + item["w"] <= _DASHBOARD_COLUMNS
                and item["h"] <= _DASHBOARD_MAX_ITEM_HEIGHT
                and item["y"] <= _DASHBOARD_MAX_ROWS
                and not any(_dashboard_items_overlap(item, current) for current in retained)
            )
        except (KeyError, TypeError, ValueError):
            continue
        if valid:
            retained.append(item)
            seen.add(item["chart_id"])

    missing_charts = [chart for chart in charts if int(chart["id"]) not in seen]
    if missing_charts:
        append_y = max((item["y"] + item["h"] for item in retained), default=0)
        for item in _default_dashboard_layout(missing_charts):
            retained.append({**item, "y": item["y"] + append_y})
    return sorted(retained, key=lambda item: (item["y"], item["x"], item["chart_id"]))


def _clone_snapshot_with_dashboard_layout(
    version: AnalyticsModelVersion,
    catalog_version: int,
    items: list[dict[str, int]],
) -> dict[str, Any]:
    """Create a layout-only catalog revision from the immutable active snapshot."""
    source = version.catalog_snapshot or {}
    if not isinstance(source, dict):
        raise AnalyticsValidationError("Active analytics catalog snapshot is invalid")
    snapshot = deepcopy(source)
    cube_catalog = snapshot.get("cubeCatalog")
    charts = snapshot.get("charts")
    if not isinstance(cube_catalog, dict) or not isinstance(charts, list):
        raise AnalyticsValidationError("Active analytics catalog snapshot is invalid")
    published_charts = [
        chart
        for chart in charts
        if isinstance(chart, dict) and chart.get("status") == "published"
    ]
    normalized = _validate_dashboard_layout(published_charts, items)
    cube_catalog["catalogVersion"] = catalog_version
    snapshot["dashboard_layout"] = {
        "dashboard": "overview",
        "columns": _DASHBOARD_COLUMNS,
        "items": normalized,
    }
    return snapshot


def _snapshot_charts(version: AnalyticsModelVersion | None, role: str) -> list[dict[str, Any]]:
    if version is None:
        return []
    snapshot = version.catalog_snapshot or {}
    charts = snapshot.get("charts", [])
    if not isinstance(charts, list):
        return []
    published_charts = [
        chart
        for chart in charts
        if isinstance(chart, dict) and chart.get("status") == "published"
    ]
    layout_by_chart = {
        item["chart_id"]: {key: item[key] for key in ("x", "y", "w", "h")}
        for item in _dashboard_layout_from_snapshot(version, published_charts)
    }
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
        item["layout"] = layout_by_chart.get(chart.get("id"))
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

    query_limit = min(int(values["limit"]), MAX_AGGREGATE_ROWS)
    query = QuerySpec(
        semantic_view=chart["semantic_view"],
        dimensions=dimensions,
        metric=values["metric"],
        aggregation=values["aggregation"],
        filters=values["filters"],
        time_dimension=values.get("time_dimension"),
        time_range=values.get("time_range"),
        timezone=values.get("timezone"),
        time_granularity=values.get("time_granularity"),
        order=values["order"],
        limit=query_limit,
    )
    query = validate_query(query, catalog, role)
    return query, compile_cube_query(query, catalog, role, _validated=True)


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
            scope=(getattr(field, "definition", None) or {}).get("scope", "response"),
            filterable=(getattr(field, "definition", None) or {}).get("filterable", True),
            filter_control=(getattr(field, "definition", None) or {}).get(
                "filter_control", "input"
            ),
            minimum_search_length=(getattr(field, "definition", None) or {}).get(
                "minimum_search_length", 0
            ),
            time_dimension=(getattr(field, "definition", None) or {}).get(
                "time_dimension", field.data_type in {"date", "time"}
            ),
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
                query_target=(metric.definition or {}).get("query_target"),
                public_aggregation=(metric.definition or {}).get(
                    "public_aggregation"
                ),
                entity=(metric.definition or {}).get("entity"),
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
        query_target=(metric.definition or {}).get("query_target"),
        public_aggregation=(metric.definition or {}).get("public_aggregation"),
        entity=(metric.definition or {}).get("entity"),
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
        Aggregation.FILTERED_DISTINCT_COUNT,
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
                "scope": (getattr(field, "definition", None) or {}).get("scope", "response"),
                "filterable": (getattr(field, "definition", None) or {}).get("filterable", True),
                "filterControl": (getattr(field, "definition", None) or {}).get(
                    "filter_control", "input"
                ),
                "minimumSearchLength": (getattr(field, "definition", None) or {}).get(
                    "minimum_search_length", 0
                ),
                "timeDimension": (getattr(field, "definition", None) or {}).get(
                    "time_dimension", field.data_type in {"date", "time"}
                ),
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
                "queryTarget": (metric.definition or {}).get("query_target"),
                "publicAggregation": (metric.definition or {}).get(
                    "public_aggregation"
                ),
                "entity": (metric.definition or {}).get("entity"),
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
    metric_by_option: dict[tuple[Any, Any, Any], list[tuple[str, str]]] = {}
    for metric in _CORE_METRICS:
        if metric.query_target is None or metric.public_aggregation is None:
            continue
        key = (
            metric.semantic_view,
            metric.query_target,
            metric.public_aggregation.value,
        )
        metric_by_option.setdefault(key, []).append(
            (metric.slug, metric.aggregation.value)
        )
    for item in metrics:
        if not isinstance(item, dict):
            continue
        key = (
            item.get("semanticView"),
            item.get("queryTarget"),
            item.get("publicAggregation"),
        )
        metric_by_option.setdefault(key, []).append(
            (str(item.get("slug")), str(item.get("operation")))
        )
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
        metric_target = definition.get("metric")
        aggregation = definition.get("aggregation")
        if (
            not isinstance(dimensions, list)
            or not isinstance(metric_target, str)
            or not isinstance(aggregation, str)
            or len(dimensions) > 3
        ):
            continue
        try:
            view = validate_identifier(str(chart["semantic_view"]))
            safe_dimensions = [validate_identifier(str(item)) for item in dimensions]
            candidates = metric_by_option.get((view, metric_target, aggregation), [])
            if len(candidates) != 1:
                continue
            measure_slug, physical_aggregation = candidates[0]
            safe_measures = [validate_identifier(measure_slug)]
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
            "nonAdditive": physical_aggregation not in additive,
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
    "/catalog",
    summary="Get the active analytics catalog",
    description=_ENDPOINT_DESCRIPTIONS["viewer_catalog"],
    response_model=AnalyticsCatalogResponse,
)
async def get_catalog(
    db: Session = Depends(get_db), current_user: ActorContext = Depends(get_current_actor)
) -> AnalyticsCatalogResponse:
    role = _role(current_user)
    try:
        version = _active_model_version(db)
        catalog = _catalog_from_version(version, role)
    except (AnalyticsValidationError, ValueError) as error:
        raise HTTPException(
            status_code=503,
            detail="Analytics catalog is invalid",
        ) from error
    return _catalog_response(catalog, version.catalog_version if version else 0, role)


@viewer_router.get(
    "/query-combinations",
    summary="List finite analytics query combinations",
    description=_ENDPOINT_DESCRIPTIONS["viewer_query_combinations"],
    response_model=QueryCombinationsResponse,
    response_model_exclude_none=True,
)
async def get_query_combinations(
    semantic_view: SemanticView
    | None = None,
    db: Session = Depends(get_db),
    current_user: ActorContext = Depends(get_current_actor),
) -> QueryCombinationsResponse:
    role = _role(current_user)
    try:
        version = _active_model_version(db)
        catalog = _catalog_from_version(version, role)
        return _query_combinations_response(
            catalog,
            version.catalog_version if version else 0,
            role,
            semantic_view,
        )
    except (AnalyticsValidationError, ValueError) as error:
        raise HTTPException(
            status_code=503,
            detail="Analytics catalog is invalid",
        ) from error


@viewer_router.post(
    "/query-capabilities",
    summary="Resolve analytics query capabilities",
    description=_ENDPOINT_DESCRIPTIONS["viewer_query_capabilities"],
    response_model=QueryCapabilitiesResponse,
)
async def get_query_capabilities(
    payload: QueryCapabilitiesInput,
    db: Session = Depends(get_db),
    current_user: ActorContext = Depends(get_current_actor),
) -> QueryCapabilitiesResponse:
    role = _role(current_user)
    try:
        version = _active_model_version(db)
        catalog = _catalog_from_version(version, role)
        return _query_capabilities_response(
            payload,
            catalog,
            version.catalog_version if version else 0,
            role,
        )
    except (AnalyticsValidationError, ValueError, KeyError, StopIteration) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@viewer_router.post(
    "/builder/options",
    summary="Resolve remaining chart builder options",
    description=_ENDPOINT_DESCRIPTIONS["viewer_builder_options"],
    response_model=BuilderOptionsResponse,
)
async def post_builder_options(
    payload: BuilderSelectionInput | None = Body(default=None),
    db: Session = Depends(get_db),
    current_user: ActorContext = Depends(get_current_actor),
) -> BuilderOptionsResponse:
    role = _role(current_user)
    selection = payload or BuilderSelectionInput()
    try:
        version = _active_model_version(db)
        catalog = _catalog_from_version(version, role)
        return _builder_options(
            selection,
            catalog,
            version.catalog_version if version else 0,
            role,
        )
    except (AnalyticsValidationError, ValueError, KeyError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@viewer_router.post(
    "/builder/query",
    summary="Run a chart builder selection",
    description=_ENDPOINT_DESCRIPTIONS["viewer_builder_query"],
)
async def post_builder_query(
    payload: BuilderQueryInput,
    db: Session = Depends(get_db),
    current_user: ActorContext = Depends(get_current_actor),
) -> dict[str, Any]:
    role = _role(current_user)
    try:
        version = _active_model_version(db)
        catalog = _catalog_from_version(version, role)
        semantic_view, warnings = _resolve_builder_view(payload, catalog, role)
        if semantic_view is None:
            detail = warnings[0] if warnings else (
                "No semantic view can answer that combination of measure and breakdowns"
            )
            raise HTTPException(status_code=422, detail=detail)
        query = _builder_query(payload, semantic_view)
    except (AnalyticsValidationError, ValueError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    response = await _execute_query(
        query, db, current_user, pinned_version=version, pinned_catalog=catalog
    )
    response["semantic_view_reason"] = _SEMANTIC_VIEW_GRAINS[semantic_view]
    if warnings:
        response.setdefault("warnings", []).extend(warnings)
    return response


@viewer_router.get(
    "/catalog/availability",
    summary="Get field data availability",
    description=_ENDPOINT_DESCRIPTIONS["viewer_availability"],
)
async def get_catalog_availability(
    semantic_view: SemanticView = "survey_responses",
    db: Session = Depends(get_db),
    current_user: ActorContext = Depends(get_current_actor),
) -> dict[str, Any]:
    role = _role(current_user)
    try:
        version = _active_model_version(db)
        catalog = _catalog_from_version(version, role)
        return _field_availability(
            db,
            catalog,
            role=role,
            semantic_view=semantic_view,
            catalog_version=version.catalog_version if version else 0,
            model_version=version,
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
    current_user: ActorContext = Depends(get_current_actor),
) -> dict[str, Any]:
    """Build a role-scoped filter dropdown from the governed semantic catalog."""

    role = _role(current_user)
    try:
        version = _active_model_version(db)
        catalog = _catalog_from_version(version, role)
        field = catalog.field(payload.member, payload.semantic_view)
        if not field.filterable:
            raise AnalyticsValidationError(
                f"Dimension {field.slug} is not available for filtering"
            )
        if field.filter_control == "input":
            raise AnalyticsValidationError(
                f"{field.label} accepts an exact value and does not provide listed options"
            )
        if (
            field.filter_control == "search"
            and (
                payload.search is None
                or len(payload.search) < field.minimum_search_length
            )
        ):
            raise AnalyticsValidationError(
                f"Search {field.label} with at least {field.minimum_search_length} characters"
            )
        count_target = _FILTER_OPTION_METRIC_TARGETS[payload.semantic_view]
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
            metric=count_target,
            aggregation=Aggregation.COUNT,
            filters=filters,
            timezone=payload.timezone,
            order=(
                OrderSpec(member="value", direction="desc"),
                OrderSpec(member=payload.member, direction="asc"),
            ),
            limit=payload.limit,
        )
        # filter-options is deliberately view-scoped. Aggregate queries normally
        # resolve the narrowest honest grain, but doing that here could silently
        # turn a survey_assignments selector into a single-assignment selector.
        validate_query_fields(
            semantic_view=payload.semantic_view,
            dimensions=query.dimensions,
            filters=query.filters,
            catalog=catalog,
            role=role,
        )
        resolve_query_metric(query, catalog, role)
        cube_query = compile_cube_query(query, catalog, role, _validated=True)
        cube_query["offset"] = payload.cursor or 0
    except (AnalyticsValidationError, ValueError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    result = await _execute_query(
        query,
        db,
        current_user,
        cube_query_override=cube_query,
        pinned_version=version,
        pinned_catalog=catalog,
        query_is_validated=True,
    )
    values = [
        {
            "value": row.get(payload.member),
            "count": row.get("value", 0),
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
    current_user: ActorContext = Depends(get_current_actor),
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
    current_user: ActorContext = Depends(get_current_actor),
) -> dict[str, Any]:
    if payload.representation == "full":
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

    if not _PROJECTED_RECORDS_SEMAPHORE.acquire(blocking=False):
        raise HTTPException(
            status_code=429,
            detail={
                "code": "analytics_records_capacity",
                "message": "Too many projected record queries are already running",
            },
            headers={"Retry-After": "2"},
        )
    role = _role(current_user)
    fields = payload.fields or DEFAULT_PROJECTED_RECORD_FIELDS
    query_id = str(uuid.uuid4())
    started = time.monotonic()
    version = None
    try:
        version = _active_model_version(db)
        catalog = _catalog_from_version(version, role)
        result = execute_projected_records(
            db,
            fields=fields,
            filters=tuple(payload.filters),
            cursor=payload.cursor,
            size=payload.size,
            timezone_name=payload.timezone,
            catalog=catalog,
            role=role,
            raw_fields=_raw_field_sources_from_version(version, role),
        )
        if _version_id(_active_model_version(db)) != _version_id(version):
            raise _AnalyticsCatalogChangedError
    except _AnalyticsCatalogChangedError as error:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "analytics_catalog_changed",
                "message": "Analytics catalog changed; retry the record query",
            },
        ) from error
    except (AnalyticsValidationError, ValueError) as error:
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
    finally:
        _PROJECTED_RECORDS_SEMAPHORE.release()

    completed_at = utc_now()
    db.add(
        AnalyticsQueryLog(
            id=query_id,
            **_actor_snapshot(current_user, "requested_by"),
            model_version_id=version.id if version else None,
            semantic_view="survey_responses",
            request={
                "kind": "records_projected",
                **payload.model_dump(mode="json"),
                "fields": list(fields),
            },
            status="completed",
            row_count=len(result["items"]),
            duration_ms=round((time.monotonic() - started) * 1_000),
            created_at=completed_at,
            completed_at=completed_at,
        )
    )
    _audit(
        db,
        current_user,
        "records.projected.executed",
        "query",
        query_id,
        {"row_count": len(result["items"])},
    )
    db.commit()
    return {
        "resource": "surveys",
        "representation": "projected",
        "items": result["items"],
        "size": payload.size,
        "cursor": payload.cursor,
        "next_cursor": result["next_cursor"],
        "has_more": result["has_more"],
        "query_id": query_id,
        "model_version": version.catalog_version if version else 0,
        "timezone": payload.timezone or "UTC",
    }


@viewer_router.get(
    "/charts/published", summary="List published charts", description=_ENDPOINT_DESCRIPTIONS["viewer_charts"]
)
async def get_published_charts(
    db: Session = Depends(get_db), current_user: ActorContext = Depends(get_current_actor)
) -> list[dict[str, Any]]:
    return _snapshot_charts(_active_model_version(db), _role(current_user))


@viewer_router.post(
    "/charts/{chart_id}/data", summary="Run published chart data", description=_ENDPOINT_DESCRIPTIONS["viewer_chart_data"]
)
async def get_published_chart_data(
    chart_id: int,
    payload: ChartDataInput | None = Body(default=None),
    db: Session = Depends(get_db),
    current_user: ActorContext = Depends(get_current_actor),
) -> dict[str, Any]:
    role = _role(current_user)
    version = _active_model_version(db)
    chart = next(
        (
            item
            for item in _snapshot_charts(version, role)
            if item.get("id") == chart_id
        ),
        None,
    )
    if chart is None:
        raise HTTPException(status_code=404, detail="Published chart not found")
    try:
        catalog = _catalog_from_version(version, role)
        query, cube_query = _chart_query(chart, payload, catalog, role)
    except (AnalyticsValidationError, ValueError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    response = await _execute_query(
        query,
        db,
        current_user,
        cube_query_override=cube_query,
        pinned_version=version,
        pinned_catalog=catalog,
    )
    response["chart"] = chart
    return response


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


def _ensure_unique_slug(
    db: Session, model: Any, slug: str, excluding_id: int | None = None
) -> None:
    query = db.query(model).filter(model.slug == slug)
    if excluding_id is not None:
        query = query.filter(model.id != excluding_id)
    if query.first() is not None:
        raise HTTPException(status_code=409, detail="Slug already exists")


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
    current_user: ActorContext = Depends(require_admin),
) -> dict[str, Any]:
    _ensure_unique_slug(db, AnalyticsChart, payload.slug)
    chart = AnalyticsChart(
        **_actor_snapshot(current_user, "created_by"), status="draft"
    )
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
    current_user: ActorContext = Depends(require_admin),
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


@admin_chart_router.post(
    "/charts/{chart_id}/publish", summary="Publish chart definition", description=_ENDPOINT_DESCRIPTIONS["admin_chart_publish"]
)
async def publish_chart(
    chart_id: int,
    db: Session = Depends(get_db),
    current_user: ActorContext = Depends(require_admin),
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
        version = await _publish_catalog_version(
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
    current_user: ActorContext = Depends(require_admin),
) -> dict[str, Any]:
    chart = _record_or_404(db, AnalyticsChart, chart_id, "Chart")
    chart.status = "archived"
    chart.archived_at = utc_now()
    _audit(db, current_user, "chart.archived", "chart", chart.id)
    # Exclude the chart from the catalog snapshot being activated below.
    db.flush()
    version = await _publish_catalog_version(
        CatalogPublicationInput(description=f"Delete chart {chart.slug}"),
        db,
        current_user,
    )
    db.refresh(chart)
    return {**chart.to_dict(), "model_version": version["catalog_version"]}


async def _publish_catalog_version(
    payload: CatalogPublicationInput,
    db: Session,
    current_user: ActorContext,
    *,
    dashboard_layout_override: list[dict[str, int]] | None = None,
    source_version: AnalyticsModelVersion | None = None,
    extra_audit: tuple[str, str, str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if _PROFILE.fullmatch(config.DEPLOYMENT_PROFILE) is None:
        raise HTTPException(status_code=422, detail="Invalid analytics deployment profile")
    if source_version is not None:
        current_active = _active_model_version(db)
        if (
            current_active is None
            or current_active.catalog_version != source_version.catalog_version
        ):
            raise HTTPException(
                status_code=409,
                detail="The analytics catalog changed while this layout was being edited; reload and try again",
            )
        if dashboard_layout_override is None:
            raise ValueError("A layout-only publication requires a dashboard layout")
        fields: list[AnalyticsField] = []
        metrics: list[AnalyticsMetric] = []
        charts: list[AnalyticsChart] = []
    else:
        fields, metrics, charts = _current_published_records(db)
    errors: list[dict[str, Any]] = []
    catalog = None
    if source_version is None:
        try:
            for field in fields:
                _validate_field_record(field)
            catalog = _catalog_from_records(fields, metrics)
            for metric in metrics:
                _validate_metric_record(metric, fields, catalog)
        except (AnalyticsValidationError, ValueError) as error:
            errors.append({"resource": "catalog", "error": str(error)})

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
    if source_version is not None:
        try:
            snapshot = _clone_snapshot_with_dashboard_layout(
                source_version,
                next_version,
                dashboard_layout_override or [],
            )
        except AnalyticsValidationError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        cube_catalog = snapshot["cubeCatalog"]
    else:
        cube_catalog = _cube_catalog_payload(fields, metrics, next_version)
        chart_snapshot = [chart.to_dict() for chart in charts]
        cube_catalog["rollups"] = _chart_rollups(
            chart_snapshot, cube_catalog["metrics"]
        )
        dashboard_layout = (
            dashboard_layout_override
            if dashboard_layout_override is not None
            else _dashboard_layout_from_snapshot(_active_model_version(db), chart_snapshot)
        )
        snapshot = {
            "cubeCatalog": cube_catalog,
            "charts": chart_snapshot,
            "dashboard_layout": {
                "dashboard": "overview",
                "columns": _DASHBOARD_COLUMNS,
                "items": dashboard_layout,
            },
        }
    try:
        _validate_cube_catalog_size(cube_catalog)
    except AnalyticsValidationError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
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
        **_actor_snapshot(current_user, "created_by"),
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
        if extra_audit is not None:
            action, resource_type, resource_id, details = extra_audit
            _audit(
                db,
                current_user,
                action,
                resource_type,
                resource_id,
                details,
            )
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(
            status_code=409, detail="Catalog publication conflicted; retry"
        ) from error
    db.refresh(version)
    return version.to_dict(include_snapshot=True)


@admin_chart_router.post(
    "/dashboard-layout/publish",
    summary="Publish the overview dashboard layout",
    description=_ENDPOINT_DESCRIPTIONS["admin_dashboard_layout_publish"],
    response_model=DashboardLayoutPublicationOutput,
)
async def publish_dashboard_layout(
    payload: DashboardLayoutPublicationInput,
    db: Session = Depends(get_db),
    current_user: ActorContext = Depends(require_admin),
) -> dict[str, Any]:
    active_version = _active_model_version(db)
    if active_version is None:
        raise HTTPException(status_code=409, detail="No active analytics model is available")
    chart_snapshot = _snapshot_charts(active_version, "admin")
    try:
        normalized = _validate_dashboard_layout(chart_snapshot, payload.items)
    except (AnalyticsValidationError, KeyError, TypeError, ValueError) as error:
        if active_version.catalog_version != payload.expected_model_version:
            raise HTTPException(
                status_code=409,
                detail="The analytics catalog changed while this layout was being edited; reload and try again",
            ) from error
        raise HTTPException(status_code=422, detail=str(error)) from error

    active_layout = _dashboard_layout_from_snapshot(active_version, chart_snapshot)
    if normalized == active_layout:
        return {
            "dashboard": payload.dashboard,
            "columns": _DASHBOARD_COLUMNS,
            "items": normalized,
            "changed": False,
            "model_version": active_version.catalog_version,
        }
    if active_version.catalog_version != payload.expected_model_version:
        raise HTTPException(
            status_code=409,
            detail="The analytics catalog changed while this layout was being edited; reload and try again",
        )

    version = await _publish_catalog_version(
        CatalogPublicationInput(description="Publish overview dashboard layout"),
        db,
        current_user,
        dashboard_layout_override=normalized,
        source_version=active_version,
        extra_audit=(
            "dashboard_layout.published",
            "dashboard_layout",
            payload.dashboard,
            {
                "dashboard": payload.dashboard,
                "item_count": len(normalized),
                "previous_model_version": payload.expected_model_version,
            },
        ),
    )
    return {
        "dashboard": payload.dashboard,
        "columns": _DASHBOARD_COLUMNS,
        "items": normalized,
        "changed": True,
        "model_version": version["catalog_version"],
    }


@viewer_router.post(
    "/exports", status_code=201, summary="Queue analytics export", description=_ENDPOINT_DESCRIPTIONS["viewer_export_create"]
)
async def create_analytics_export(
    payload: ExportInput,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: ActorContext = Depends(get_current_actor),
) -> dict[str, Any]:
    role = _role(current_user)
    _lock_export_admission(db)
    outstanding_statuses = ("queued", "processing")
    user_outstanding = (
        db.query(func.count(AnalyticsExportJob.id))
        .filter(
            AnalyticsExportJob.requested_by_subject
            == _actor_snapshot(current_user, "requested_by")["requested_by_subject"],
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
        catalog = _catalog_from_version(version, role)
        if payload.query is not None:
            semantic_query = validate_query(payload.query, catalog, role)
            semantic_view = semantic_query.semantic_view
            assert semantic_view is not None
            cube_query = augment_cube_query_with_supports(
                compile_cube_query(semantic_query, catalog, role, _validated=True),
                semantic_query,
                catalog,
                role,
            )
            request_payload = {
                "mode": "query",
                "role": role,
                "semantic_query": semantic_query.model_dump(mode="json"),
                "cube_query": cube_query,
            }
        else:
            assert payload.record_query is not None
            semantic_view = (
                "survey_responses"
                if payload.record_query.resource == "surveys"
                else payload.record_query.resource
            )
            # Validate all allowlists, operators, typed values, catalog
            # visibility, and projection sources at admission time. The worker
            # repeats validation against the pinned role before reading data.
            if payload.record_query.representation == "projected":
                build_projected_record_statement(
                    fields=(
                        payload.record_query.fields
                        or DEFAULT_PROJECTED_RECORD_FIELDS
                    ),
                    filters=tuple(payload.record_query.filters),
                    cursor=payload.record_query.cursor,
                    size=payload.record_query.size,
                    timezone_name=payload.record_query.timezone,
                    catalog=catalog,
                    role=role,
                    raw_fields=_raw_field_sources_from_version(version, role),
                )
            else:
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
        **_actor_snapshot(current_user, "requested_by"),
        model_version_id=version.id if version else None,
        semantic_view=semantic_view,
        request={"kind": "export", **request_payload},
        cube_query=cube_query,
        status="pending",
    )
    job = AnalyticsExportJob(
        id=job_id,
        **_actor_snapshot(current_user, "requested_by"),
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
    db: Session, job_id: str, current_user: ActorContext
) -> AnalyticsExportJob:
    job = (
        db.query(AnalyticsExportJob)
        .filter(AnalyticsExportJob.id == job_id)
        .first()
    )
    if job is None or (
        current_user.role != "admin"
        and job.requested_by_subject
        != _actor_snapshot(current_user, "requested_by")["requested_by_subject"]
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
    current_user: ActorContext = Depends(get_current_actor),
) -> dict[str, Any]:
    return _export_job_for_user(db, job_id, current_user).to_dict()


@viewer_router.get(
    "/exports/{job_id}/download", summary="Download analytics export", description=_ENDPOINT_DESCRIPTIONS["viewer_export_download"]
)
async def download_analytics_export(
    job_id: str,
    db: Session = Depends(get_db),
    current_user: ActorContext = Depends(get_current_actor),
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
