"""Cube supporting-aggregate orchestration and chart-friendly responses."""
from __future__ import annotations

from dataclasses import asdict
from typing import Any

from utils.analytics import (
    Aggregation,
    CatalogMetric,
    QuerySpec,
    SemanticCatalog,
)
from utils.analytics_statistics import (
    mean_confidence_interval_from_summary,
    proportion_confidence_interval,
    weighted_mean_confidence_interval_from_summary,
    weighted_proportion_confidence_interval_from_summary,
)


_WEIGHTED = {
    Aggregation.WEIGHTED_FILTERED_RATE,
    Aggregation.WEIGHTED_SUM,
    Aggregation.WEIGHTED_AVERAGE,
    Aggregation.WEIGHTED_VARIANCE_SAMPLE,
    Aggregation.WEIGHTED_VARIANCE_POPULATION,
    Aggregation.WEIGHTED_STDDEV_SAMPLE,
    Aggregation.WEIGHTED_STDDEV_POPULATION,
    Aggregation.WEIGHTED_MEAN_CONFIDENCE_INTERVAL,
    Aggregation.WEIGHTED_PROPORTION_CONFIDENCE_INTERVAL,
}


def _support_suffixes(metric: CatalogMetric) -> tuple[str, ...]:
    suffixes: list[str] = []
    if metric.aggregation in _WEIGHTED:
        suffixes.extend(
            [
                "invalid_weight_count",
                "invalid_value_count",
                "pair_count",
                "weight_sum",
                "weight_sum_squares",
                "weighted_value_sum",
                "weighted_value_square_sum",
            ]
        )
        if metric.aggregation in {
            Aggregation.WEIGHTED_FILTERED_RATE,
            Aggregation.WEIGHTED_PROPORTION_CONFIDENCE_INTERVAL,
        }:
            suffixes.append("success_weight_sum")
    if metric.aggregation is Aggregation.MEAN_CONFIDENCE_INTERVAL:
        suffixes.extend(
            ["sample_count", "value_sum", "value_square_sum", "variance_sample"]
        )
    elif metric.aggregation is Aggregation.PROPORTION_CONFIDENCE_INTERVAL:
        suffixes.extend(["success_count", "sample_count"])
    return tuple(suffixes)


def augment_cube_query_with_supports(
    cube_query: dict[str, Any],
    query: QuerySpec,
    catalog: SemanticCatalog,
) -> dict[str, Any]:
    result = dict(cube_query)
    measures = list(result.get("measures") or [])
    prefix = f"{query.semantic_view}."
    for slug in query.metrics:
        metric = catalog.metric(slug, query.semantic_view)
        for suffix in _support_suffixes(metric):
            member = f"{prefix}{slug}__{suffix}"
            if member not in measures:
                measures.append(member)
    result["measures"] = measures
    return result


def _number(
    row: dict[str, Any], key: str, *, zero_when_empty: bool = False
) -> float:
    value = row.get(key)
    if value is None:
        if zero_when_empty:
            return 0.0
        raise ValueError(f"Missing Cube supporting aggregate {key}")
    return float(value)


def _integer(row: dict[str, Any], key: str) -> int:
    return int(_number(row, key))


def _short_member(member: str) -> str:
    return member.split(".", maxsplit=1)[-1]


