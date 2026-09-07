from __future__ import annotations

import base64
import os
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

os.environ.setdefault("DATABASE_USER", "test")
os.environ.setdefault("DATABASE_PASSWORD", "test")
os.environ.setdefault("DATABASE_HOST", "localhost")
os.environ.setdefault("DATABASE_PORT", "5432")
os.environ.setdefault("DATABASE_NAME", "test")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import core.config as config
import core.security as security
from features.analytics.endpoints import analytics
from features.analytics.model.semantic import (
    Aggregation,
    AnalyticsValidationError,
    CatalogField,
    CatalogMetric,
    FieldType,
    QueryAggregation,
    QuerySpec,
    SemanticCatalog,
    compile_cube_query,
    validate_query,
)
from features.identity.service.security import get_current_actor, require_admin
from infrastructure.database.session import get_db
from infrastructure.integrations.analytics_metadata_auth import sign_metadata_request
from infrastructure.integrations.cube import (
    CubePreAggregationNotReadyError,
    CubeQueryError,
    CubeQueryPendingError,
    CubeUnavailableError,
)


class FakeDb:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.commits = 0
        self.rollbacks = 0

    def add(self, value: object) -> None:
        self.added.append(value)

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


class FakeCube:
    def __init__(self, result: dict | None = None, error: Exception | None = None):
        self.result = result or {}
        self.error = error
        self.calls: list[tuple[dict, dict]] = []

    async def execute(self, query: dict, **kwargs: object) -> dict:
        self.calls.append((query, kwargs))
        if self.error:
            raise self.error
        return self.result


def _catalog() -> SemanticCatalog:
    return SemanticCatalog(
        fields=[
            CatalogField(
                slug="id",
                label="Response ID",
                semantic_view="survey_responses",
                data_type=FieldType.NUMBER,
            ),
            CatalogField(
                slug="store_name",
                label="Store",
                semantic_view="survey_responses",
                data_type=FieldType.STRING,
            ),
        ],
        metrics=[
            CatalogMetric(
                slug="survey_count",
                label="Responses",
                semantic_view="survey_responses",
                aggregation=Aggregation.COUNT,
                source_field="id",
                query_target="survey",
                public_aggregation="count",
                entity="survey",
            ),
        ],
    )


def test_core_dashboard_sentiment_metrics_are_queryable_without_publication() -> None:
    catalog = analytics._catalog_from_records([], [])
    # A slug is unique only within its grain; survey_count and
    # responding_store_count intentionally recur across semantic views.
    metrics = {
        (metric.semantic_view, metric.slug): metric for metric in catalog.metrics
    }

    responding_stores = metrics[("survey_responses", "responding_store_count")]
    assert responding_stores.aggregation is Aggregation.DISTINCT_COUNT
    assert responding_stores.source_field == "store_key"

    for sentiment in ("positive", "negative", "neutral", "mixed"):
        metric = metrics[("survey_responses", f"topic_sentiment_{sentiment}_count")]
        assert metric.aggregation is Aggregation.FILTERED_COUNT
        assert metric.source_field == "topic_sentiment"
        assert metric.parameters == {
            "filter": {"operator": "equals", "value": sentiment.upper()}
        }
        # The same sentiment is also reachable as a metric target so a chart can
        # measure one enum value without spending a group-by slot on it.
        assert metric.query_target == f"topic_sentiment_{sentiment}"
        assert metric.public_aggregation is QueryAggregation.COUNT

    for prefix, view in (
        ("topic", "survey_topics"),
        ("department", "survey_departments"),
        ("keyword", "survey_keywords"),
    ):
        for sentiment in ("positive", "negative", "neutral"):
            metric = metrics[(view, f"{prefix}_assignment_{sentiment}_count")]
            assert metric.aggregation is Aggregation.FILTERED_COUNT
            assert metric.source_field == "sentiment"
            assert metric.query_target == f"sentiment_{sentiment}"

    for view, target, entity in (
        ("survey_topics", "topic_assignment_sentiment", "topic_assignment"),
        ("survey_departments", "department_sentiment", "department_assignment"),
        ("survey_keywords", "keyword_sentiment", "keyword_assignment"),
    ):
        metric = metrics[(view, f"{target}_average")]
        assert metric.aggregation is Aggregation.AVERAGE
        assert metric.source_field == "sentiment_score"
        assert metric.query_target == target
        assert metric.public_aggregation is QueryAggregation.AVERAGE
        assert metric.entity == entity
        score = next(
            field
            for field in catalog.fields
            if field.semantic_view == view and field.slug == "sentiment_score"
        )
        assert score.data_type is FieldType.NUMBER
        assert score.published is False
        assert score.filterable is False

    # The combination grain must never count fanned-out rows.
    combination_survey_count = metrics[("survey_assignments", "survey_count")]
    assert combination_survey_count.aggregation is Aggregation.DISTINCT_COUNT
    assert combination_survey_count.source_field == "distinct_survey_id"

    for sentiment in ("positive", "negative", "neutral", "mixed"):
        metric = metrics[
            ("survey_assignments", f"topic_sentiment_{sentiment}_survey_count")
        ]
        assert metric.aggregation is Aggregation.FILTERED_DISTINCT_COUNT
        assert metric.source_field == "topic_sentiment"
        assert metric.parameters["distinctField"] == "distinct_survey_id"
        assert metric.query_target == f"topic_sentiment_{sentiment}"

    distinct_survey_id = next(
        field
        for field in catalog.fields
        if field.semantic_view == "survey_assignments"
        and field.slug == "distinct_survey_id"
    )
    assert distinct_survey_id.published is False
    assert distinct_survey_id.filterable is False


def test_core_filter_controls_do_not_enumerate_identifiers() -> None:
    catalog = analytics._catalog_from_records([], [])
    fields = {(field.semantic_view, field.slug): field for field in catalog.fields}

    assert fields[("survey_responses", "id")].filter_control == "input"
    assert fields[("survey_keywords", "assignment_id")].filter_control == "input"
    assert fields[("survey_assignments", "combination_id")].filter_control == "input"
    assert fields[("survey_keywords", "keyword")].filter_control == "search"
    assert fields[("survey_keywords", "keyword")].minimum_search_length == 2


def test_assignment_sentiment_average_targets_resolve_to_their_own_grains() -> None:
    catalog = analytics._catalog_from_records([], [])
    for dimension, target, semantic_view, measure in (
        (
            "topic",
            "topic_assignment_sentiment",
            "survey_topics",
            "topic_assignment_sentiment_average",
        ),
        (
            "department",
            "department_sentiment",
            "survey_departments",
            "department_sentiment_average",
        ),
        (
            "keyword",
            "keyword_sentiment",
            "survey_keywords",
            "keyword_sentiment_average",
        ),
    ):
        query = validate_query(
            {
                "dimensions": [dimension],
                "metric": target,
                "aggregation": "average",
            },
            catalog,
        )
        assert query.semantic_view == semantic_view
        assert compile_cube_query(query, catalog, _validated=True)["measures"] == [
            f"{semantic_view}.{measure}"
        ]

    with pytest.raises(AnalyticsValidationError, match="Crossing assignment families"):
        validate_query(
            {
                "dimensions": ["keyword", "department"],
                "metric": "keyword_sentiment",
                "aggregation": "average",
            },
            catalog,
        )


def test_distinct_metrics_match_their_core_cube_measures() -> None:
    """Keep the API catalog deduplication key aligned with Cube SQL."""

    catalog = analytics._catalog_from_records([], [])
    core_dir = Path(__file__).resolve().parents[2] / "cube" / "model" / "core"
    distinct_metrics = (
        metric
        for metric in catalog.metrics
        if metric.aggregation
        in {Aggregation.DISTINCT_COUNT, Aggregation.FILTERED_DISTINCT_COUNT}
    )

    for metric in distinct_metrics:
        distinct_field = (
            metric.parameters["distinctField"]
            if metric.aggregation is Aggregation.FILTERED_DISTINCT_COUNT
            else metric.source_field
        )
        assert isinstance(distinct_field, str)
        model = (core_dir / f"{metric.semantic_view}.yml").read_text()
        match = re.search(
            rf"^\s+- name: {re.escape(metric.slug)}\n"
            rf"\s+sql: (?P<sql>.+)$",
            model,
            flags=re.MULTILINE,
        )
        assert match is not None, metric.slug
        assert distinct_field in match.group("sql"), metric.slug


