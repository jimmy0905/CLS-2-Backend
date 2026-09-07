"""Analytics builder contract: measure first, then breakdowns and aggregation.

The two worked examples in these tests are the requirements this contract was
built for:

1. every keyword's MIXED topic sentiment, grouped by department;
2. every store's CLS at a one week interval.
"""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "sqlite://")

import core.config as config
from features.analytics.endpoints import analytics
from features.analytics.model.semantic import (
    QuerySpec,
    compile_cube_query,
    validate_query,
)
from infrastructure.database.session import get_db
from features.identity.service.security import get_current_actor, require_admin


class FakeDb:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.commits = 0

    def add(self, value: object) -> None:
        self.added.append(value)

    def commit(self) -> None:
        self.commits += 1


class FakeCube:
    def __init__(self, result: dict | None = None) -> None:
        self.result = result or {}
        self.calls: list[tuple[dict, dict]] = []

    async def execute(self, query: dict, **kwargs: object) -> dict:
        self.calls.append((query, kwargs))
        return self.result


@pytest.fixture(name="catalog")
def catalog_fixture():
    return analytics._catalog_from_records([], [])


@pytest.fixture(name="client")
def client_fixture(monkeypatch):
    monkeypatch.setattr(config, "ANALYTICS_ENABLED", True)
    monkeypatch.setattr(analytics, "_active_model_version", lambda db: None)
    app = FastAPI()
    app.include_router(analytics.router)
    user = SimpleNamespace(id="user-1", role="user")
    app.dependency_overrides[get_db] = lambda: FakeDb()
    app.dependency_overrides[get_current_actor] = lambda: user
    app.dependency_overrides[require_admin] = lambda: user
    return TestClient(app)


def _resolved(payload: dict, catalog) -> tuple[str | None, QuerySpec | None, list[str]]:
    selection = analytics.BuilderQueryInput.model_validate(payload)
    semantic_view, warnings = analytics._resolve_builder_view(
        selection, catalog, "viewer"
    )
    if semantic_view is None:
        return None, None, warnings
    query = validate_query(
        analytics._builder_query(selection, semantic_view), catalog, "viewer"
    )
    return semantic_view, query, warnings


EXAMPLE_KEYWORD_BY_DEPARTMENT = {
    "measure": {"field": "topic_sentiment", "enum_value": "MIXED"},
    "aggregation": "count",
    "breakdown": "keyword",
    "series": {"dimension": "department"},
}
EXAMPLE_STORE_CLS_WEEKLY = {
    "measure": {"field": "cls"},
    "aggregation": "average",
    "breakdown": "store_name_english",
    "series": {"time": {"field": "reported_at", "interval": "week"}},
}
EXAMPLE_CLS_BY_DELIVERY_SERVICE_AND_CHANNEL = {
    "measure": {"field": "cls"},
    "aggregation": "average",
    "breakdown": "delivery_service_name",
    "series": {"dimension": "channel_name"},
}


def test_enum_dimensions_are_measurable_one_value_at_a_time(catalog) -> None:
    measures = {item.key: item for item in analytics._builder_measures(catalog, "viewer")}

    mixed = measures["topic_sentiment:MIXED"]
    assert mixed.field == "topic_sentiment"
    assert mixed.enum_value == "MIXED"
    assert mixed.label == "Topic Sentiment is MIXED"
    # Sentiment is a string, so counting is the only honest aggregation.
    assert [option.method.value for option in mixed.aggregations] == ["count"]
    assert mixed.supports_cross_assignment is True

    # Every declared value becomes its own target, and nothing else does.
    assert {
        key for key in measures if key.startswith("topic_sentiment:")
    } == {
        "topic_sentiment:POSITIVE",
        "topic_sentiment:NEGATIVE",
        "topic_sentiment:NEUTRAL",
        "topic_sentiment:MIXED",
    }
    assert "comment" not in measures
    assert "store_name_english" not in measures


