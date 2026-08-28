from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pytest
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utils.analytics import (
    Aggregation,
    AnalyticsValidationError,
    CatalogField,
    CatalogMetric,
    FieldType,
    OrderSpec,
    QuerySpec,
    SemanticCatalog,
    compile_cube_query,
    metric_options,
    validate_chart_definition,
    validate_query,
)
from utils.analytics_results import format_query_result


MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "migrations"
    / "versions"
    / "2026_08_28_0012_migrate_single_metric_analytics_charts.py"
)


def _load_single_metric_migration():
    spec = importlib.util.spec_from_file_location(
        "migration_0012_single_metric_contract", MIGRATION_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def catalog() -> SemanticCatalog:
    return SemanticCatalog(
        fields=[
            CatalogField(
                slug="id",
                label="Response ID",
                semantic_view="survey_responses",
                data_type=FieldType.NUMBER,
            ),
            CatalogField(
                slug="store_format",
                label="Store Format",
                semantic_view="survey_responses",
                data_type=FieldType.STRING,
            ),
            CatalogField(
                slug="region",
                label="Region",
                semantic_view="survey_responses",
                data_type=FieldType.STRING,
            ),
            CatalogField(
                slug="channel",
                label="Channel",
                semantic_view="survey_responses",
                data_type=FieldType.STRING,
            ),
            CatalogField(
                slug="reported_at",
                label="Reported At",
                semantic_view="survey_responses",
                data_type=FieldType.DATE,
            ),
            CatalogField(
                slug="score",
                label="Score",
                semantic_view="survey_responses",
                data_type=FieldType.NUMBER,
            ),
            CatalogField(
                slug="secret_score",
                label="Secret Score",
                semantic_view="survey_responses",
                data_type=FieldType.NUMBER,
                visibility="admin",
            ),
        ],
        metrics=[
            CatalogMetric(
                slug="response_count",
                label="Response Count",
                semantic_view="survey_responses",
                aggregation=Aggregation.COUNT,
                source_field="id",
            ),
            CatalogMetric(
                slug="average_score",
                label="Average Score",
                semantic_view="survey_responses",
                aggregation=Aggregation.AVERAGE,
                source_field="score",
            ),
            CatalogMetric(
                slug="latest_reported_at",
                label="Latest Reported At",
                semantic_view="survey_responses",
                aggregation=Aggregation.MAX,
                source_field="reported_at",
            ),
            CatalogMetric(
                slug="score_variance",
                label="Score Variance",
                semantic_view="survey_responses",
                aggregation=Aggregation.VARIANCE_SAMPLE,
                source_field="score",
            ),
            CatalogMetric(
                slug="secret_average",
                label="Secret Average",
                semantic_view="survey_responses",
                aggregation=Aggregation.AVERAGE,
                source_field="secret_score",
                visibility="admin",
            ),
        ],
    )


def test_query_requires_one_raw_metric_and_one_simple_aggregation() -> None:
    query = QuerySpec(
        semantic_view="survey_responses",
        metric="score",
        aggregation="average",
    )
    assert query.metric == "score"
    assert query.aggregation == Aggregation.AVERAGE

    for payload in (
        {"semantic_view": "survey_responses"},
        {
            "semantic_view": "survey_responses",
            "metric": "score",
            "aggregation": "avg",
        },
        {
            "semantic_view": "survey_responses",
            "metric": "score",
            "aggregation": "variance_sample",
        },
        {
            "semantic_view": "survey_responses",
            "metric": "score",
            "aggregation": "average",
            "metrics": ["average_score"],
        },
    ):
        with pytest.raises(ValidationError):
            QuerySpec.model_validate(payload)


def test_query_resolves_governed_pair_and_orders_value(
    catalog: SemanticCatalog,
) -> None:
    query = QuerySpec(
        semantic_view="survey_responses",
        dimensions=["store_format"],
        metric="score",
        aggregation="average",
        order=[OrderSpec(member="value", direction="desc")],
    )

    assert validate_query(query, catalog) == query
    assert compile_cube_query(query, catalog) == {
        "dimensions": ["survey_responses.store_format"],
        "measures": ["survey_responses.average_score"],
        "order": {"survey_responses.average_score": "desc"},
        "limit": 1000,
    }


def test_query_rejects_missing_ambiguous_or_wrong_type_pairs(
    catalog: SemanticCatalog,
) -> None:
    with pytest.raises(AnalyticsValidationError, match="not published"):
        validate_query(
            QuerySpec(
                semantic_view="survey_responses",
                metric="score",
                aggregation="sum",
            ),
            catalog,
        )
    with pytest.raises(AnalyticsValidationError, match="not valid for string"):
        validate_query(
            QuerySpec(
                semantic_view="survey_responses",
                metric="store_format",
                aggregation="average",
            ),
            catalog,
        )

    ambiguous = SemanticCatalog(
        fields=catalog.fields,
        metrics=(
            *catalog.metrics,
            CatalogMetric(
                slug="mean_score_duplicate",
                label="Duplicate",
                semantic_view="survey_responses",
                aggregation=Aggregation.AVERAGE,
                source_field="score",
            ),
        ),
    )
    with pytest.raises(AnalyticsValidationError, match="ambiguous"):
        validate_query(
            QuerySpec(
                semantic_view="survey_responses",
                metric="score",
                aggregation="average",
            ),
            ambiguous,
        )


def test_catalog_metric_options_exclude_complex_hidden_and_ambiguous_pairs(
    catalog: SemanticCatalog,
) -> None:
    options = metric_options(catalog, "survey_responses", role="viewer")
    assert [(item.field, item.aggregation) for item in options] == [
        ("id", Aggregation.COUNT),
        ("reported_at", Aggregation.MAX),
        ("score", Aggregation.AVERAGE),
    ]


@pytest.mark.parametrize(
    "chart_type,dimensions,time_dimension,time_granularity",
    [
        ("kpi", [], None, None),
        ("table", [], None, None),
        ("bar", ["store_format"], None, None),
        ("column", ["store_format"], None, None),
        ("pie", ["store_format"], None, None),
        ("donut", ["store_format"], None, None),
        ("stacked_bar", ["store_format", "region"], None, None),
        ("heatmap", ["store_format", "region"], None, None),
        ("table", ["store_format", "region", "channel"], None, None),
        ("line", [], "reported_at", "day"),
        ("area", ["store_format"], "reported_at", "month"),
        ("table", ["store_format", "region"], "reported_at", "day"),
    ],
)
def test_chart_compatibility_matrix_accepts_supported_shapes(
    catalog: SemanticCatalog,
    chart_type: str,
    dimensions: list[str],
    time_dimension: str | None,
    time_granularity: str | None,
) -> None:
    validate_chart_definition(
        chart_type,
        dimensions,
        "score",
        "average",
        catalog,
        semantic_view="survey_responses",
        time_dimension=time_dimension,
        time_granularity=time_granularity,
    )


@pytest.mark.parametrize(
    "chart_type,dimensions,time_dimension,time_granularity",
    [
        ("scatter", ["store_format"], None, None),
        ("store_map", ["store_format"], None, None),
        ("line", [], None, None),
        ("line", [], "reported_at", None),
        ("bar", ["store_format"], "reported_at", "day"),
        ("stacked_bar", ["store_format", "region", "channel"], None, None),
        ("line", ["store_format", "region"], "reported_at", "day"),
    ],
)
def test_chart_compatibility_matrix_rejects_unsupported_shapes(
    catalog: SemanticCatalog,
    chart_type: str,
    dimensions: list[str],
    time_dimension: str | None,
    time_granularity: str | None,
) -> None:
    with pytest.raises(AnalyticsValidationError):
        validate_chart_definition(
            chart_type,
            dimensions,
            "score",
            "average",
            catalog,
            semantic_view="survey_responses",
            time_dimension=time_dimension,
            time_granularity=time_granularity,
        )


def test_non_numeric_metric_is_limited_to_kpi_and_table(
    catalog: SemanticCatalog,
) -> None:
    validate_chart_definition(
        "kpi",
        [],
        "reported_at",
        "max",
        catalog,
        semantic_view="survey_responses",
    )
    with pytest.raises(AnalyticsValidationError, match="numeric"):
        validate_chart_definition(
            "bar",
            ["store_format"],
            "reported_at",
            "max",
            catalog,
            semantic_view="survey_responses",
        )


def test_result_is_flat_and_renames_the_resolved_measure_to_value(
    catalog: SemanticCatalog,
) -> None:
    query = QuerySpec(
        semantic_view="survey_responses",
        dimensions=["store_format"],
        metric="score",
        aggregation="average",
        time_dimension="reported_at",
        time_granularity="day",
        timezone="Asia/Hong_Kong",
    )
    result = format_query_result(
        {
            "data": [
                {
                    "survey_responses.store_format": "Mall",
                    "survey_responses.reported_at.day": "2026-08-27T00:00:00.000",
                    "survey_responses.average_score": "4.2",
                }
            ],
            "lastRefreshTime": "2026-08-28T05:00:00Z",
        },
        query,
        catalog,
    )
    assert result == {
        "rows": [
            {
                "store_format": "Mall",
                "reported_at": "2026-08-27T00:00:00+08:00",
                "value": 4.2,
            }
        ],
        "warnings": [],
        "freshness_time": "2026-08-28T05:00:00Z",
    }


def test_migration_default_charts_resolve_against_public_core_catalog() -> None:
    from routers.analytics import _catalog_from_records

    migration = _load_single_metric_migration()
    public_catalog = _catalog_from_records([], [])
    public_options = {
        view: {
            (option.field, option.aggregation.value)
            for option in metric_options(public_catalog, view)
        }
        for view in public_catalog.views
    }

    for chart in migration._DEFAULT_CHARTS:
        definition = chart["definition"]
        option = (definition["metric"], definition["aggregation"])
        assert option in public_options[chart["semantic_view"]], chart["slug"]
        validate_chart_definition(
            chart["chart_type"],
            definition["dimensions"],
            definition["metric"],
            definition["aggregation"],
            public_catalog,
            semantic_view=chart["semantic_view"],
            time_dimension=definition.get("time_dimension"),
            time_granularity=definition.get("time_granularity"),
        )