def format_query_result(
    response: dict[str, Any],
    query: QuerySpec,
    catalog: SemanticCatalog,
) -> dict[str, Any]:
    raw_rows = response.get("data")
    if not isinstance(raw_rows, list) or not all(
        isinstance(row, dict) for row in raw_rows
    ):
        raise ValueError("Cube analytics response contains invalid data")

    rows: list[dict[str, Any]] = []
    confidence: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    prefix = f"{query.semantic_view}."
    for row_index, raw_row in enumerate(raw_rows):
        rows.append(
            {
                _short_member(key): value
                for key, value in raw_row.items()
                if "__" not in _short_member(key)
            }
        )
        for slug in query.metrics:
            metric = catalog.metric(slug, query.semantic_view)
            base = f"{prefix}{slug}"
            if metric.aggregation in _WEIGHTED:
                invalid_weights = int(float(raw_row.get(f"{base}__invalid_weight_count") or 0))
                invalid_values = int(float(raw_row.get(f"{base}__invalid_value_count") or 0))
                if invalid_weights or invalid_values:
                    warnings.append(
                        {
                            "code": "invalid_weight_data",
                            "metric": slug,
                            "row_index": row_index,
                            "invalid_weight_count": invalid_weights,
                            "invalid_value_count": invalid_values,
                            "message": (
                                "Negative or non-finite weights/values caused this "
                                "weighted estimate to fail data-quality validation."
                            ),
                        }
                    )
                    continue

            level = metric.confidence_level or 0.95
            try:
                interval = None
                if metric.aggregation is Aggregation.MEAN_CONFIDENCE_INTERVAL:
                    interval = mean_confidence_interval_from_summary(
                        estimate=(
                            float(raw_row[base]) if raw_row.get(base) is not None else None
                        ),
                        sample_size=_integer(raw_row, f"{base}__sample_count"),
                        sample_variance=(
                            float(raw_row[f"{base}__variance_sample"])
                            if raw_row.get(f"{base}__variance_sample") is not None
                            else None
                        ),
                        confidence_level=level,
                    )
                elif metric.aggregation is Aggregation.PROPORTION_CONFIDENCE_INTERVAL:
                    sample_size = _integer(raw_row, f"{base}__sample_count")
                    interval = proportion_confidence_interval(
                        int(
                            _number(
                                raw_row,
                                f"{base}__success_count",
                                zero_when_empty=sample_size == 0,
                            )
                        ),
                        sample_size,
                        level,
                    )
                elif metric.aggregation is Aggregation.WEIGHTED_MEAN_CONFIDENCE_INTERVAL:
                    pair_count = _integer(raw_row, f"{base}__pair_count")
                    interval = weighted_mean_confidence_interval_from_summary(
                        pair_count=pair_count,
                        weight_sum=_number(
                            raw_row,
                            f"{base}__weight_sum",
                            zero_when_empty=pair_count == 0,
                        ),
                        weight_sum_squares=_number(
                            raw_row,
                            f"{base}__weight_sum_squares",
                            zero_when_empty=pair_count == 0,
                        ),
                        weighted_value_sum=_number(
                            raw_row,
                            f"{base}__weighted_value_sum",
                            zero_when_empty=pair_count == 0,
                        ),
                        weighted_value_square_sum=_number(
                            raw_row,
                            f"{base}__weighted_value_square_sum",
                            zero_when_empty=pair_count == 0,
                        ),
                        confidence_level=level,
                    )
                elif metric.aggregation is Aggregation.WEIGHTED_PROPORTION_CONFIDENCE_INTERVAL:
                    pair_count = _integer(raw_row, f"{base}__pair_count")
                    interval = weighted_proportion_confidence_interval_from_summary(
                        pair_count=pair_count,
                        weight_sum=_number(
                            raw_row,
                            f"{base}__weight_sum",
                            zero_when_empty=pair_count == 0,
                        ),
                        weight_sum_squares=_number(
                            raw_row,
                            f"{base}__weight_sum_squares",
                            zero_when_empty=pair_count == 0,
                        ),
                        success_weight_sum=_number(
                            raw_row,
                            f"{base}__success_weight_sum",
                            zero_when_empty=pair_count == 0,
                        ),
                        confidence_level=level,
                    )
                if interval is not None:
                    confidence.append(
                        {"metric": slug, "row_index": row_index, **asdict(interval)}
                    )
            except (KeyError, TypeError, ValueError) as error:
                warnings.append(
                    {
                        "code": "confidence_support_unavailable",
                        "metric": slug,
                        "row_index": row_index,
                        "message": str(error),
                    }
                )

    columns = [
        {
            "name": slug,
            "label": catalog.field(slug, query.semantic_view).label,
            "data_type": catalog.field(slug, query.semantic_view).data_type.value,
            "kind": "dimension",
        }
        for slug in query.dimensions
    ] + [
        {
            "name": slug,
            "label": catalog.metric(slug, query.semantic_view).label,
            "data_type": "number",
            "kind": "metric",
        }
        for slug in query.metrics
    ]
    return {
        "columns": columns,
        "rows": rows,
        "confidence": confidence,
        "warnings": warnings,
        "freshness_time": response.get("lastRefreshTime"),
    }
