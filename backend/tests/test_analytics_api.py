from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


os.environ.setdefault("DATABASE_USER", "test")
os.environ.setdefault("DATABASE_PASSWORD", "test")
os.environ.setdefault("DATABASE_HOST", "localhost")
os.environ.setdefault("DATABASE_PORT", "5432")
os.environ.setdefault("DATABASE_NAME", "test")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config
from routers import analytics
from utils.analytics import (
    Aggregation,
    AnalyticsValidationError,
    CatalogField,
    CatalogMetric,
    FieldType,
    SemanticCatalog,
)
from utils.analytics_cube import CubeQueryError, CubeUnavailableError
from utils.analytics_metadata_auth import sign_metadata_request
from utils.database import get_db
from utils.security import get_current_user, require_admin


class FakeDb:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.commits = 0

    def add(self, value: object) -> None:
        self.added.append(value)

    def commit(self) -> None:
        self.commits += 1


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
                slug="store_name",
                label="Store",
                semantic_view="survey_responses",
                data_type=FieldType.STRING,
            ),
        ],
        metrics=[
            CatalogMetric(
                slug="response_count",
                label="Responses",
                semantic_view="survey_responses",
                aggregation=Aggregation.COUNT,
            ),
        ],
    )


def _client(db: FakeDb, role: str = "user") -> TestClient:
    app = FastAPI()
    app.include_router(analytics.router)
    user = SimpleNamespace(id="user-1", role=role)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[require_admin] = lambda: user
    return TestClient(app)


def test_feature_gate_is_evaluated_dynamically(monkeypatch) -> None:
    db = FakeDb()
    monkeypatch.setattr(config, "ANALYTICS_ENABLED", False)

    response = _client(db).get("/analytics/catalog")

    assert response.status_code == 404
    assert response.json()["detail"] == "Analytics is not enabled for this profile"


def test_query_compiles_catalog_members_and_returns_chart_ready_rows(monkeypatch) -> None:
    db = FakeDb()
    cube = FakeCube(
        {
            "data": [
                {
                    "survey_responses.store_name": "Central",
                    "survey_responses.response_count": "2",
                }
            ],
            "lastRefreshTime": "2026-08-25T12:00:00Z",
        }
    )
    monkeypatch.setattr(config, "ANALYTICS_ENABLED", True)
    monkeypatch.setattr(config, "DEPLOYMENT_PROFILE", "wtchk_cls")
    monkeypatch.setattr(analytics, "_catalog", lambda db, role: _catalog())
    monkeypatch.setattr(analytics, "_active_model_version", lambda db: None)
    monkeypatch.setattr(analytics, "_cube_client", lambda: cube)

    response = _client(db).post(
        "/analytics/query",
        json={
            "semantic_view": "survey_responses",
            "dimensions": ["store_name"],
            "metrics": ["response_count"],
            "limit": 100,
        },
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store, private"
    body = response.json()
    assert body["model_version"] == 0
    assert body["rows"] == [{"store_name": "Central", "response_count": 2}]
    assert body["columns"] == [
        {"name": "store_name", "label": "Store", "type": "string", "kind": "dimension"},
        {"name": "response_count", "label": "Responses", "type": "number", "kind": "metric"},
    ]
    assert body["confidence"] == []
    assert body["freshness_time"] == "2026-08-25T12:00:00Z"
    assert cube.calls[0][0] == {
        "dimensions": ["survey_responses.store_name"],
        "measures": ["survey_responses.response_count"],
        "limit": 100,
    }
    assert cube.calls[0][1]["profile_id"] == "wtchk_cls"
    assert db.commits >= 2


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
            "metrics": ["response_count"],
        },
    )

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "analytics_unavailable"


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
        json={"semantic_view": "survey_responses", "metrics": ["response_count"]},
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


def test_admin_routes_require_an_administrator(monkeypatch) -> None:
    db = FakeDb()
    monkeypatch.setattr(config, "ANALYTICS_ENABLED", True)
    app = FastAPI()
    app.include_router(analytics.router)
    viewer = SimpleNamespace(id="viewer-1", role="user")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: viewer

    response = TestClient(app).get("/admin/analytics/candidates")

    assert response.status_code == 403


