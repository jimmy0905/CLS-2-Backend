from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pytest
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from features.analytics.model.semantic import (
    Aggregation,
    AnalyticsValidationError,
    CatalogField,
    CatalogMetric,
    FieldType,
    OrderSpec,
    QuerySpec,
    SemanticCatalog,
    compile_cube_query,
    metric_targets,
    validate_query,
)
from features.analytics.service.results import format_query_result


MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "migrations"
    / "versions"
    / "2026_08_28_0013_migrate_goal_first_analytics.py"
)


def _load_single_metric_migration():
    spec = importlib.util.spec_from_file_location(
        "migration_0013_goal_first_contract", MIGRATION_PATH
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
                time_dimension=True,
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
                slug="survey_count",
                label="Survey Count",
                semantic_view="survey_responses",
                aggregation=Aggregation.COUNT,
                source_field="id",
                query_target="survey",
                public_aggregation="count",
                entity="survey",
            ),
            CatalogMetric(
                slug="average_score",
                label="Average Score",
                semantic_view="survey_responses",
                aggregation=Aggregation.AVERAGE,
                source_field="score",
                query_target="score",
                public_aggregation="average",
                entity="score",
            ),
            CatalogMetric(
                slug="latest_reported_at",
                label="Latest Reported At",
                semantic_view="survey_responses",
                aggregation=Aggregation.MAX,
                source_field="reported_at",
                query_target="reported_at",
                public_aggregation="max",
                entity="reported_at",
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
                query_target="secret_score",
                public_aggregation="average",
                entity="secret_score",
            ),
        ],
    )


def test_query_requires_one_logical_metric_and_one_simple_aggregation() -> None:
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
    with pytest.raises(AnalyticsValidationError, match="not published"):
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
                query_target="score",
                public_aggregation="average",
                entity="score",
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


def test_catalog_metric_targets_exclude_complex_hidden_and_ambiguous_pairs(
    catalog: SemanticCatalog,
) -> None:
    targets = metric_targets(catalog, "survey_responses", role="viewer")
    assert {
        target.metric: [item.method for item in target.aggregations]
        for target in targets
    } == {
        "reported_at": [Aggregation.MAX],
        "score": [Aggregation.AVERAGE],
        "survey": [Aggregation.COUNT],
    }


@pytest.mark.parametrize(
    "legacy_semantic_view",
    [
        None,
        "survey_responses",
        "survey_topics",
        "survey_departments",
        "survey_keywords",
    ],
)
def test_survey_count_query_ignores_legacy_semantic_view(
    legacy_semantic_view: str | None,
) -> None:
    from features.analytics.endpoints.analytics import _catalog_from_records

    public_catalog = _catalog_from_records([], [])
    payload = {
        "metric": "survey",
        "aggregation": "count",
    }
    if legacy_semantic_view is not None:
        payload["semantic_view"] = legacy_semantic_view
    compiled = compile_cube_query(
        QuerySpec(**payload),
        public_catalog,
    )
    assert compiled["measures"] == ["survey_responses.survey_count"]


@pytest.mark.parametrize("raw_metric", ["id", "assignment_id", "survey_id"])
def test_raw_identifiers_are_not_public_metric_targets(raw_metric: str) -> None:
    from features.analytics.endpoints.analytics import _catalog_from_records

    with pytest.raises(AnalyticsValidationError, match="not published"):
        validate_query(
            QuerySpec(
                semantic_view="survey_keywords",
                metric=raw_metric,
                aggregation="count",
            ),
            _catalog_from_records([], []),
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("chart_type", "bar"),
        ("series_limit", 10),
        ("fill_empty", True),
    ],
)
def test_query_rejects_renderer_metadata(field: str, value: object) -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        QuerySpec.model_validate(
            {
                "metric": "survey",
                "aggregation": "count",
                field: value,
            }
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
    from features.analytics.endpoints.analytics import _catalog_from_records

    migration = _load_single_metric_migration()
    public_catalog = _catalog_from_records([], [])
    public_options = {
        view: {
            (target.metric, aggregation.method.value)
            for target in metric_targets(public_catalog, view)
            for aggregation in target.aggregations
        }
        for view in public_catalog.views
    }

    for chart in migration._DEFAULT_CHARTS:
        definition = chart["definition"]
        option = (definition["metric"], definition["aggregation"])
        assert option in public_options[chart["semantic_view"]], chart["slug"]
        assert validate_query(
            QuerySpec(
                semantic_view=chart["semantic_view"],
                **definition,
            ),
            public_catalog,
        )