def test_a_response_average_cannot_cross_assignment_families(catalog) -> None:
    cls = next(
        item
        for item in analytics._builder_measures(catalog, "viewer")
        if item.key == "cls"
    )
    assert cls.supports_cross_assignment is False

    semantic_view, query, warnings = _resolved(
        {
            "measure": {"field": "cls"},
            "aggregation": "average",
            "breakdown": "keyword",
            "series": {"dimension": "department"},
        },
        catalog,
    )
    assert semantic_view is None and query is None
    assert any("repeats a response" in warning for warning in warnings)


def test_routing_prefers_the_narrowest_grain_that_answers_the_selection(
    catalog,
) -> None:
    # No assignment dimension: stay on the response grain.
    assert _resolved(
        {"measure": {"field": "survey"}, "aggregation": "count", "breakdown": "region"},
        catalog,
    )[0] == "survey_responses"

    # One assignment family: use its own grain and avoid any fan-out.
    assert _resolved(
        {"measure": {"field": "survey"}, "aggregation": "count", "breakdown": "keyword"},
        catalog,
    )[0] == "survey_keywords"
    assert _resolved(
        {"measure": {"field": "survey"}, "aggregation": "count", "breakdown": "topic"},
        catalog,
    )[0] == "survey_topics"

    # Response-level enum counts remain correct at one assignment-family grain,
    # which avoids the larger cross-assignment view.
    assert _resolved(
        {
            "measure": {"field": "topic_sentiment", "enum_value": "MIXED"},
            "aggregation": "count",
            "breakdown": "keyword",
        },
        catalog,
    )[0] == "survey_keywords"

    # Two families cannot coexist anywhere else.
    assert _resolved(
        {
            "measure": {"field": "survey"},
            "aggregation": "count",
            "breakdown": "keyword",
            "series": {"dimension": "department"},
        },
        catalog,
    )[0] == "survey_assignments"


def test_raw_query_infers_its_view_and_ignores_legacy_view_hint(catalog) -> None:
    payload = {
        "dimensions": ("keyword",),
        "metric": "topic_sentiment_mixed",
        "aggregation": "count",
    }

    inferred = validate_query(QuerySpec(**payload), catalog, "viewer")
    legacy_hint = validate_query(
        QuerySpec(semantic_view="survey_responses", **payload), catalog, "viewer"
    )

    assert inferred.semantic_view == "survey_keywords"
    assert legacy_hint == inferred
    assert compile_cube_query(inferred, catalog, "viewer")["measures"] == [
        "survey_keywords.topic_sentiment_mixed_survey_count"
    ]

    filter_scoped = validate_query(
        QuerySpec(
            metric="survey",
            aggregation="count",
            filters=(
                {"member": "keyword", "operator": "equals", "value": "staff"},
            ),
        ),
        catalog,
        "viewer",
    )
    assert filter_scoped.semantic_view == "survey_keywords"


def test_example_one_crosses_keyword_with_department_on_deduplicated_counts(
    catalog,
) -> None:
    semantic_view, query, warnings = _resolved(EXAMPLE_KEYWORD_BY_DEPARTMENT, catalog)

    assert semantic_view == "survey_assignments"
    assert warnings == []
    assert query is not None
    assert query.dimensions == ("keyword", "department")
    assert query.time_dimension is None

    compiled = compile_cube_query(query, catalog, "viewer")
    assert compiled["dimensions"] == [
        "survey_assignments.keyword",
        "survey_assignments.department",
    ]
    # Counting combination rows would multiply by the assignment fan-out.
    assert compiled["measures"] == [
        "survey_assignments.topic_sentiment_mixed_survey_count"
    ]

def test_example_two_queries_stores_by_week(catalog) -> None:
    semantic_view, query, warnings = _resolved(EXAMPLE_STORE_CLS_WEEKLY, catalog)

    assert semantic_view == "survey_responses"
    assert warnings == []
    assert query is not None
    assert query.time_granularity == "week"

    compiled = compile_cube_query(query, catalog, "viewer")
    assert compiled["measures"] == ["survey_responses.cls_average"]
    assert compiled["timeDimensions"] == [
        {
            "dimension": "survey_responses.reported_at",
            "granularity": "week",
        }
    ]


