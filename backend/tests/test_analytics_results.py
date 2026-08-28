from __future__ import annotations

from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utils.analytics import (
    Aggregation,
    CatalogField,
    CatalogMetric,
    FieldType,
    QuerySpec,
    SemanticCatalog,
)
from utils.analytics_results import augment_cube_query_with_supports, format_query_result


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
            )
        ],
    )


def test_simple_query_does_not_request_hidden_support_measures(
    catalog: SemanticCatalog,
) -> None:
    spec = QuerySpec(
        semantic_view="survey_responses",
        dimensions=["store_name"],
        metric="survey",
        aggregation="count",
    )
    query = {
        "dimensions": ["survey_responses.store_name"],
        "measures": ["survey_responses.survey_count"],
        "limit": 100,
    }

    assert augment_cube_query_with_supports(query, spec, catalog) == query


def test_result_uses_stable_value_key_and_always_returns_warnings(
    catalog: SemanticCatalog,
) -> None:
    spec = QuerySpec(
        semantic_view="survey_responses",
        dimensions=["store_name"],
        metric="survey",
        aggregation="count",
    )
    result = format_query_result(
        {
            "data": [
                {
                    "survey_responses.store_name": "Central",
                    "survey_responses.survey_count": "5",
                    "survey_responses.internal_support": "ignored",
                }
            ]
        },
        spec,
        catalog,
    )

    assert result["rows"] == [{"store_name": "Central", "value": 5}]
    assert result["warnings"] == []
    assert result["freshness_time"] is None


def test_result_rejects_invalid_cube_rows(catalog: SemanticCatalog) -> None:
    spec = QuerySpec(
        semantic_view="survey_responses",
        metric="survey",
        aggregation="count",
    )
    with pytest.raises(ValueError, match="invalid data"):
        format_query_result({"data": None}, spec, catalog)


def test_temporal_metric_value_uses_the_requested_timezone() -> None:
    catalog = SemanticCatalog(
        fields=[
            CatalogField(
                slug="reported_at",
                label="Reported At",
                semantic_view="survey_responses",
                data_type=FieldType.DATE,
            )
        ],
        metrics=[
            CatalogMetric(
                slug="first_reported_at",
                label="First Reported At",
                semantic_view="survey_responses",
                aggregation=Aggregation.MIN,
                source_field="reported_at",
                query_target="reported_at",
                public_aggregation="min",
                entity="reported_at",
            )
        ],
    )
    spec = QuerySpec(
        semantic_view="survey_responses",
        metric="reported_at",
        aggregation="min",
        timezone="Asia/Hong_Kong",
    )

    result = format_query_result(
        {
            "data": [
                {"survey_responses.first_reported_at": "2026-08-27T16:00:00Z"}
            ]
        },
        spec,
        catalog,
    )

    assert result["rows"] == [{"value": "2026-08-28T00:00:00+08:00"}]
