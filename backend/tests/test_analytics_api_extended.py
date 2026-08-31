from __future__ import annotations

import os
from pathlib import Path
import sys

import pytest
from pydantic import ValidationError

os.environ.setdefault("DATABASE_USER", "test")
os.environ.setdefault("DATABASE_PASSWORD", "test")
os.environ.setdefault("DATABASE_HOST", "localhost")
os.environ.setdefault("DATABASE_PORT", "5432")
os.environ.setdefault("DATABASE_NAME", "test")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from features.analytics.endpoints.analytics import ExportInput, router
from features.analytics.model.semantic import QuerySpec
from features.analytics.repository.drilldown import DrilldownSpec


def test_router_exposes_drilldown_and_export_lifecycle() -> None:
    routes = {
        (route.path, method)
        for route in router.routes
        for method in getattr(route, "methods", set())
    }

    assert ("/analytics/drilldown", "POST") in routes
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
    drilldown = DrilldownSpec(fields=["id"])

    assert ExportInput(export_format="csv", query=query).query == query
    assert ExportInput(export_format="xlsx", drilldown=drilldown).drilldown == drilldown
    with pytest.raises(ValidationError, match="exactly one"):
        ExportInput(export_format="csv")
    with pytest.raises(ValidationError, match="exactly one"):
        ExportInput(export_format="csv", query=query, drilldown=drilldown)


def test_metric_input_cannot_mix_core_and_promoted_sources() -> None:
    from features.analytics.endpoints.analytics import MetricInput

    with pytest.raises(ValidationError, match="either field_id or source_member"):
        MetricInput(
            slug="bad_metric",
            label="Bad metric",
            field_id=1,
            source_member="cls",
            operation="average",
        )
