import sys
from pathlib import Path

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


def _catalog() -> SemanticCatalog:
    return SemanticCatalog(
        fields=[
            CatalogField(
                slug="store_name",
                label="Store",
                semantic_view="survey_responses",
                data_type=FieldType.STRING,
            ),
            CatalogField(
                slug="score",
                label="Score",
                semantic_view="survey_responses",
                data_type=FieldType.NUMBER,
            ),
            CatalogField(
                slug="weight",
                label="Weight",
                semantic_view="survey_responses",
                data_type=FieldType.NUMBER,
                visibility="admin",
            ),
        ],
        metrics=[
            CatalogMetric(
                slug="mean_ci",
                label="Mean confidence interval",
                semantic_view="survey_responses",
                aggregation=Aggregation.MEAN_CONFIDENCE_INTERVAL,
                source_field="score",
                confidence_level=0.95,
            ),
            CatalogMetric(
                slug="weighted_score",
                label="Weighted score",
                semantic_view="survey_responses",
                aggregation=Aggregation.WEIGHTED_AVERAGE,
                source_field="score",
                weight_field="weight",
            ),
        ],
    )


def test_cube_query_requests_ci_and_weight_data_quality_supports() -> None:
    catalog = _catalog()
    spec = QuerySpec(
        semantic_view="survey_responses",
        dimensions=["store_name"],
        metrics=["mean_ci", "weighted_score"],
    )
    query = {
        "dimensions": ["survey_responses.store_name"],
        "measures": ["survey_responses.mean_ci", "survey_responses.weighted_score"],
        "limit": 100,
    }

    augmented = augment_cube_query_with_supports(query, spec, catalog)

    assert "survey_responses.mean_ci__sample_count" in augmented["measures"]
    assert "survey_responses.mean_ci__variance_sample" in augmented["measures"]
    assert (
        "survey_responses.weighted_score__invalid_weight_count"
        in augmented["measures"]
    )
    assert "survey_responses.weighted_score__weight_sum" in augmented["measures"]


def test_result_formats_confidence_and_visible_weight_failure() -> None:
    catalog = _catalog()
    spec = QuerySpec(
        semantic_view="survey_responses",
        dimensions=["store_name"],
        metrics=["mean_ci", "weighted_score"],
    )
    response = {
        "data": [
            {
                "survey_responses.store_name": "Central",
                "survey_responses.mean_ci": "3.0",
                "survey_responses.mean_ci__sample_count": "5",
                "survey_responses.mean_ci__variance_sample": "2.5",
                "survey_responses.weighted_score": None,
                "survey_responses.weighted_score__invalid_weight_count": "1",
                "survey_responses.weighted_score__invalid_value_count": "0",
            }
        ],
        "lastRefreshTime": "2026-08-25T12:00:00.000Z",
    }

    result = format_query_result(response, spec, catalog)

    assert result["rows"] == [
        {"store_name": "Central", "mean_ci": "3.0", "weighted_score": None}
    ]
    assert result["confidence"][0]["estimate"] == pytest.approx(3.0)
    assert result["confidence"][0]["sample_size"] == 5
    assert result["warnings"][0]["code"] == "invalid_weight_data"
    assert result["freshness_time"] == "2026-08-25T12:00:00.000Z"


def test_empty_ci_support_sums_are_interpreted_as_zero() -> None:
    catalog = SemanticCatalog(
        fields=[
            CatalogField(
                slug="score",
                label="Score",
                semantic_view="survey_responses",
                data_type=FieldType.NUMBER,
            ),
            CatalogField(
                slug="weight",
                label="Weight",
                semantic_view="survey_responses",
                data_type=FieldType.NUMBER,
            ),
        ],
        metrics=[
            CatalogMetric(
                slug="weighted_ci",
                label="Weighted CI",
                semantic_view="survey_responses",
                aggregation=Aggregation.WEIGHTED_MEAN_CONFIDENCE_INTERVAL,
                source_field="score",
                weight_field="weight",
                confidence_level=0.95,
            )
        ],
    )
    spec = QuerySpec(
        semantic_view="survey_responses", metrics=["weighted_ci"]
    )
    base = "survey_responses.weighted_ci"
    response = {
        "data": [
            {
                base: None,
                f"{base}__invalid_weight_count": 0,
                f"{base}__invalid_value_count": 0,
                f"{base}__pair_count": 0,
                f"{base}__weight_sum": None,
                f"{base}__weight_sum_squares": None,
                f"{base}__weighted_value_sum": None,
                f"{base}__weighted_value_square_sum": None,
            }
        ]
    }

    result = format_query_result(response, spec, catalog)

    assert result["confidence"][0]["estimate"] is None
    assert result["confidence"][0]["sample_size"] == 0
    assert not any(
        warning["code"] == "confidence_support_unavailable"
        for warning in result["warnings"]
    )