def test_published_chart_response_uses_active_snapshot_version() -> None:
    version = SimpleNamespace(
        catalog_version=7,
        catalog_snapshot={
            "charts": [
                {
                    "id": 2,
                    "status": "published",
                    "visibility": "viewer",
                    "published_model_version_id": 3,
                }
            ]
        },
    )

    assert analytics._snapshot_charts(version, "viewer") == [
        {
            "id": 2,
            "status": "published",
            "visibility": "viewer",
            "model_version": 7,
            "layout": {"x": 0, "y": 0, "w": 6, "h": 3},
        }
    ]


def _dashboard_charts() -> list[dict]:
    return [
        {"id": 1, "chart_type": "kpi", "status": "published", "visibility": "viewer"},
        {"id": 2, "chart_type": "line", "status": "published", "visibility": "viewer"},
        {"id": 3, "chart_type": "table", "status": "published", "visibility": "viewer"},
    ]


def test_default_dashboard_layout_matches_current_dashboard_shape() -> None:
    layout = analytics._default_dashboard_layout(_dashboard_charts())

    assert layout == [
        {"chart_id": 1, "x": 0, "y": 0, "w": 3, "h": 2},
        {"chart_id": 2, "x": 0, "y": 2, "w": 12, "h": 3},
        {"chart_id": 3, "x": 0, "y": 5, "w": 6, "h": 3},
    ]


def test_dashboard_layout_inherits_positions_and_appends_new_charts() -> None:
    version = SimpleNamespace(
        catalog_snapshot={
            "dashboard_layout": {
                "items": [
                    {"chart_id": 1, "x": 0, "y": 0, "w": 3, "h": 2},
                    {"chart_id": 2, "x": 0, "y": 2, "w": 12, "h": 3},
                ]
            }
        }
    )

    layout = analytics._dashboard_layout_from_snapshot(version, _dashboard_charts())

    assert layout[:2] == version.catalog_snapshot["dashboard_layout"]["items"]
    assert layout[2] == {"chart_id": 3, "x": 0, "y": 5, "w": 6, "h": 3}


def test_dashboard_layout_snapshot_clone_preserves_published_chart_set() -> None:
    charts = _dashboard_charts()
    source_snapshot = {
        "cubeCatalog": {
            "profile": "wtchk_cls",
            "catalogVersion": 7,
            "fields": [{"slug": "store"}],
            "metrics": [{"slug": "survey_count"}],
            "rollups": [{"slug": "chart_1"}],
        },
        "charts": charts,
        "dashboard_layout": {"items": analytics._default_dashboard_layout(charts)},
    }
    version = SimpleNamespace(catalog_snapshot=source_snapshot)
    changed = [
        {"chart_id": 1, "x": 0, "y": 0, "w": 3, "h": 2},
        {"chart_id": 2, "x": 0, "y": 2, "w": 6, "h": 5},
        {"chart_id": 3, "x": 6, "y": 2, "w": 6, "h": 5},
    ]

    cloned = analytics._clone_snapshot_with_dashboard_layout(version, 8, changed)

    assert cloned["charts"] == charts
    assert cloned["cubeCatalog"] == {
        **source_snapshot["cubeCatalog"],
        "catalogVersion": 8,
    }
    assert cloned["dashboard_layout"]["items"] == changed
    assert source_snapshot["cubeCatalog"]["catalogVersion"] == 7
    assert source_snapshot["dashboard_layout"]["items"] != changed


def test_dashboard_layout_removes_archived_charts() -> None:
    version = SimpleNamespace(
        catalog_snapshot={
            "dashboard_layout": {
                "items": [
                    {"chart_id": 1, "x": 0, "y": 0, "w": 3, "h": 2},
                    {"chart_id": 2, "x": 0, "y": 2, "w": 12, "h": 3},
                ]
            }
        }
    )

    layout = analytics._dashboard_layout_from_snapshot(version, [_dashboard_charts()[0]])

    assert layout == [{"chart_id": 1, "x": 0, "y": 0, "w": 3, "h": 2}]


@pytest.mark.parametrize(
    ("items", "message"),
    [
        (
            [
                {"chart_id": 1, "x": 0, "y": 0, "w": 3, "h": 2},
                {"chart_id": 1, "x": 3, "y": 0, "w": 3, "h": 2},
                {"chart_id": 3, "x": 0, "y": 7, "w": 6, "h": 5},
            ],
            "duplicate",
        ),
        (
            [
                {"chart_id": 1, "x": 0, "y": 0, "w": 3, "h": 2},
                {"chart_id": 2, "x": 0, "y": 2, "w": 12, "h": 5},
            ],
            "missing chart IDs",
        ),
        (
            [
                {"chart_id": 1, "x": 0, "y": 0, "w": 3, "h": 2},
                {"chart_id": 2, "x": 2, "y": 0, "w": 10, "h": 5},
                {"chart_id": 3, "x": 0, "y": 5, "w": 6, "h": 3},
            ],
            "overlap",
        ),
        (
            [
                {"chart_id": 1, "x": 0, "y": 0, "w": 3, "h": 2},
                {"chart_id": 2, "x": 9, "y": 2, "w": 4, "h": 3},
                {"chart_id": 3, "x": 0, "y": 5, "w": 6, "h": 3},
            ],
            "beyond",
        ),
        (
            [
                {"chart_id": 1, "x": 0, "y": 0, "w": 2, "h": 2},
                {"chart_id": 2, "x": 0, "y": 2, "w": 12, "h": 5},
                {"chart_id": 3, "x": 0, "y": 7, "w": 6, "h": 5},
            ],
            "at least 3 columns by 2 rows",
        ),
        (
            [
                {"chart_id": 1, "x": 0, "y": 0, "w": 3, "h": 2},
                {"chart_id": 2, "x": 0, "y": 2, "w": 12, "h": 13},
                {"chart_id": 3, "x": 0, "y": 15, "w": 6, "h": 3},
            ],
            "limits",
        ),
    ],
)
def test_dashboard_layout_validation_errors(items: list[dict], message: str) -> None:
    with pytest.raises(AnalyticsValidationError, match=message):
        analytics._validate_dashboard_layout(_dashboard_charts(), items)


def test_dashboard_layout_publish_is_atomic_and_audited(monkeypatch) -> None:
    charts = _dashboard_charts()
    active = SimpleNamespace(
        catalog_version=7,
        catalog_snapshot={
            "charts": charts,
            "dashboard_layout": {"items": analytics._default_dashboard_layout(charts)},
        },
    )
    captured: dict = {}

    async def publish(payload, db, actor, **kwargs):
        captured.update(kwargs)
        return {"catalog_version": 8}

    monkeypatch.setattr(config, "ANALYTICS_ENABLED", True)
    monkeypatch.setattr(analytics, "_active_model_version", lambda db: active)
    monkeypatch.setattr(
        analytics,
        "_current_published_records",
        lambda db: pytest.fail("layout validation must not read mutable chart records"),
    )
    monkeypatch.setattr(analytics, "_publish_catalog_version", publish)
    payload = [
        {"chart_id": 1, "x": 0, "y": 0, "w": 3, "h": 2},
        {"chart_id": 2, "x": 0, "y": 2, "w": 6, "h": 5},
        {"chart_id": 3, "x": 6, "y": 2, "w": 6, "h": 5},
    ]

    response = _client(FakeDb(), role="admin").post(
        "/admin/analytics/dashboard-layout/publish",
        json={"dashboard": "overview", "expected_model_version": 7, "items": payload},
    )

    assert response.status_code == 200
    assert response.json() == {
        "dashboard": "overview",
        "columns": 12,
        "items": payload,
        "changed": True,
        "model_version": 8,
    }
    assert captured["dashboard_layout_override"] == payload
    assert captured["source_version"] is active
    assert captured["extra_audit"][0] == "dashboard_layout.published"


