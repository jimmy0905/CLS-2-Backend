from __future__ import annotations

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
    FilterSpec,
    OrderSpec,
    QuerySpec,
    SemanticCatalog,
    allowed_aggregations,
    compile_cube_query,
    escape_spreadsheet_formula,
    validate_chart_definition,
    validate_identifier,
    validate_metric,
    validate_query,
)


@pytest.fixture
def catalog() -> SemanticCatalog:
    return SemanticCatalog(
        fields=[
            CatalogField(
                slug="store_name",
                label="Store",
                semantic_view="survey_responses",
                data_type=FieldType.STRING,
            ),
            CatalogField(
                slug="reported_at",
                label="Reported at",
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
                slug="sample_weight",
                label="Sample weight",
                semantic_view="survey_responses",
                data_type=FieldType.NUMBER,
                visibility="admin",
            ),
            CatalogField(
                slug="topic",
                label="Topic",
                semantic_view="survey_topics",
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
            CatalogMetric(
                slug="average_score",
                label="Average score",
                semantic_view="survey_responses",
                aggregation=Aggregation.AVERAGE,
                source_field="score",
            ),
            CatalogMetric(
                slug="weighted_score",
                label="Weighted score",
                semantic_view="survey_responses",
                aggregation=Aggregation.WEIGHTED_AVERAGE,
                source_field="score",
                weight_field="sample_weight",
            ),
            CatalogMetric(
                slug="admin_score",
                label="Admin score",
                semantic_view="survey_responses",
                aggregation=Aggregation.SUM,
                source_field="score",
                visibility="admin",
            ),
        ],
    )


@pytest.mark.parametrize(
    "value",
    [
        "store-name",
        "StoreName",
        "store.name",
        "1store",
        "store__name",
        "store_name_",
        "store;drop_table",
        "a" * 64,
    ],
)
def test_identifier_validation_rejects_unsafe_or_ambiguous_names(value: str) -> None:
    with pytest.raises(AnalyticsValidationError, match="identifier"):
        validate_identifier(value)


def test_identifier_validation_accepts_lowercase_snake_case() -> None:
    assert validate_identifier("survey_responses") == "survey_responses"
    assert validate_identifier("score2") == "score2"


def test_query_model_enforces_contract_limits() -> None:
    with pytest.raises(ValidationError):
        QuerySpec(
            semantic_view="survey_responses",
            dimensions=["a", "b", "c", "d"],
            metrics=[],
        )
    with pytest.raises(ValidationError):
        QuerySpec(
            semantic_view="survey_responses",
            dimensions=[],
            metrics=["a", "b", "c", "d", "e", "f"],
        )
    with pytest.raises(ValidationError):
        QuerySpec(
            semantic_view="survey_responses",
            dimensions=[],
            metrics=[],
            filters=[FilterSpec(member="score", operator="equals", value=1)] * 21,
        )
    with pytest.raises(ValidationError):
        QuerySpec(semantic_view="survey_responses", limit=1001)


def test_query_validation_blocks_cross_view_fanout(catalog: SemanticCatalog) -> None:
    query = QuerySpec(
        semantic_view="survey_responses",
        dimensions=["topic"],
        metrics=["response_count"],
    )

    with pytest.raises(AnalyticsValidationError, match="semantic view"):
        validate_query(query, catalog)


def test_query_validation_blocks_unpublished_and_role_hidden_members(
    catalog: SemanticCatalog,
) -> None:
    query = QuerySpec(
        semantic_view="survey_responses",
        dimensions=[],
        metrics=["admin_score"],
    )

    with pytest.raises(AnalyticsValidationError, match="visible"):
        validate_query(query, catalog, role="viewer")
    assert validate_query(query, catalog, role="admin") == query


def test_published_metric_may_safely_aggregate_an_admin_only_dependency(
    catalog: SemanticCatalog,
) -> None:
    query = QuerySpec(
        semantic_view="survey_responses",
        metrics=["weighted_score"],
    )

    assert validate_query(query, catalog, role="viewer") == query


def test_query_validation_checks_filter_value_types(catalog: SemanticCatalog) -> None:
    query = QuerySpec(
        semantic_view="survey_responses",
        dimensions=["store_name"],
        metrics=["response_count"],
        filters=[FilterSpec(member="score", operator="greater_than", value="1")],
    )

    with pytest.raises(AnalyticsValidationError, match="numeric"):
        validate_query(query, catalog)


def test_compiler_emits_only_catalog_owned_cube_members(catalog: SemanticCatalog) -> None:
    query = QuerySpec(
        semantic_view="survey_responses",
        dimensions=["store_name"],
        metrics=["average_score"],
        filters=[FilterSpec(member="score", operator="greater_than_or_equal", value=3)],
        time_dimension="reported_at",
        time_range=["2026-01-01", "2026-01-31"],
        time_granularity="day",
        order=[OrderSpec(member="average_score", direction="desc")],
        limit=100,
    )

    compiled = compile_cube_query(query, catalog)

    assert compiled == {
        "dimensions": ["survey_responses.store_name"],
        "measures": ["survey_responses.average_score"],
        "filters": [
            {
                "member": "survey_responses.score",
                "operator": "gte",
                "values": ["3"],
            }
        ],
        "timeDimensions": [
            {
                "dimension": "survey_responses.reported_at",
                "dateRange": ["2026-01-01", "2026-01-31"],
                "granularity": "day",
            }
        ],
        "order": {"survey_responses.average_score": "desc"},
        "limit": 100,
    }


def test_aggregation_rules_and_metric_weight_contract(catalog: SemanticCatalog) -> None:
    assert Aggregation.SUM in allowed_aggregations(FieldType.NUMBER)
    assert Aggregation.MEDIAN not in allowed_aggregations(FieldType.STRING)
    assert Aggregation.MIN in allowed_aggregations(FieldType.DATE)
    assert Aggregation.SUM not in allowed_aggregations(FieldType.DATE)

    weighted = catalog.metric("weighted_score")
    assert validate_metric(weighted, catalog) == weighted

    invalid = CatalogMetric(
        slug="weighted_median",
        label="Weighted median",
        semantic_view="survey_responses",
        aggregation=Aggregation.MEDIAN,
        source_field="score",
        weight_field="sample_weight",
    )
    with pytest.raises(AnalyticsValidationError, match="does not support weights"):
        validate_metric(invalid, catalog)


def test_query_time_range_is_typed_and_ordered() -> None:
    QuerySpec(
        semantic_view="survey_responses",
        dimensions=["reported_at"],
        time_dimension="reported_at",
        time_range=("2026-08-01", "2026-08-31T23:59:59Z"),
    )
    with pytest.raises(ValidationError, match="ISO-8601"):
        QuerySpec(
            semantic_view="survey_responses",
            dimensions=["reported_at"],
            time_dimension="reported_at",
            time_range=("last week", "today"),
        )
    with pytest.raises(ValidationError, match="start"):
        QuerySpec(
            semantic_view="survey_responses",
            dimensions=["reported_at"],
            time_dimension="reported_at",
            time_range=("2026-09-01", "2026-08-01"),
        )
    with pytest.raises(ValidationError, match="raw dimension"):
        QuerySpec(
            semantic_view="survey_responses",
            dimensions=["reported_at"],
            time_dimension="reported_at",
            time_granularity="day",
        )


@pytest.mark.parametrize(
    "chart_type,dimensions,metrics",
    [
        ("kpi", [], ["response_count"]),
        ("pie", ["store_name"], ["response_count"]),
        ("scatter", ["store_name"], ["average_score", "response_count"]),
        ("heatmap", ["store_name", "reported_at"], ["average_score"]),
        (
            "store_map",
            ["store_key", "store_name", "latitude", "longitude"],
            ["response_count"],
        ),
    ],
)
def test_chart_compatibility_accepts_supported_shapes(
    chart_type: str, dimensions: list[str], metrics: list[str]
) -> None:
    validate_chart_definition(chart_type, dimensions, metrics)


@pytest.mark.parametrize(
    "chart_type,dimensions,metrics",
    [
        ("pie", ["store_name", "reported_at"], ["response_count"]),
        ("scatter", [], ["average_score"]),
        ("heatmap", ["store_name"], ["average_score"]),
        ("store_map", ["store_name", "latitude", "longitude"], ["response_count"]),
        ("kpi", ["store_name"], ["response_count"]),
    ],
)
def test_chart_compatibility_rejects_invalid_shapes(
    chart_type: str, dimensions: list[str], metrics: list[str]
) -> None:
    with pytest.raises(AnalyticsValidationError, match="requires"):
        validate_chart_definition(chart_type, dimensions, metrics)


def test_numeric_chart_families_reject_temporal_extrema() -> None:
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

    validate_chart_definition(
        "kpi",
        [],
        ["latest_response"],
        temporal_catalog,
        semantic_view="survey_responses",
    )
    with pytest.raises(AnalyticsValidationError, match="numeric metrics"):
        validate_chart_definition(
            "bar",
            ["reported_at"],
            ["latest_response"],
            temporal_catalog,
            semantic_view="survey_responses",
        )


@pytest.mark.parametrize(
    "value,expected",
    [
        ("=SUM(A1:A2)", "'=SUM(A1:A2)"),
        ("+cmd|' /C calc'!A0", "'+cmd|' /C calc'!A0"),
        ("-2+3", "'-2+3"),
        ("@IMPORTXML('x')", "'@IMPORTXML('x')"),
        ("\t=1+1", "'\t=1+1"),
        ("\r=1+1", "'\r=1+1"),
        ("\n=1+1", "'\n=1+1"),
        ("ordinary text", "ordinary text"),
        (42, 42),
        (None, None),
    ],
)
def test_spreadsheet_formula_escaping(value: object, expected: object) -> None:
    assert escape_spreadsheet_formula(value) == expected
