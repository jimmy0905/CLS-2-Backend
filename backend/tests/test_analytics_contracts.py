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
    validate_identifier,
    validate_metric,
    validate_query,
)


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
                source_field="id",
            ),
            CatalogMetric(
                slug="average_score",
                label="Average score",
                semantic_view="survey_responses",
                aggregation=Aggregation.AVERAGE,
                source_field="score",
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


def test_query_model_enforces_breaking_contract_and_limits() -> None:
    with pytest.raises(ValidationError):
        QuerySpec(
            semantic_view="survey_responses",
            dimensions=["a", "b", "c", "d"],
            metric="id",
            aggregation="count",
        )
    with pytest.raises(ValidationError):
        QuerySpec.model_validate(
            {
                "semantic_view": "survey_responses",
                "metrics": ["response_count"],
            }
        )
    with pytest.raises(ValidationError):
        QuerySpec(
            semantic_view="survey_responses",
            metric="id",
            aggregation="count",
            filters=[FilterSpec(member="score", operator="equals", value=1)] * 21,
        )
    with pytest.raises(ValidationError):
        QuerySpec(
            semantic_view="survey_responses",
            metric="id",
            aggregation="count",
            limit=1001,
        )


def test_query_validation_blocks_cross_view_and_bad_filter_values(
    catalog: SemanticCatalog,
) -> None:
    with pytest.raises(AnalyticsValidationError, match="semantic view"):
        validate_query(
            QuerySpec(
                semantic_view="survey_responses",
                dimensions=["topic"],
                metric="id",
                aggregation="count",
            ),
            catalog,
        )
    with pytest.raises(AnalyticsValidationError, match="numeric"):
        validate_query(
            QuerySpec(
                semantic_view="survey_responses",
                metric="id",
                aggregation="count",
                filters=[
                    FilterSpec(member="score", operator="greater_than", value="1")
                ],
            ),
            catalog,
        )
    with pytest.raises(AnalyticsValidationError, match="does not accept value"):
        validate_query(
            QuerySpec(
                semantic_view="survey_responses",
                metric="id",
                aggregation="count",
                filters=[
                    FilterSpec(
                        member="store_name",
                        operator="in",
                        value={"ignored": ["unbounded"]},
                        values=["Mall"],
                    )
                ],
            ),
            catalog,
        )


def test_compiler_emits_governed_measure_and_value_order(
    catalog: SemanticCatalog,
) -> None:
    query = QuerySpec(
        semantic_view="survey_responses",
        dimensions=["store_name"],
        metric="score",
        aggregation="average",
        filters=[FilterSpec(member="score", operator="greater_than_or_equal", value=3)],
        time_dimension="reported_at",
        time_range=["2026-01-01", "2026-01-31"],
        time_granularity="day",
        timezone="Asia/Hong_Kong",
        order=[OrderSpec(member="value", direction="desc")],
        limit=100,
    )

    assert compile_cube_query(query, catalog) == {
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
        "timezone": "Asia/Hong_Kong",
        "order": {"survey_responses.average_score": "desc"},
        "limit": 100,
    }


def test_time_contract_rejects_invalid_timezone_and_duplicate_dimension() -> None:
    with pytest.raises(ValidationError, match="timezone"):
        QuerySpec(
            semantic_view="survey_responses",
            metric="id",
            aggregation="count",
            timezone="Not/A_Timezone",
        )
    with pytest.raises(ValidationError, match="must not also"):
        QuerySpec(
            semantic_view="survey_responses",
            dimensions=["reported_at"],
            metric="id",
            aggregation="count",
            time_dimension="reported_at",
        )
    with pytest.raises(ValidationError, match="reserved output key"):
        QuerySpec(
            semantic_view="survey_responses",
            dimensions=["value"],
            metric="id",
            aggregation="count",
        )
    with pytest.raises(ValidationError, match="reserved output key"):
        QuerySpec(
            semantic_view="survey_responses",
            metric="id",
            aggregation="count",
            time_dimension="value",
        )


def test_admin_metric_operations_remain_available(catalog: SemanticCatalog) -> None:
    assert Aggregation.WEIGHTED_AVERAGE in allowed_aggregations(FieldType.NUMBER)
    weighted_catalog = SemanticCatalog(
        fields=(
            *catalog.fields,
            CatalogField(
                slug="weight",
                label="Weight",
                semantic_view="survey_responses",
                data_type=FieldType.NUMBER,
            ),
        ),
        metrics=catalog.metrics,
    )
    metric = CatalogMetric(
        slug="weighted_score",
        label="Weighted score",
        semantic_view="survey_responses",
        aggregation=Aggregation.WEIGHTED_AVERAGE,
        source_field="score",
        weight_field="weight",
    )
    assert validate_metric(metric, weighted_catalog) == metric


@pytest.mark.parametrize(
    "value,expected",
    [
        ("=SUM(A1:A2)", "'=SUM(A1:A2)"),
        ("+cmd|' /C calc'!A0", "'+cmd|' /C calc'!A0"),
        ("ordinary text", "ordinary text"),
        (42, 42),
        (None, None),
    ],
)
def test_spreadsheet_formula_escaping(value: object, expected: object) -> None:
    assert escape_spreadsheet_formula(value) == expected