def test_dashboard_layout_publish_rejects_stale_version_but_idempotent_retry_succeeds(monkeypatch) -> None:
    charts = _dashboard_charts()
    current = analytics._default_dashboard_layout(charts)
    active = SimpleNamespace(
        catalog_version=8,
        catalog_snapshot={"charts": charts, "dashboard_layout": {"items": current}},
    )
    monkeypatch.setattr(config, "ANALYTICS_ENABLED", True)
    monkeypatch.setattr(analytics, "_active_model_version", lambda db: active)
    client = _client(FakeDb(), role="admin")

    stale = client.post(
        "/admin/analytics/dashboard-layout/publish",
        json={
            "dashboard": "overview",
            "expected_model_version": 7,
            "items": [
                {"chart_id": 1, "x": 0, "y": 0, "w": 3, "h": 2},
                {"chart_id": 2, "x": 0, "y": 2, "w": 6, "h": 5},
                {"chart_id": 3, "x": 6, "y": 2, "w": 6, "h": 5},
            ],
        },
    )
    retry = client.post(
        "/admin/analytics/dashboard-layout/publish",
        json={"dashboard": "overview", "expected_model_version": 7, "items": current},
    )

    assert stale.status_code == 409
    assert retry.status_code == 200
    assert retry.json()["changed"] is False
    assert retry.json()["model_version"] == 8


def _client(db: FakeDb, role: str = "user") -> TestClient:
    app = FastAPI()
    app.include_router(analytics.router)
    user = SimpleNamespace(id="user-1", role=role)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_actor] = lambda: user
    app.dependency_overrides[require_admin] = lambda: user
    return TestClient(app)


def test_openapi_describes_every_analytics_endpoint() -> None:
    schema = _client(FakeDb()).get("/openapi.json").json()
    for route in analytics.router.routes:
        for method in route.methods or ():
            if method not in {"GET", "POST", "PUT", "DELETE"}:
                continue
            operation = schema["paths"][route.path][method.lower()]
            assert operation["summary"]
            assert operation["description"]

    models = schema["components"]["schemas"]
    assert models["QuerySpec"]["required"] == ["metric", "aggregation"]
    assert models["QuerySpec"]["properties"]["semantic_view"]["deprecated"] is True
    assert models["QueryAggregation"]["enum"] == [
        "count",
        "distinct_count",
        "sum",
        "average",
        "min",
        "max",
        "median",
    ]
    for name in (
        "AnalyticsCatalogResponse",
        "CatalogCombinationsOutput",
        "DashboardLayoutPublicationOutput",
        "SemanticViewCombinationOutput",
        "QueryCapabilitiesResponse",
    ):
        assert name in models
    assert "ChartCombinationOutput" not in models
    assert "usage" not in models["CatalogFieldOutput"]["properties"]
    assert "chart_types" not in models["AnalyticsCatalogResponse"]["properties"]
    for field in ("chart_type", "series_limit", "fill_empty"):
        assert field not in models["QuerySpec"]["properties"]

    for name in (
        "FilterSpec",
        "OrderSpec",
        "QuerySpec",
        "QueryCapabilitiesInput",
        "RecordQueryInput",
        "ChartDefinitionInput",
        "ChartInput",
        "ChartDataInput",
        "FilterOptionsInput",
        "ExportInput",
    ):
        assert models[name]["examples"]

    assert "/admin/analytics/charts" in schema["paths"]
    assert "/admin/analytics/charts/{chart_id}" in schema["paths"]
    assert "delete" in schema["paths"]["/admin/analytics/charts/{chart_id}"]
    assert "/admin/analytics/dashboard-layout/publish" in schema["paths"]
    assert "post" in schema["paths"]["/admin/analytics/dashboard-layout/publish"]
    assert "/admin/analytics/charts/{chart_id}/validate" not in schema["paths"]
    assert "/admin/analytics/fields" not in schema["paths"]
    assert "/admin/analytics/metrics" not in schema["paths"]
    assert "/admin/analytics/catalog/publish" not in schema["paths"]

    catalog_response = schema["paths"]["/analytics/catalog"]["get"]["responses"]["200"]
    assert catalog_response["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/AnalyticsCatalogResponse"
    }
    combinations_response = schema["paths"]["/analytics/query-combinations"]["get"][
        "responses"
    ]["200"]
    assert combinations_response["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/QueryCombinationsResponse"
    }


