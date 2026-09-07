from __future__ import annotations

import os
from pathlib import Path
import sys

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

os.environ.setdefault("DATABASE_USER", "test")
os.environ.setdefault("DATABASE_PASSWORD", "test")
os.environ.setdefault("DATABASE_HOST", "localhost")
os.environ.setdefault("DATABASE_PORT", "5432")
os.environ.setdefault("DATABASE_NAME", "test")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import create_app
from features.analytics.endpoints.analytics import ExportInput, RecordQueryInput, router
from features.analytics.model.semantic import QuerySpec


def _operations(application) -> set[tuple[str, str]]:
    return {
        (route.path, method)
        for route in application.routes
        for method in getattr(route, "methods", set())
    }


def test_router_exposes_records_and_export_lifecycle_without_drilldown() -> None:
    routes = _operations(router)

    assert ("/analytics/records/query", "POST") in routes
    assert ("/analytics/drilldown", "POST") not in routes
    assert ("/analytics/builder/measures", "GET") not in routes
    assert ("/analytics/exports", "POST") in routes
    assert ("/analytics/exports/{job_id}", "GET") in routes
    assert ("/analytics/exports/{job_id}/download", "GET") in routes


def test_export_requires_exactly_one_governed_request_kind() -> None:
    query = QuerySpec(
        semantic_view="survey_responses",
        dimensions=["store_name"],
        metric="id",
        aggregation="count",
    )
    record_query = RecordQueryInput(resource="surveys")

    assert ExportInput(export_format="csv", query=query).query == query
    assert (
        ExportInput(export_format="xlsx", record_query=record_query).record_query
        == record_query
    )
    with pytest.raises(ValidationError, match="exactly one"):
        ExportInput(export_format="csv")
    with pytest.raises(ValidationError, match="exactly one"):
        ExportInput(
            export_format="csv", query=query, record_query=record_query
        )
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        ExportInput.model_validate(
            {
                "export_format": "csv",
                "drilldown": {"fields": ["id"]},
            }
        )


def test_removed_legacy_operations_and_dormant_admin_handlers_are_not_mounted() -> None:
    routes = _operations(create_app())
    removed_legacy = {
        ("/dashboard/department-distribution", "GET"),
        ("/dashboard/keyword-analysis", "GET"),
        ("/dashboard/topic-distribution", "GET"),
        ("/dashboard/sentiment-distribution", "GET"),
        ("/dashboard/store-distribution", "GET"),
        ("/dashboard/channel-and-delivery-service-distribution", "GET"),
        ("/dashboard/topic-sentiment-score", "GET"),
        ("/dashboard/last-updated-date", "GET"),
        ("/dashboard/data-coverage", "GET"),
        ("/dashboard/store-column-sentiment-distribution", "GET"),
        ("/surveys", "GET"),
        ("/surveys/download", "GET"),
        ("/surveys/{survey_id}", "GET"),
        ("/channels/", "GET"),
        ("/channels/{channel_id}", "GET"),
        ("/delivery_services/", "GET"),
        ("/delivery_services/{delivery_service_id}", "GET"),
        ("/topics/", "GET"),
        ("/topics/{topic_id}", "GET"),
    }
    assert routes.isdisjoint(removed_legacy)

    dormant_admin = {
        ("/admin/analytics/candidates", "GET"),
        ("/admin/analytics/fields", "GET"),
        ("/admin/analytics/fields", "POST"),
        ("/admin/analytics/fields/{field_id}", "GET"),
        ("/admin/analytics/fields/{field_id}", "PUT"),
        ("/admin/analytics/fields/{field_id}/promote", "POST"),
        ("/admin/analytics/fields/{field_id}/validate", "POST"),
        ("/admin/analytics/fields/{field_id}/publish", "POST"),
        ("/admin/analytics/fields/{field_id}/archive", "POST"),
        ("/admin/analytics/metrics", "GET"),
        ("/admin/analytics/metrics", "POST"),
        ("/admin/analytics/metrics/{metric_id}", "GET"),
        ("/admin/analytics/metrics/{metric_id}", "PUT"),
        ("/admin/analytics/metrics/{metric_id}/validate", "POST"),
        ("/admin/analytics/metrics/{metric_id}/publish", "POST"),
        ("/admin/analytics/metrics/{metric_id}/archive", "POST"),
        ("/admin/analytics/charts/{chart_id}/validate", "POST"),
        ("/admin/analytics/catalog/versions", "GET"),
        ("/admin/analytics/catalog/versions/{version_id}", "GET"),
        ("/admin/analytics/catalog/publish", "POST"),
    }
    assert routes.isdisjoint(dormant_admin)


def test_removed_legacy_reads_return_404_instead_of_redirect_or_405() -> None:
    client = TestClient(create_app())
    paths = {
        "/dashboard/department-distribution",
        "/dashboard/keyword-analysis",
        "/dashboard/topic-distribution",
        "/dashboard/sentiment-distribution",
        "/dashboard/store-distribution",
        "/dashboard/channel-and-delivery-service-distribution",
        "/dashboard/topic-sentiment-score",
        "/dashboard/last-updated-date",
        "/dashboard/data-coverage",
        "/dashboard/store-column-sentiment-distribution",
        "/surveys",
        "/surveys/download",
        "/surveys/1",
        "/channels/",
        "/channels/1",
        "/delivery_services/",
        "/delivery_services/1",
        "/topics/",
        "/topics/1",
    }

    for path in paths:
        response = client.get(path, follow_redirects=False)
        assert response.status_code == 404, path


def test_preserved_writes_and_selected_legacy_reads_remain_mounted() -> None:
    routes = _operations(create_app())

    for operation in {
        ("/surveys/", "POST"),
        ("/surveys/{survey_id}", "PUT"),
        ("/surveys/{survey_id}", "DELETE"),
        ("/channels/", "POST"),
        ("/delivery_services/", "POST"),
        ("/topics/", "POST"),
        ("/stores/", "GET"),
        ("/stores/{store_key}", "GET"),
        ("/stores/export", "GET"),
        ("/departments/", "GET"),
        ("/departments/{department_id}", "GET"),
    }:
        assert operation in routes