def test_chart_rollups_are_stable_structured_and_mark_non_additive() -> None:
    charts = [
        {
            "id": 42,
            "status": "published",
            "semantic_view": "survey_responses",
            "definition": {
                "dimensions": ["store_name"],
                "metrics": ["median_score"],
                "time_dimension": "reported_at",
                "time_granularity": "month",
            },
        }
    ]
    metrics = [{"slug": "median_score", "operation": "median"}]

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
                    "metrics": ["response_count"],
                },
            }
        ],
        [{"slug": "response_count", "operation": "count"}],
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


def test_drilldown_capacity_returns_a_bounded_429(monkeypatch) -> None:
    class FullSemaphore:
        def acquire(self, blocking: bool = False) -> bool:
            assert blocking is False
            return False

    monkeypatch.setattr(config, "ANALYTICS_ENABLED", True)
    monkeypatch.setattr(analytics, "_DRILLDOWN_SEMAPHORE", FullSemaphore())

    response = _client(FakeDb()).post(
        "/analytics/drilldown",
        json={"semantic_view": "survey_responses", "fields": ["id"]},
    )

    assert response.status_code == 429
    assert response.headers["retry-after"] == "2"


def test_drilldown_raw_sources_are_pinned_to_the_active_snapshot(monkeypatch) -> None:
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
    monkeypatch.setattr(analytics, "_active_model_version", lambda db: version)

    assert analytics._raw_field_sources(object(), "viewer") == {
        "public_score": ("Published Score Header", analytics.FieldType.NUMBER)
    }
    assert analytics._raw_field_sources(object(), "admin") == {
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

    assert {
        item.semantic_view
        for item in catalog.fields
        if item.slug == "raw_score"
    } == {
        "survey_responses",
        "survey_topics",
        "survey_departments",
        "survey_keywords",
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
            )
        ],
    )
    query = analytics.QuerySpec(
        semantic_view="survey_responses", metrics=["first_visit"]
    )

    assert analytics._column_metadata(query, catalog) == [
        {
            "name": "first_visit",
            "label": "First visit",
            "type": "date",
            "kind": "metric",
        }
    ]


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


def test_field_archive_dependency_scan_covers_chart_filters_time_and_order() -> None:
    definition = {
        "dimensions": ["store_name"],
        "time_dimension": "reported_at",
        "filters": [{"member": "sentiment", "operator": "equals", "value": "ok"}],
        "order": [{"member": "raw_score", "direction": "desc"}],
    }

    assert analytics._chart_dimension_dependencies(definition) == {
        "store_name",
        "reported_at",
        "sentiment",
        "raw_score",
    }


def test_pie_contract_forces_top_twelve_and_uses_governed_other_value() -> None:
    chart = {
        "chart_type": "pie",
        "semantic_view": "survey_responses",
        "definition": {
            "dimensions": ["store_name"],
            "metrics": ["response_count"],
            "limit": 1_000,
        },
    }
    query, cube_query = analytics._chart_query(chart, None, _catalog(), "viewer")

    assert query.limit == 13
    assert query.order[0].member == "response_count"
    assert query.order[0].direction == "desc"
    assert cube_query["limit"] == 13
    response = {
        "rows": [
            {"store_name": f"Store {index}", "response_count": 20 - index}
            for index in range(12)
        ]
    }
    shaped = analytics._shape_chart_rows(
        chart,
        response,
        other_value=7,
        other_response={
            "confidence": [{"metric": "response_count", "row_index": 0}],
            "warnings": [{"code": "tail_warning", "row_index": 0}],
        },
    )
    assert len(shaped["rows"]) == 13
    assert shaped["rows"][-1] == {"store_name": "Other", "response_count": 7}
    assert shaped["confidence"][-1]["row_index"] == 12
    assert shaped["confidence"][-1]["category"] == "Other"
    assert shaped["warnings"][-1]["row_index"] == 12

    zero_tail = analytics._shape_chart_rows(chart, response, other_value=0)
    assert zero_tail["rows"][-1] == {
        "store_name": "Other",
        "response_count": 0,
    }


def test_chart_runtime_rejects_temporal_metric_in_numeric_plot() -> None:
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
            )
        ],
    )
    chart = {
        "chart_type": "bar",
        "semantic_view": "survey_responses",
        "definition": {
            "dimensions": ["reported_at"],
            "metrics": ["latest_response"],
        },
    }

    with pytest.raises(AnalyticsValidationError, match="numeric metrics"):
        analytics._chart_query(chart, None, temporal_catalog, "viewer")


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