def test_query_capabilities_use_the_same_goal_first_resolver(monkeypatch) -> None:
    db = FakeDb()
    catalog = analytics._catalog_from_records([], [])
    monkeypatch.setattr(config, "ANALYTICS_ENABLED", True)
    monkeypatch.setattr(analytics, "_catalog_from_version", lambda version, role: catalog)
    monkeypatch.setattr(analytics, "_active_model_version", lambda db: None)
    client = _client(db)

    response = client.post(
        "/analytics/query-capabilities",
        json={
            "semantic_view": "survey_keywords",
            "metric": "survey",
            "aggregation": "count",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["metric"] == {
        "metric": "survey",
        "label": "Survey",
        "entity": "survey",
        "aggregation": "count",
        "aggregation_label": "Unique Survey Count",
        "result_type": "number",
    }
    assert body["result_type"] == "number"
    assert "keyword" in {item["slug"] for item in body["allowed_dimensions"]}
    assert "reported_at" in {
        item["slug"] for item in body["allowed_time_dimensions"]
    }
    keyword_filter = next(
        item for item in body["filter_members"] if item["field"] == "keyword"
    )
    assert "contains" in keyword_filter["operators"]

    sentiment_average = client.post(
        "/analytics/query-capabilities",
        json={
            "semantic_view": "survey_keywords",
            "metric": "keyword_sentiment",
            "aggregation": "average",
        },
    )
    assert sentiment_average.status_code == 200
    sentiment_body = sentiment_average.json()
    assert sentiment_body["metric"]["aggregation_label"] == (
        "Average Keyword Assignment Sentiment"
    )
    assert "sentiment_score" not in {
        item["slug"] for item in sentiment_body["allowed_dimensions"]
    }
    assert "sentiment_score" not in {
        item["field"] for item in sentiment_body["filter_members"]
    }

    invalid = client.post(
        "/analytics/query-capabilities",
        json={
            "semantic_view": "survey_keywords",
            "metric": "cls",
            "aggregation": "average",
        },
    )
    assert invalid.status_code == 422
    assert "not published" in invalid.json()["detail"]

    rejected = client.post(
        "/analytics/query-capabilities",
        json={
            "semantic_view": "survey_keywords",
            "metric": "assignment_id",
            "aggregation": "count",
        },
    )
    assert rejected.status_code == 422


def test_catalog_exposes_machine_readable_member_and_chart_combinations(
    monkeypatch,
) -> None:
    db = FakeDb()
    catalog = analytics._catalog_from_records([], [])
    monkeypatch.setattr(config, "ANALYTICS_ENABLED", True)
    monkeypatch.setattr(analytics, "_catalog_from_version", lambda version, role: catalog)
    monkeypatch.setattr(analytics, "_active_model_version", lambda db: None)

    response = _client(db).get("/analytics/catalog")

    assert response.status_code == 200
    payload = response.json()
    combinations = payload["combinations"]
    assert combinations["query"] == {
        "max_dimensions": 3,
        "exact_metric_count": 1,
        "max_filters": 20,
        "requires_single_semantic_view": True,
        "members_must_belong_to_semantic_view": True,
        "order_members_must_be_selected": True,
        "time_dimension_must_not_be_dimension": True,
    }

    fields_by_view = {
        semantic_view: {
            field["slug"]
            for field in payload["fields"]
            if field["semantic_view"] == semantic_view
        }
        for semantic_view in payload["semantic_views"]
    }
    assert set(payload["metric_targets"]) == set(payload["semantic_views"])
    response_targets = {
        item["metric"]: {method["method"] for method in item["aggregations"]}
        for item in payload["metric_targets"]["survey_responses"]
    }
    assert response_targets["survey"] == {"count"}
    assert response_targets["cls"] == {"sum", "average"}
    assert response_targets["topic_sentiment_score"] == {
        "sum",
        "average",
        "median",
    }
    for semantic_view, target in (
        ("survey_topics", "topic_assignment_sentiment"),
        ("survey_departments", "department_sentiment"),
        ("survey_keywords", "keyword_sentiment"),
    ):
        targets = {
            item["metric"]: {method["method"] for method in item["aggregations"]}
            for item in payload["metric_targets"][semantic_view]
        }
        assert targets[target] == {"average"}
        assert "sentiment_score" not in fields_by_view[semantic_view]
    view_rules = {
        item["semantic_view"]: item
        for item in combinations["semantic_views"]
    }
    assert set(view_rules) == set(payload["semantic_views"])
    for semantic_view, rule in view_rules.items():
        assert set(rule["dimensions"]) == fields_by_view[semantic_view]
        assert rule["response_sentiment_dimension"] == "topic_sentiment"

    assert view_rules["survey_responses"]["assignment_dimension"] is None
    assert view_rules["survey_responses"]["assignment_sentiment_dimension"] is None
    assert "topic" not in view_rules["survey_responses"]["dimensions"]

    assert view_rules["survey_topics"]["assignment_dimension"] == "topic"
    assert view_rules["survey_topics"]["assignment_sentiment_dimension"] == "sentiment"
    assert "topic" in view_rules["survey_topics"]["dimensions"]

    assert "charts" not in combinations
    assert "chart_types" not in payload
    assert all("usage" not in field for field in payload["fields"])


def test_query_combinations_return_finite_executable_templates(monkeypatch) -> None:
    db = FakeDb()
    catalog = analytics._catalog_from_records([], [])
    monkeypatch.setattr(config, "ANALYTICS_ENABLED", True)
    monkeypatch.setattr(analytics, "_catalog", lambda db, role: catalog)
    monkeypatch.setattr(analytics, "_active_model_version", lambda db: None)

    response = _client(db).get("/analytics/query-combinations")

    assert response.status_code == 200
    payload = response.json()
    assert payload["model_version"] == 0
    assert payload["count"] == len(payload["combinations"])
    assert 1 <= payload["count"] <= 50

    slugs = [item["slug"] for item in payload["combinations"]]
    assert len(slugs) == len(set(slugs))
    assert {
        "responses_total",
        "responses_by_day",
        "responses_by_sentiment_by_day",
        "responding_stores_total",
        "responding_stores_by_region",
        "responding_stores_by_store_format",
        "topic_assignments_by_topic",
        "department_assignments_by_department",
        "keyword_assignments_by_keyword",
    }.issubset(slugs)

    for item in payload["combinations"]:
        query = QuerySpec.model_validate(item["query"])
        assert validate_query(query, catalog) == query
        assert item["semantic_view"] == query.semantic_view
        assert "compatible_chart_types" not in item
        assert set(item["allowed_overrides"]).issubset(
            {"filters", "time_range", "timezone", "order", "limit"}
        )

    daily = next(
        item for item in payload["combinations"] if item["slug"] == "responses_by_day"
    )
    assert daily["query"]["dimensions"] == []
    assert daily["query"]["time_dimension"] == "reported_at"
    assert daily["query"]["time_granularity"] == "day"
    assert "reported_at" not in daily["query"]["dimensions"]
    assert "time_range" in daily["allowed_overrides"]

    responding_stores = next(
        item
        for item in payload["combinations"]
        if item["slug"] == "responding_stores_by_region"
    )
    assert responding_stores["query"]["semantic_view"] == "survey_responses"
    assert responding_stores["query"]["dimensions"] == ["region"]
    assert responding_stores["query"]["metric"] == "store"
    assert responding_stores["query"]["aggregation"] == "count"


def test_query_combinations_can_be_filtered_by_semantic_view(monkeypatch) -> None:
    db = FakeDb()
    catalog = analytics._catalog_from_records([], [])
    monkeypatch.setattr(config, "ANALYTICS_ENABLED", True)
    monkeypatch.setattr(analytics, "_catalog", lambda db, role: catalog)
    monkeypatch.setattr(analytics, "_active_model_version", lambda db: None)

    response = _client(db).get(
        "/analytics/query-combinations",
        params={"semantic_view": "survey_topics"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] > 0
    assert {
        item["semantic_view"] for item in payload["combinations"]
    } == {"survey_topics"}
    assert all(
        item["query"]["semantic_view"] == "survey_topics"
        for item in payload["combinations"]
    )


def test_daily_query_combination_can_be_posted_without_time_dimension_duplication(
    monkeypatch,
) -> None:
    db = FakeDb()
    cube = FakeCube({"data": []})
    catalog = analytics._catalog_from_records([], [])
    monkeypatch.setattr(config, "ANALYTICS_ENABLED", True)
    monkeypatch.setattr(config, "DEPLOYMENT_PROFILE", "wtchk_cls")
    monkeypatch.setattr(analytics, "_catalog", lambda db, role: catalog)
    monkeypatch.setattr(analytics, "_active_model_version", lambda db: None)
    monkeypatch.setattr(analytics, "_cube_client", lambda: cube)
    client = _client(db)

    combinations = client.get(
        "/analytics/query-combinations",
        params={"semantic_view": "survey_responses"},
    ).json()["combinations"]
    query = next(
        item["query"] for item in combinations if item["slug"] == "responses_by_day"
    )
    query["timezone"] = "Asia/Hong_Kong"

    response = client.post("/analytics/query", json=query)

    assert response.status_code == 200
    assert cube.calls[0][0] == {
        "dimensions": [],
        "measures": ["survey_responses.survey_count"],
        "timeDimensions": [
            {
                "dimension": "survey_responses.reported_at",
                "granularity": "day",
            }
        ],
        "timezone": "Asia/Hong_Kong",
        "limit": 100,
    }


def test_field_availability_reports_non_null_data_for_visible_fields(monkeypatch) -> None:
    class AvailabilityDb:
        statement = None
        parameters = None

        def execute(self, statement, parameters):
            self.statement = statement
            self.parameters = parameters
            return SimpleNamespace(
                mappings=lambda: SimpleNamespace(
                    one=lambda: {"total_rows": 3, "non_null_0": 2}
                )
            )

    db = AvailabilityDb()
    catalog = SemanticCatalog(
        fields=[
            CatalogField(
                slug="store_name",
                label="Store",
                semantic_view="survey_responses",
                data_type=FieldType.STRING,
            ),
            CatalogField(
                slug="admin_note",
                label="Admin note",
                semantic_view="survey_responses",
                data_type=FieldType.STRING,
                visibility="admin",
            ),
        ]
    )
    monkeypatch.setattr(
        analytics,
        "_raw_field_sources_from_version",
        lambda version, role: {},
    )
    analytics._FIELD_AVAILABILITY_CACHE.clear()

    result = analytics._field_availability(
        db,
        catalog,
        role="viewer",
        semantic_view="survey_responses",
        catalog_version=999,
    )

    assert str(db.statement).endswith("FROM analytics_survey_facts")
    assert result["total_rows"] == 3
    assert result["fields"] == [
        {
            "slug": "store_name",
            "label": "Store",
            "data_type": "string",
            "non_null_count": 2,
            "null_count": 1,
            "availability_rate": pytest.approx(2 / 3),
            "available": True,
        }
    ]


def test_filter_options_return_non_null_governed_values(monkeypatch) -> None:
    db = FakeDb()
    catalog = SemanticCatalog(
        fields=[
            CatalogField(
                slug="id",
                label="Response ID",
                semantic_view="survey_responses",
                data_type=FieldType.NUMBER,
            ),
            CatalogField(
                slug="store_format",
                label="Store format",
                semantic_view="survey_responses",
                data_type=FieldType.STRING,
            ),
            CatalogField(
                slug="topic_sentiment",
                label="Topic sentiment",
                semantic_view="survey_responses",
                data_type=FieldType.STRING,
            ),
        ],
        metrics=[
            CatalogMetric(
                slug="survey_count",
                label="Response count",
                semantic_view="survey_responses",
                aggregation=Aggregation.COUNT,
                source_field="id",
                query_target="survey",
                public_aggregation="count",
                entity="survey",
            )
        ],
    )
    cube = FakeCube(
        {
            "data": [
                {
                    "survey_responses.store_format": "Mall",
                    "survey_responses.survey_count": "12",
                }
            ]
        }
    )
    monkeypatch.setattr(config, "ANALYTICS_ENABLED", True)
    monkeypatch.setattr(config, "DEPLOYMENT_PROFILE", "wtchk_cls")
    monkeypatch.setattr(analytics, "_catalog", lambda db, role: catalog)
    monkeypatch.setattr(analytics, "_active_model_version", lambda db: None)
    monkeypatch.setattr(analytics, "_cube_client", lambda: cube)

    response = _client(db).post(
        "/analytics/filter-options",
        json={
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
            "limit": 1,
            "cursor": 1000,
        },
    )

    assert response.status_code == 200
    assert response.json()["values"] == [{"value": "Mall", "count": 12}]
    assert "metric_columns" not in response.json()
    assert response.json()["cursor"] == 1000
    assert response.json()["next_cursor"] == 1001
    assert response.json()["has_more"] is True
    assert cube.calls[0][0]["filters"] == [
        {
            "member": "survey_responses.topic_sentiment",
            "operator": "equals",
            "values": ["NEGATIVE"],
        },
        {
            "member": "survey_responses.store_format",
            "operator": "set",
        },
        {
            "member": "survey_responses.store_format",
            "operator": "contains",
            "values": ["Mall"],
        },
    ]
    assert cube.calls[0][0]["order"] == {
        "survey_responses.survey_count": "desc",
        "survey_responses.store_format": "asc",
    }
    assert cube.calls[0][0]["offset"] == 1000


def test_filter_options_enforce_catalog_option_controls(monkeypatch) -> None:
    db = FakeDb()
    catalog = SemanticCatalog(
        fields=[
            CatalogField(
                slug="id",
                label="Response ID",
                semantic_view="survey_responses",
                data_type=FieldType.NUMBER,
                filter_control="input",
            ),
            CatalogField(
                slug="keyword",
                label="Keyword",
                semantic_view="survey_responses",
                data_type=FieldType.STRING,
                filter_control="search",
                minimum_search_length=2,
            ),
        ],
        metrics=[
            CatalogMetric(
                slug="survey_count",
                label="Response count",
                semantic_view="survey_responses",
                aggregation=Aggregation.COUNT,
                source_field="id",
                query_target="survey",
                public_aggregation="count",
                entity="survey",
            )
        ],
    )
    captured: dict[str, object] = {}

    async def fake_execute(
        query,
        db,
        current_user,
        *,
        cube_query_override=None,
        pinned_version=None,
        pinned_catalog=None,
        query_is_validated=False,
    ):
        captured["query"] = query
        captured["cube_query"] = cube_query_override
        captured["query_is_validated"] = query_is_validated
        return {
            "query_id": "query-1",
            "model_version": 0,
            "rows": [{"keyword": "Delivery", "value": 12}],
            "warnings": [],
            "freshness_time": None,
        }

    monkeypatch.setattr(config, "ANALYTICS_ENABLED", True)
    monkeypatch.setattr(config, "DEPLOYMENT_PROFILE", "wtchk_cls")
    monkeypatch.setattr(analytics, "_catalog_from_version", lambda version, role: catalog)
    monkeypatch.setattr(analytics, "_active_model_version", lambda db: None)
    monkeypatch.setattr(analytics, "_execute_query", fake_execute)
    client = _client(db)

    input_response = client.post(
        "/analytics/filter-options",
        json={"semantic_view": "survey_responses", "member": "id"},
    )
    short_search_response = client.post(
        "/analytics/filter-options",
        json={
            "semantic_view": "survey_responses",
            "member": "keyword",
            "search": "d",
        },
    )
    search_response = client.post(
        "/analytics/filter-options",
        json={
            "semantic_view": "survey_responses",
            "member": "keyword",
            "search": "de",
        },
    )

    assert input_response.status_code == 422
    assert "does not provide listed options" in input_response.json()["detail"]
    assert short_search_response.status_code == 422
    assert "at least 2 characters" in short_search_response.json()["detail"]
    assert search_response.status_code == 200
    assert search_response.json()["values"] == [{"value": "Delivery", "count": 12}]
    assert captured["query_is_validated"] is True
    assert captured["query"].semantic_view == "survey_responses"
    assert captured["cube_query"]["filters"] == [
        {"member": "survey_responses.keyword", "operator": "set"},
        {
            "member": "survey_responses.keyword",
            "operator": "contains",
            "values": ["de"],
        },
    ]


def test_frontend_dashboard_analytics_discovery_and_chart_flow(monkeypatch) -> None:
    """Keep the documented frontend bootstrap-to-chart request chain executable."""

    db = FakeDb()
    catalog = SemanticCatalog(
        fields=[
            CatalogField(
                slug="id",
                label="Response ID",
                semantic_view="survey_responses",
                data_type=FieldType.NUMBER,
            ),
            CatalogField(
                slug="store_format",
                label="Store format",
                semantic_view="survey_responses",
                data_type=FieldType.STRING,
            )
        ],
        metrics=[
            CatalogMetric(
                slug="survey_count",
                label="Response count",
                semantic_view="survey_responses",
                aggregation=Aggregation.COUNT,
                source_field="id",
                query_target="survey",
                public_aggregation="count",
                entity="survey",
            )
        ],
    )
    chart = {
        "id": 41,
        "slug": "dashboard_store_format_distribution",
        "title": "Responses by store format",
        "chart_type": "bar",
        "semantic_view": "survey_responses",
        "definition": {
            "dimensions": ["store_format"],
            "metric": "survey",
            "aggregation": "count",
            "limit": 100,
        },
        "visibility": "viewer",
        "status": "published",
    }
    version = SimpleNamespace(
        id=17,
        catalog_version=7,
        catalog_snapshot={"charts": [chart]},
    )
    cube = FakeCube(
        {
            "data": [
                {
                    "survey_responses.store_format": "Mall",
                    "survey_responses.survey_count": "12",
                }
            ],
            "lastRefreshTime": "2026-08-26T08:00:00Z",
        }
    )

    monkeypatch.setattr(config, "ANALYTICS_ENABLED", True)
    monkeypatch.setattr(config, "DEPLOYMENT_PROFILE", "wtchk_cls")
    monkeypatch.setattr(analytics, "_catalog_from_version", lambda version, role: catalog)
    monkeypatch.setattr(analytics, "_active_model_version", lambda db: version)
    monkeypatch.setattr(analytics, "_cube_client", lambda: cube)
    monkeypatch.setattr(
        analytics,
        "_field_availability",
        lambda db, catalog, **kwargs: {
            "model_version": kwargs["catalog_version"],
            "semantic_view": kwargs["semantic_view"],
            "total_rows": 12,
            "fields": [
                {
                    "slug": "store_format",
                    "label": "Store format",
                    "data_type": "string",
                    "non_null_count": 12,
                    "null_count": 0,
                    "availability_rate": 1.0,
                    "available": True,
                }
            ],
            "generated_at": "2026-08-26T08:00:00+00:00",
            "cached": False,
        },
    )
    client = _client(db)

    catalog_response = client.get("/analytics/catalog")
    assert catalog_response.status_code == 200
    assert catalog_response.json()["model_version"] == 7
    assert {item["slug"] for item in catalog_response.json()["fields"]} == {
        "id",
        "store_format",
    }

    availability_response = client.get(
        "/analytics/catalog/availability",
        params={"semantic_view": "survey_responses"},
    )
    assert availability_response.status_code == 200
    assert availability_response.json()["fields"][0]["available"] is True

    charts_response = client.get("/analytics/charts/published")
    assert charts_response.status_code == 200
    published_chart = charts_response.json()[0]
    assert published_chart["model_version"] == 7
    assert published_chart["layout"] == {"x": 0, "y": 0, "w": 6, "h": 3}

    options_response = client.post(
        "/analytics/filter-options",
        json={
            "semantic_view": "survey_responses",
            "member": "store_format",
            "timezone": "Asia/Hong_Kong",
            "limit": 100,
        },
    )
    assert options_response.status_code == 200
    selected_value = options_response.json()["values"][0]["value"]
    assert selected_value == "Mall"

    data_response = client.post(
        f"/analytics/charts/{published_chart['id']}/data",
        json={
            "filters": [
                {
                    "member": "store_format",
                    "operator": "equals",
                    "value": selected_value,
                }
            ],
            "timezone": "Asia/Hong_Kong",
        },
    )
    assert data_response.status_code == 200
    assert data_response.json()["chart"]["slug"] == chart["slug"]
    assert data_response.json()["rows"] == [
        {"store_format": "Mall", "value": 12}
    ]
    assert data_response.json()["model_version"] == 7
    assert cube.calls[1][0]["filters"] == [
        {
            "member": "survey_responses.store_format",
            "operator": "equals",
            "values": ["Mall"],
        }
    ]


def test_feature_gate_is_evaluated_dynamically(monkeypatch) -> None:
    db = FakeDb()
    monkeypatch.setattr(config, "ANALYTICS_ENABLED", False)

    response = _client(db).get("/analytics/catalog")

    assert response.status_code == 404
    assert response.json()["detail"] == "Analytics is not enabled for this profile"


def test_aggregate_endpoints_reject_legacy_or_missing_metric_contract(
    monkeypatch,
) -> None:
    monkeypatch.setattr(config, "ANALYTICS_ENABLED", True)
    client = _client(FakeDb())

    legacy = client.post(
        "/analytics/query",
        json={
            "semantic_view": "survey_responses",
            "metrics": ["response_count"],
        },
    )
    missing = client.post(
        "/analytics/query",
        json={"semantic_view": "survey_responses"},
    )
    filter_options = client.post(
        "/analytics/filter-options",
        json={
            "semantic_view": "survey_responses",
            "member": "store_format",
            "metrics": ["response_count"],
        },
    )

    assert legacy.status_code == 422
    assert missing.status_code == 422
    assert filter_options.status_code == 422


def test_query_compiles_catalog_members_and_returns_chart_ready_rows(monkeypatch) -> None:
    db = FakeDb()
    cube = FakeCube(
        {
            "data": [
                {
                    "survey_responses.store_name": "Central",
                    "survey_responses.survey_count": "2",
                }
            ],
            "lastRefreshTime": "2026-08-25T12:00:00Z",
        }
    )
    monkeypatch.setattr(config, "ANALYTICS_ENABLED", True)
    monkeypatch.setattr(config, "DEPLOYMENT_PROFILE", "wtchk_cls")
    monkeypatch.setattr(analytics, "_catalog_from_version", lambda version, role: _catalog())
    monkeypatch.setattr(analytics, "_active_model_version", lambda db: None)
    monkeypatch.setattr(analytics, "_cube_client", lambda: cube)

    response = _client(db).post(
        "/analytics/query",
        json={
            "dimensions": ["store_name"],
            "metric": "survey",
            "aggregation": "count",
            "limit": 100,
        },
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store, private"
    body = response.json()
    assert body["model_version"] == 0
    assert body["semantic_view"] == "survey_responses"
    assert body["rows"] == [{"store_name": "Central", "value": 2}]
    assert body["row_count"] == 1
    assert body["schema"] == {
        "dimensions": [
            {
                "field": "store_name",
                "label": "Store",
                "type": "string",
                "key": "store_name",
                "group_role": "primary",
            }
        ],
        "time_dimension": None,
        "metric": {
            "target": "survey",
            "aggregation": "count",
            "label": "Responses",
            "type": "number",
            "key": "value",
        },
    }
    assert body["freshness_time"] == "2026-08-25T12:00:00Z"
    assert cube.calls[0][0] == {
        "dimensions": ["survey_responses.store_name"],
        "measures": ["survey_responses.survey_count"],
        "limit": 100,
    }
    assert cube.calls[0][1]["profile_id"] == "wtchk_cls"
    assert db.added[0].semantic_view == "survey_responses"
    assert db.added[0].request["semantic_view"] == "survey_responses"
    assert db.commits >= 2


def test_query_rejects_catalog_drift_during_cube_execution(monkeypatch) -> None:
    db = FakeDb()
    original = SimpleNamespace(id=17, catalog_version=7, catalog_snapshot={})
    replacement = SimpleNamespace(id=18, catalog_version=8, catalog_snapshot={})
    versions = iter((original, replacement))
    cube = FakeCube(
        {
            "data": [{"survey_responses.survey_count": "2"}],
            "lastRefreshTime": "2026-08-25T12:00:00Z",
        }
    )
    monkeypatch.setattr(config, "ANALYTICS_ENABLED", True)
    monkeypatch.setattr(config, "DEPLOYMENT_PROFILE", "wtchk_cls")
    monkeypatch.setattr(analytics, "_active_model_version", lambda db: next(versions))
    monkeypatch.setattr(analytics, "_catalog_from_version", lambda version, role: _catalog())
    monkeypatch.setattr(analytics, "_cube_client", lambda: cube)

    response = _client(db).post(
        "/analytics/query",
        json={
            "semantic_view": "survey_responses",
            "metric": "survey",
            "aggregation": "count",
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "analytics_catalog_changed",
        "message": "Analytics catalog changed; retry the query",
    }
    assert db.added[-1].status == "failed"
    assert db.added[-1].model_version_id == original.id


def test_response_sentiment_query_with_hong_kong_timezone_reaches_cube(
    monkeypatch,
) -> None:
    db = FakeDb()
    cube = FakeCube(
        {
            "data": [
                {
                    "survey_responses.topic_sentiment": "POSITIVE",
                    "survey_responses.survey_count": "6",
                }
            ]
        }
    )
    monkeypatch.setattr(config, "ANALYTICS_ENABLED", True)
    monkeypatch.setattr(config, "DEPLOYMENT_PROFILE", "wtchk_cls")
    monkeypatch.setattr(
        analytics,
        "_catalog",
        lambda db, role: analytics._catalog_from_records([], []),
    )
    monkeypatch.setattr(analytics, "_active_model_version", lambda db: None)
    monkeypatch.setattr(analytics, "_cube_client", lambda: cube)

    response = _client(db).post(
        "/analytics/query",
        json={
            "semantic_view": "survey_responses",
            "dimensions": ["topic_sentiment"],
            "metric": "survey",
            "aggregation": "count",
            "timezone": "Asia/Hong_Kong",
            "limit": 100,
        },
    )

    assert response.status_code == 200
    assert response.json()["rows"] == [
        {"topic_sentiment": "POSITIVE", "value": 6}
    ]
    assert cube.calls[0][0] == {
        "dimensions": ["survey_responses.topic_sentiment"],
        "measures": ["survey_responses.survey_count"],
        "timezone": "Asia/Hong_Kong",
        "limit": 100,
    }


def test_cube_unavailable_is_isolated_to_an_analytics_503(monkeypatch) -> None:
    db = FakeDb()
    monkeypatch.setattr(config, "ANALYTICS_ENABLED", True)
    monkeypatch.setattr(config, "DEPLOYMENT_PROFILE", "wtchk_cls")
    monkeypatch.setattr(analytics, "_catalog", lambda db, role: _catalog())
    monkeypatch.setattr(analytics, "_active_model_version", lambda db: None)
    monkeypatch.setattr(
        analytics,
        "_cube_client",
        lambda: FakeCube(error=CubeUnavailableError("down")),
    )

    response = _client(db).post(
        "/analytics/query",
        json={
            "semantic_view": "survey_responses",
            "metric": "survey",
            "aggregation": "count",
        },
    )

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "analytics_unavailable"


@pytest.mark.parametrize(
    ("error", "code", "message"),
    [
        (
            CubeQueryPendingError("still running"),
            "analytics_query_pending",
            "The analytics query is still processing; retry shortly",
        ),
        (
            CubePreAggregationNotReadyError("not ready"),
            "analytics_warming",
            "Analytics data is preparing; retry shortly",
        ),
    ],
)
def test_cube_warming_states_are_retryable_analytics_503s(
    monkeypatch, error, code: str, message: str
) -> None:
    db = FakeDb()
    monkeypatch.setattr(config, "ANALYTICS_ENABLED", True)
    monkeypatch.setattr(config, "DEPLOYMENT_PROFILE", "wtchk_cls")
    monkeypatch.setattr(analytics, "_catalog", lambda db, role: _catalog())
    monkeypatch.setattr(analytics, "_active_model_version", lambda db: None)
    monkeypatch.setattr(analytics, "_cube_client", lambda: FakeCube(error=error))

    response = _client(db).post(
        "/analytics/query",
        json={
            "semantic_view": "survey_responses",
            "metric": "survey",
            "aggregation": "count",
        },
    )

    assert response.status_code == 503
    assert response.headers["retry-after"] == "2"
    assert response.json()["detail"] == {"code": code, "message": message}
    assert len(db.added) == 1


def test_cube_query_errors_do_not_expose_generated_sql(monkeypatch) -> None:
    db = FakeDb()
    monkeypatch.setattr(config, "ANALYTICS_ENABLED", True)
    monkeypatch.setattr(config, "DEPLOYMENT_PROFILE", "wtchk_cls")
    monkeypatch.setattr(analytics, "_catalog", lambda db, role: _catalog())
    monkeypatch.setattr(analytics, "_active_model_version", lambda db: None)
    monkeypatch.setattr(
        analytics,
        "_cube_client",
        lambda: FakeCube(
            error=CubeQueryError("SELECT secret_header FROM analytics_survey_facts")
        ),
    )

    response = _client(db).post(
        "/analytics/query",
        json={
            "semantic_view": "survey_responses",
            "metric": "survey",
            "aggregation": "count",
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"] == {
        "code": "analytics_query_rejected",
        "message": "The analytics query could not be executed",
    }
    assert "secret_header" not in response.text


def test_internal_catalog_requires_signed_profile_request_and_uses_camel_case(
    monkeypatch,
) -> None:
    db = FakeDb()
    secret = "metadata-secret"
    timestamp = 1_777_000_000
    snapshot = {
        "cubeCatalog": {
            "profile": "wtchk_cls",
            "catalogVersion": 7,
            "fields": [
                {
                    "slug": "raw_score",
                    "label": "Score",
                    "semanticView": "survey_responses",
                    "dataType": "number",
                    "sourceKind": "raw_json",
                    "sourceKey": "Score",
                    "visibility": "viewer",
                }
            ],
            "metrics": [
                {
                    "slug": "average_score",
                    "label": "Average score",
                    "semanticView": "survey_responses",
                    "operation": "average",
                    "sourceField": "raw_score",
                    "weightField": None,
                    "confidenceLevel": None,
                    "parameters": {},
                    "visibility": "viewer",
                }
            ],
        },
        "charts": [],
    }
    version = SimpleNamespace(catalog_version=7, catalog_snapshot=snapshot)
    # Cube compiles during the shadow phase before viewer/admin analytics is
    # enabled, so the private HMAC endpoint must remain available.
    monkeypatch.setattr(config, "ANALYTICS_ENABLED", False)
    monkeypatch.setattr(config, "DEPLOYMENT_PROFILE", "wtchk_cls")
    monkeypatch.setattr(config, "ANALYTICS_INTERNAL_METADATA_SECRET", secret)
    monkeypatch.setattr(analytics, "_active_model_version", lambda db: version)
    monkeypatch.setattr(analytics, "_metadata_now", lambda: timestamp)
    signature = sign_metadata_request(secret, "wtchk_cls", timestamp)

    response = _client(db).get(
        "/internal/analytics/catalog",
        headers={
            "X-Analytics-Profile": "wtchk_cls",
            "X-Analytics-Timestamp": str(timestamp),
            "X-Analytics-Signature": signature,
        },
    )

    assert response.status_code == 200
    assert response.json() == {**snapshot["cubeCatalog"], "rollups": []}
    assert set(response.json()) == {
        "profile",
        "catalogVersion",
        "fields",
        "metrics",
        "rollups",
    }


def test_admin_routes_require_only_the_static_bearer(monkeypatch) -> None:
    token = base64.b64encode(b"0123456789abcdef0123456789abcdef").decode()
    monkeypatch.setattr(security, "API_BEARER_TOKEN", token)

    app = FastAPI()

    @app.get("/admin/example")
    async def admin_example(_: object = Depends(require_admin)) -> dict[str, bool]:
        return {"ok": True}

    client = TestClient(app)

    response = client.get(
        "/admin/example",
        headers={
            "Authorization": f"Bearer {token}",
            # Legacy actor headers are ignored; bearer is the whole contract.
            "X-CLS-Actor-Role": "viewer",
            "X-CLS-Actor-Profile": "another-profile",
        },
    )
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_chart_rollups_are_stable_structured_and_mark_non_additive() -> None:
    charts = [
        {
            "id": 42,
            "status": "published",
            "semantic_view": "survey_responses",
            "definition": {
                "dimensions": ["store_name"],
                "metric": "score",
                "aggregation": "median",
                "time_dimension": "reported_at",
                "time_granularity": "month",
            },
        }
    ]
    metrics = [
        {
            "slug": "median_score",
            "semanticView": "survey_responses",
            "sourceField": "score",
            "operation": "median",
            "queryTarget": "score",
            "publicAggregation": "median",
        }
    ]

    first = analytics._chart_rollups(charts, metrics)

    assert first == analytics._chart_rollups(charts, metrics)
    assert first == [
        {
            "name": first[0]["name"],
            "semanticView": "survey_responses",
            "measures": ["median_score"],
            "dimensions": ["store_name"],
            "timeDimension": "reported_at",
            "granularity": "month",
            "partitionGranularity": "year",
            "nonAdditive": True,
        }
    ]
    assert first[0]["name"].startswith("chart_42_")

    untimed = analytics._chart_rollups(
        [
            {
                "id": 43,
                "status": "published",
                "semantic_view": "survey_responses",
                "definition": {
                    "dimensions": ["store_name"],
                    "metric": "survey",
                    "aggregation": "count",
                },
            }
        ],
        [],
    )
    assert untimed[0]["timeDimension"] is None
    assert "partitionGranularity" not in untimed[0]


def test_catalog_versions_begin_at_one_and_increment_monotonically() -> None:
    assert analytics._next_catalog_version(None) == 1
    assert analytics._next_catalog_version(1) == 2
    assert analytics._next_catalog_version(9) == 10


def test_catalog_publication_enforces_cube_compiler_payload_limit(monkeypatch) -> None:
    monkeypatch.setattr(analytics, "_MAX_CUBE_CATALOG_BYTES", 32)

    with pytest.raises(analytics.AnalyticsValidationError, match="size limit"):
        analytics._validate_cube_catalog_size(
            {"profile": "wtchk_cls", "catalogVersion": 1, "fields": []}
        )


def test_export_admission_lock_is_stable_and_profile_scoped() -> None:
    assert analytics._export_admission_lock_key(
        "wtchk_cls"
    ) == analytics._export_admission_lock_key("wtchk_cls")
    assert analytics._export_admission_lock_key(
        "wtchk_cls"
    ) != analytics._export_admission_lock_key("wtchk_ecls")


def test_projected_record_capacity_returns_a_bounded_429(monkeypatch) -> None:
    class FullSemaphore:
        def acquire(self, blocking: bool = False) -> bool:
            assert blocking is False
            return False

    monkeypatch.setattr(config, "ANALYTICS_ENABLED", True)
    monkeypatch.setattr(analytics, "_PROJECTED_RECORDS_SEMAPHORE", FullSemaphore())

    response = _client(FakeDb()).post(
        "/analytics/records/query",
        json={
            "resource": "surveys",
            "representation": "projected",
            "fields": ["id"],
        },
    )

    assert response.status_code == 429
    assert response.headers["retry-after"] == "2"
    assert response.json()["detail"]["code"] == "analytics_records_capacity"


def test_projected_record_database_failure_returns_record_oriented_503(monkeypatch) -> None:
    class Semaphore:
        def acquire(self, blocking: bool = False) -> bool:
            return True

        def release(self) -> None:
            pass

    db = FakeDb()
    monkeypatch.setattr(config, "ANALYTICS_ENABLED", True)
    monkeypatch.setattr(analytics, "_PROJECTED_RECORDS_SEMAPHORE", Semaphore())
    monkeypatch.setattr(analytics, "_active_model_version", lambda db: None)
    monkeypatch.setattr(analytics, "_catalog_from_version", lambda version, role: object())
    monkeypatch.setattr(
        analytics, "_raw_field_sources_from_version", lambda version, role: {}
    )
    monkeypatch.setattr(
        analytics,
        "execute_projected_records",
        lambda *args, **kwargs: (_ for _ in ()).throw(SQLAlchemyError("failed")),
    )

    response = _client(db).post(
        "/analytics/records/query",
        json={"resource": "surveys", "representation": "projected"},
    )

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "analytics_records_unavailable"
    assert db.rollbacks == 1


def test_projected_record_query_rejects_catalog_race(monkeypatch) -> None:
    versions = iter(
        [
            SimpleNamespace(id=1, catalog_version=4),
            SimpleNamespace(id=2, catalog_version=5),
        ]
    )
    monkeypatch.setattr(config, "ANALYTICS_ENABLED", True)
    monkeypatch.setattr(analytics, "_active_model_version", lambda db: next(versions))
    monkeypatch.setattr(analytics, "_catalog_from_version", lambda version, role: object())
    monkeypatch.setattr(
        analytics, "_raw_field_sources_from_version", lambda version, role: {}
    )
    monkeypatch.setattr(
        analytics,
        "execute_projected_records",
        lambda *args, **kwargs: {"items": [], "next_cursor": None, "has_more": False},
    )

    response = _client(FakeDb()).post(
        "/analytics/records/query",
        json={"resource": "surveys", "representation": "projected"},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "analytics_catalog_changed"


def test_projected_record_raw_sources_are_pinned_to_the_active_snapshot() -> None:
    snapshot = {
        "cubeCatalog": {
            "profile": "wtchk_cls",
            "catalogVersion": 3,
            "fields": [
                {
                    "slug": "public_score",
                    "semanticView": "survey_responses",
                    "dataType": "number",
                    "sourceKind": "raw_json",
                    "sourceKey": "Published Score Header",
                    "visibility": "viewer",
                },
                {
                    "slug": "private_note",
                    "semanticView": "survey_responses",
                    "dataType": "string",
                    "sourceKind": "raw_json",
                    "sourceKey": "Private Note Header",
                    "visibility": "admin",
                },
            ],
            "metrics": [],
        }
    }
    version = SimpleNamespace(catalog_snapshot=snapshot)

    assert analytics._raw_field_sources_from_version(version, "viewer") == {
        "public_score": ("Published Score Header", analytics.FieldType.NUMBER)
    }
    assert analytics._raw_field_sources_from_version(version, "admin") == {
        "public_score": ("Published Score Header", analytics.FieldType.NUMBER),
        "private_note": ("Private Note Header", analytics.FieldType.STRING),
    }


def test_promoted_response_fields_project_to_each_assignment_grain(monkeypatch) -> None:
    field = SimpleNamespace(
        id=11,
        slug="raw_score",
        label="Score",
        semantic_view="survey_responses",
        data_type="number",
        visibility="viewer",
        source_kind="raw_json",
        source_key="Score",
    )
    catalog = analytics._catalog_from_records([field], [])

    # Every grain projects facts.*, so a promoted response field reaches all of
    # them, including the assignment-combination grain.
    assert {
        item.semantic_view
        for item in catalog.fields
        if item.slug == "raw_score"
    } == {
        "survey_responses",
        "survey_topics",
        "survey_departments",
        "survey_keywords",
        "survey_assignments",
    }
    monkeypatch.setattr(config, "DEPLOYMENT_PROFILE", "wtchk_cls")
    payload = analytics._cube_catalog_payload([field], [], 4)
    assert {
        item["semanticView"] for item in payload["fields"]
    } == {
        "survey_responses",
        "survey_topics",
        "survey_departments",
        "survey_keywords",
        "survey_assignments",
    }


def test_temporal_min_metric_returns_temporal_column_metadata() -> None:
    catalog = SemanticCatalog(
        fields=[
            CatalogField(
                slug="visited_at",
                label="Visited at",
                semantic_view="survey_responses",
                data_type=FieldType.DATE,
            )
        ],
        metrics=[
            CatalogMetric(
                slug="first_visit",
                label="First visit",
                semantic_view="survey_responses",
                aggregation=Aggregation.MIN,
                source_field="visited_at",
                query_target="visited_at",
                public_aggregation="min",
                entity="visited_at",
            )
        ],
    )
    query = analytics.QuerySpec(
        semantic_view="survey_responses",
        metric="visited_at",
        aggregation="min",
    )

    schema = analytics._query_schema(query, catalog, "viewer")
    assert schema["metric"] == {
        "target": "visited_at",
        "aggregation": "min",
        "label": "First visit",
        "type": "date",
        "key": "value",
    }


def test_admin_can_define_governed_metrics_over_fixed_core_members(monkeypatch) -> None:
    metric = SimpleNamespace(
        slug="average_latitude",
        label="Average latitude",
        semantic_view="survey_responses",
        operation="average",
        field_id=None,
        source_member="latitude",
        weight_field_id=None,
        weight_member=None,
        confidence_level=None,
        definition={},
        visibility="viewer",
    )
    catalog = analytics._catalog_from_records([], [metric])

    analytics._validate_metric_record(metric, [], catalog)
    assert catalog.metric(
        "average_latitude", "survey_responses"
    ).source_field == "latitude"
    monkeypatch.setattr(config, "DEPLOYMENT_PROFILE", "wtchk_cls")
    assert analytics._cube_catalog_payload([], [metric], 1)["metrics"][0][
        "sourceField"
    ] == "latitude"


def test_published_chart_query_preserves_requested_limit_without_pie_shaping() -> None:
    chart = {
        "chart_type": "pie",
        "semantic_view": "survey_responses",
        "definition": {
            "dimensions": ["store_name"],
            "metric": "survey",
            "aggregation": "count",
            "limit": 1_000,
        },
    }
    query, cube_query = analytics._chart_query(chart, None, _catalog(), "viewer")

    assert query.limit == 1_000
    assert query.order == ()
    assert cube_query["limit"] == 1_000
    assert "order" not in cube_query


def test_published_chart_type_is_not_copied_into_the_query() -> None:
    temporal_catalog = SemanticCatalog(
        fields=[
            CatalogField(
                slug="reported_at",
                label="Reported at",
                semantic_view="survey_responses",
                data_type=FieldType.DATE,
            )
        ],
        metrics=[
            CatalogMetric(
                slug="latest_response",
                label="Latest response",
                semantic_view="survey_responses",
                aggregation=Aggregation.MAX,
                source_field="reported_at",
                query_target="reported_at",
                public_aggregation="max",
                entity="reported_at",
            )
        ],
    )
    chart = {
        "chart_type": "bar",
        "semantic_view": "survey_responses",
        "definition": {
            "dimensions": ["reported_at"],
            "metric": "reported_at",
            "aggregation": "max",
        },
    }

    query, _ = analytics._chart_query(chart, None, temporal_catalog, "viewer")

    assert "chart_type" not in query.model_dump()


def test_filtered_metric_parameters_are_typed_and_declarative() -> None:
    source = SimpleNamespace(data_type="number")

    analytics._validate_metric_filter(
        Aggregation.FILTERED_RATE,
        {"filter": {"operator": "greater_than_or_equal", "value": 4}},
        source,
    )

    try:
        analytics._validate_metric_filter(
            Aggregation.FILTERED_RATE,
            {"filter": {"operator": "greater_than_or_equal", "value": "4"}},
            source,
        )
    except ValueError as error:
        assert "number values" in str(error)
    else:
        raise AssertionError("string values must not be accepted for numeric filters")