def test_two_builder_dimensions_are_marked_primary_and_secondary(catalog) -> None:
    semantic_view, query, warnings = _resolved(
        EXAMPLE_CLS_BY_DELIVERY_SERVICE_AND_CHANNEL, catalog
    )

    assert semantic_view == "survey_responses"
    assert warnings == []
    assert query is not None
    assert query.dimensions == ("delivery_service_name", "channel_name")
    assert compile_cube_query(query, catalog, "viewer")["measures"] == [
        "survey_responses.cls_average"
    ]
    schema = analytics._query_schema(query, catalog, "viewer")
    assert schema["dimensions"] == [
        {
            "field": "delivery_service_name",
                "label": "Delivery Service Name",
            "type": "string",
            "key": "delivery_service_name",
            "group_role": "primary",
        },
        {
            "field": "channel_name",
                "label": "Channel Name",
            "type": "string",
            "key": "channel_name",
            "group_role": "secondary",
        },
    ]

def test_a_series_is_either_a_dimension_or_a_time_interval() -> None:
    with pytest.raises(ValueError, match="one dimension or one time interval"):
        analytics.BuilderSeriesInput.model_validate(
            {"dimension": "department", "time": {"field": "reported_at", "interval": "week"}}
        )
    with pytest.raises(ValueError, match="one dimension or one time interval"):
        analytics.BuilderSeriesInput.model_validate({})


def test_an_unknown_enum_value_is_rejected(catalog) -> None:
    with pytest.raises(Exception, match="not a value of"):
        analytics._measure_target(
            analytics.BuilderMeasureInput(field="topic_sentiment", enum_value="ANGRY")
        )


def test_builder_options_bootstrap_lists_expanded_enum_targets(client) -> None:
    response = client.post("/analytics/builder/options", json={})

    assert response.status_code == 200
    body = response.json()
    keys = {item["key"] for item in body["available_measures"]}
    assert "topic_sentiment:MIXED" in keys
    assert "cls" in keys


def test_builder_options_resolves_in_any_selection_order(client) -> None:
    # Nothing chosen yet: every measure is offered and no grain is fixed.
    empty = client.post("/analytics/builder/options", json={}).json()
    assert empty["semantic_view"] is None
    assert empty["selection_complete"] is False
    assert empty["available_measures"]

    # Breakdowns first, aggregation last, still resolves.
    breakdown_first = client.post(
        "/analytics/builder/options",
        json={
            "breakdown": "keyword",
            "series": {"dimension": "department"},
            "measure": {"field": "topic_sentiment", "enum_value": "MIXED"},
        },
    ).json()
    assert breakdown_first["semantic_view"] == "survey_assignments"

    complete = client.post(
        "/analytics/builder/options", json=EXAMPLE_KEYWORD_BY_DEPARTMENT
    ).json()
    assert complete["semantic_view"] == "survey_assignments"
    assert complete["selection_complete"] is True
    assert complete["query"]["dimensions"] == ["keyword", "department"]
    assert "week" in complete["available_intervals"]

    # The chosen breakdown is not offered again as the series dimension.
    series_slugs = {item["slug"] for item in complete["available_series_dimensions"]}
    assert "keyword" not in series_slugs
    breakdown_slugs = {item["slug"] for item in complete["available_breakdowns"]}
    assert {"id", "comment", "latitude"} <= breakdown_slugs


def test_builder_options_hides_a_dimension_that_would_distort_the_measure(
    client,
) -> None:
    body = client.post(
        "/analytics/builder/options",
        json={
            "measure": {"field": "keyword_assignment"},
            "aggregation": "count",
            "breakdown": "keyword",
        },
    ).json()

    assert body["semantic_view"] == "survey_keywords"
    series_slugs = {item["slug"] for item in body["available_series_dimensions"]}
    # Adding a second family would move the query to the combination grain,
    # which counts responses rather than keyword assignments and so cannot
    # report this measure.
    assert "department" not in series_slugs
    assert "topic" not in series_slugs
    assert "region" in series_slugs

    # A measure that survives the fan-out keeps both families on offer.
    cross_safe = client.post(
        "/analytics/builder/options",
        json={
            "measure": {"field": "topic_sentiment", "enum_value": "MIXED"},
            "aggregation": "count",
            "breakdown": "keyword",
        },
    ).json()
    cross_slugs = {item["slug"] for item in cross_safe["available_series_dimensions"]}
    assert {"department", "topic"} <= cross_slugs


