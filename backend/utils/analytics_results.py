"""Formatting for the one-metric aggregate analytics contract."""
from __future__ import annotations

import math
from datetime import datetime, time
from typing import Any

from utils.analytics import (
    FieldType,
    QuerySpec,
    SemanticCatalog,
    metric_result_type,
    resolve_query_metric,
)
from utils.utc import resolve_timezone


def augment_cube_query_with_supports(
    cube_query: dict[str, Any],
    query: QuerySpec,
    catalog: SemanticCatalog,
    role: str = "viewer",
) -> dict[str, Any]:
    """Keep the execution hook stable; simple metrics need no support measures."""

    resolve_query_metric(query, catalog, role)
    return dict(cube_query)


def _local_member(member: str, semantic_view: str) -> str:
    prefix = f"{semantic_view}."
    value = member[len(prefix) :] if member.startswith(prefix) else member
    return value.split(".", maxsplit=1)[0]


def _coerce_value(value: Any, field_type: FieldType, timezone_name: str | None) -> Any:
    if value is None or not isinstance(value, str):
        return value
    if field_type is FieldType.NUMBER:
        try:
            number = float(value)
        except ValueError:
            return value
        if not math.isfinite(number):
            return None
        return int(number) if number.is_integer() else number
    if field_type is FieldType.BOOLEAN and value.lower() in {"true", "false"}:
        return value.lower() == "true"
    if field_type is FieldType.DATE:
        try:
            timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return value
        display_timezone = resolve_timezone(timezone_name)
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=display_timezone)
        else:
            timestamp = timestamp.astimezone(display_timezone)
        return timestamp.isoformat()
    if field_type is FieldType.TIME:
        try:
            return time.fromisoformat(value).isoformat()
        except ValueError:
            return value
    return value


def format_query_result(
    response: dict[str, Any],
    query: QuerySpec,
    catalog: SemanticCatalog,
    role: str = "viewer",
) -> dict[str, Any]:
    """Return flat rows and expose the sole aggregate under the stable `value` key."""

    raw_rows = response.get("data")
    if not isinstance(raw_rows, list) or not all(
        isinstance(row, dict) for row in raw_rows
    ):
        raise ValueError("Cube analytics response contains invalid data")

    governed_metric = resolve_query_metric(query, catalog, role)
    cube_metric = governed_metric.slug
    metric_type = metric_result_type(governed_metric, catalog)
    selected_dimensions = {*query.dimensions}
    if query.time_dimension:
        selected_dimensions.add(query.time_dimension)
    dimension_types = {
        slug: catalog.field(slug, query.semantic_view).data_type
        for slug in selected_dimensions
    }
    rows: list[dict[str, Any]] = []
    for raw_row in raw_rows:
        row: dict[str, Any] = {}
        for key, value in raw_row.items():
            member = _local_member(str(key), query.semantic_view)
            if member == cube_metric:
                row["value"] = _coerce_value(value, metric_type, query.timezone)
            elif member in selected_dimensions:
                row[member] = _coerce_value(
                    value, dimension_types[member], query.timezone
                )
        rows.append(row)

    return {
        "rows": rows,
        "warnings": [],
        "freshness_time": response.get("lastRefreshTime")
        or response.get("last_refresh_time"),
    }