def test_builder_explains_a_measure_missing_from_the_required_grain(client) -> None:
    # Averaging CLS is published only at the response grain, because an
    # assignment grain would weight each response by its assignment count.
    body = client.post(
        "/analytics/builder/options",
        json={
            "measure": {"field": "cls"},
            "aggregation": "average",
            "breakdown": "keyword",
        },
    ).json()

    assert body["semantic_view"] is None
    assert body["selection_complete"] is False
    assert any(
        "not published at the survey_keywords grain" in warning
        for warning in body["warnings"]
    )


def test_builder_options_reports_enum_values_for_a_dimension(client) -> None:
    body = client.post(
        "/analytics/builder/options",
        json={"measure": {"field": "survey"}, "aggregation": "count"},
    ).json()

    sentiment = next(
        item
        for item in body["available_breakdowns"]
        if item["slug"] == "topic_sentiment"
    )
    assert set(sentiment["enum_values"]) == {
        "POSITIVE",
        "NEGATIVE",
        "NEUTRAL",
        "MIXED",
    }
    region = next(
        item for item in body["available_breakdowns"] if item["slug"] == "region"
    )
    assert region["enum_values"] == []


def test_builder_query_runs_example_one_without_renderer_layout(
    monkeypatch, client
) -> None:
    cube = FakeCube(
        {
            "data": [
                {
                    "survey_assignments.keyword": "staff",
                    "survey_assignments.department": "Sales Ops",
                    "survey_assignments.topic_sentiment_mixed_survey_count": "526",
                },
                {
                    "survey_assignments.keyword": "staff",
                    "survey_assignments.department": "HR L&D",
                    "survey_assignments.topic_sentiment_mixed_survey_count": "498",
                },
            ],
            "lastRefreshTime": "2026-08-28T12:00:00Z",
        }
    )
    monkeypatch.setattr(config, "DEPLOYMENT_PROFILE", "wtchk_cls")
    monkeypatch.setattr(analytics, "_cube_client", lambda: cube)

    response = client.post(
        "/analytics/builder/query",
        json={**EXAMPLE_KEYWORD_BY_DEPARTMENT, "limit": 100},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["semantic_view"] == "survey_assignments"
    assert body["rows"] == [
        {"keyword": "staff", "department": "Sales Ops", "value": 526},
        {"keyword": "staff", "department": "HR L&D", "value": 498},
    ]
    assert [
        dimension["group_role"] for dimension in body["schema"]["dimensions"]
    ] == ["primary", "secondary"]
    assert "layout" not in body["schema"]
    assert cube.calls[0][0]["measures"] == [
        "survey_assignments.topic_sentiment_mixed_survey_count"
    ]


def test_builder_query_refuses_a_selection_no_grain_can_answer(
    monkeypatch, client
) -> None:
    monkeypatch.setattr(analytics, "_cube_client", lambda: FakeCube())

    response = client.post(
        "/analytics/builder/query",
        json={
            "measure": {"field": "cls"},
            "aggregation": "average",
            "breakdown": "keyword",
            "series": {"dimension": "department"},
        },
    )

    assert response.status_code == 422
    assert "repeats a response" in response.json()["detail"]


def test_builder_query_requires_a_measure_and_an_aggregation(client) -> None:
    response = client.post(
        "/analytics/builder/query", json={"breakdown": "region"}
    )
    assert response.status_code == 422


@pytest.mark.parametrize(
    "field,value",
    [
        ("chart_type", "bar"),
        ("series_limit", 10),
        ("fill_empty", True),
    ],
)
def test_builder_rejects_renderer_metadata(client, field: str, value: object) -> None:
    options = client.post("/analytics/builder/options", json={field: value})
    assert options.status_code == 422

    query = client.post(
        "/analytics/builder/query",
        json={
            "measure": {"field": "survey"},
            "aggregation": "count",
            field: value,
        },
    )
    assert query.status_code == 422
