"""Reusable live smoke/contract tests for the analytics dashboard migration.

Run the live suite explicitly so the normal unit-test run stays hermetic::

    ANALYTICS_E2E=1 \
    ANALYTICS_E2E_BASE_URL=http://localhost:8000 \
    ANALYTICS_E2E_API_TOKEN='<profile-backend-api-token>' \
    .venv/bin/python -m pytest -m analytics_e2e -v --log-cli-level=INFO \
        backend/tests/test_analytics_dashboard_e2e.py

The profile's static API bearer token is supplied with
``ANALYTICS_E2E_API_TOKEN``. For legacy comparisons, provide
``ANALYTICS_E2E_COMPARISON_MANIFEST`` pointing to a JSON file containing a
list of cases.  Each case has this shape::

    {
      "name": "store distribution",
      "legacy": {"method": "GET", "path": "/dashboard/store-distribution"},
      "chart_slug": "dashboard_store_distribution",
      "chart_payload": {"timezone": "Asia/Hong_Kong"},
      "legacy_rows_path": "data",
      "row_key_map": {
        "store_key": "store_key",
        "topic_sentiment_negative_count": "negative_count"
      }
    }

``row_key_map`` maps a new chart row key to the equivalent legacy row key.
Rows are compared as sorted tuples, so ordering differences are reported as
calculation differences rather than producing a false failure.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import logging
import os
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx
import pytest


pytestmark = pytest.mark.analytics_e2e

LOGGER = logging.getLogger("analytics_e2e")
_LOG_RESULT_MAX_BYTES = int(os.getenv("ANALYTICS_E2E_LOG_MAX_BYTES", "50000"))
_SECRET_KEYS = {
    "access_token",
    "api_secret",
    "authorization",
    "password",
    "refresh_token",
    "secret",
    "token",
}

DEFAULT_CHART_SLUGS = (
    "dashboard_sentiment_distribution",
    "dashboard_store_distribution",
    "dashboard_store_format_distribution",
    "dashboard_channel_delivery_distribution",
    "dashboard_topic_sentiment_counts",
    "dashboard_overall_topic_sentiment_score",
    "dashboard_mixed_topic_sentiment_score",
    "dashboard_topic_distribution",
    "dashboard_department_distribution",
    "dashboard_keyword_analysis",
    "dashboard_first_reported_at",
    "dashboard_last_reported_at",
    "dashboard_last_updated_at",
)

FILTER_MEMBERS = {
    "survey_responses": (
        "store_key",
        "store_name_english",
        "store_format",
        "channel_name",
        "delivery_service_name",
        "topic_sentiment",
    ),
    "survey_topics": ("topic",),
    "survey_departments": ("department",),
    "survey_keywords": ("keyword",),
}


@dataclass(frozen=True)
class E2EConfig:
    base_url: str
    api_prefix: str
    api_token: str | None = field(repr=False)
    timezone: str
    from_date: str
    to_date: str
    timeout: float

    @classmethod
    def from_environment(cls) -> "E2EConfig":
        return cls(
            base_url=os.getenv("ANALYTICS_E2E_BASE_URL", "http://localhost:8000").rstrip("/"),
            api_prefix=os.getenv("ANALYTICS_E2E_API_PREFIX", "").strip("/"),
            api_token=os.getenv("ANALYTICS_E2E_API_TOKEN") or None,
            timezone=os.getenv("ANALYTICS_E2E_TIMEZONE", "Asia/Hong_Kong"),
            from_date=os.getenv("ANALYTICS_E2E_FROM_DATE", "2020-01-01T00:00:00Z"),
            to_date=os.getenv("ANALYTICS_E2E_TO_DATE", "2030-01-01T00:00:00Z"),
            timeout=float(os.getenv("ANALYTICS_E2E_TIMEOUT", "30")),
        )

    def url(self, path: str) -> str:
        suffix = f"/{self.api_prefix}" if self.api_prefix else ""
        return f"{self.base_url}{suffix}/{path.lstrip('/')}"

    def authentication_headers(self) -> dict[str, str]:
        assert self.api_token is not None
        return {
            "Authorization": f"Bearer {self.api_token}",
        }


def _require_e2e_enabled() -> None:
    if os.getenv("ANALYTICS_E2E", "").lower() not in {"1", "true", "yes"}:
        pytest.skip("Set ANALYTICS_E2E=1 to run live analytics dashboard tests")


def _require_auth(config: E2EConfig) -> None:
    required = {"ANALYTICS_E2E_API_TOKEN": config.api_token}
    missing = [name for name, value in required.items() if not value]
    if missing:
        pytest.skip(f"Set {', '.join(missing)} for static API authentication")


def _redact(value: Any, key: str | None = None) -> Any:
    if key and key.lower() in _SECRET_KEYS:
        return "<redacted>"
    if isinstance(value, dict):
        return {name: _redact(item, name) for name, item in value.items()}
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact(item) for item in value)
    return value


def _log_value(value: Any) -> str:
    try:
        rendered = json.dumps(_redact(value), sort_keys=True, default=str)
    except (TypeError, ValueError):
        rendered = repr(_redact(value))
    if len(rendered) <= _LOG_RESULT_MAX_BYTES:
        return rendered
    return f"{rendered[:_LOG_RESULT_MAX_BYTES]}...<truncated>"


def _safe_url(url: httpx.URL) -> str:
    parsed = urlsplit(str(url))
    query = [
        (key, "<redacted>" if key.lower() in _SECRET_KEYS else value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
    ]
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment))


def _request_payload(response: httpx.Response) -> Any:
    content = response.request.content
    if not content:
        return None
    try:
        return json.loads(content)
    except (TypeError, UnicodeDecodeError, json.JSONDecodeError):
        return "<non-JSON request body>"


def _response_payload(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return response.text[:_LOG_RESULT_MAX_BYTES]


def _log_http_result(response: httpx.Response, *, label: str | None = None) -> None:
    LOGGER.info(
        "analytics_e2e query_result label=%s method=%s url=%s status=%s request=%s result=%s",
        label or "http",
        response.request.method,
        _safe_url(response.request.url),
        response.status_code,
        _log_value(_request_payload(response)),
        _log_value(_response_payload(response)),
    )


def _json(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError as error:  # pragma: no cover - exercised by live failures
        raise AssertionError(
            f"Expected JSON from {response.request.method} {response.request.url}; "
            f"received HTTP {response.status_code}: {response.text[:500]}"
        ) from error


def _assert_status(
    response: httpx.Response,
    expected: int = 200,
    *,
    label: str | None = None,
) -> Any:
    _log_http_result(response, label=label)
    body = response.text[:1_000]
    assert response.status_code == expected, (
        f"{response.request.method} {response.request.url} returned "
        f"{response.status_code}, expected {expected}: {body}"
    )
    return _json(response)


def _dotted_get(value: Any, path: str) -> Any:
    for part in path.split("."):
        if isinstance(value, dict):
            value = value.get(part)
        else:
            return None
    return value


def _normalised_rows(
    payload: Any,
    rows_path: str,
    row_key_map: dict[str, str],
) -> list[tuple[Any, ...]]:
    rows = _dotted_get(payload, rows_path)
    assert isinstance(rows, list), f"Expected list at {rows_path!r}, got {rows!r}"
    result = []
    for row in rows:
        assert isinstance(row, dict), f"Expected object row, got {row!r}"
        result.append(tuple(row.get(legacy_key) for legacy_key in row_key_map.values()))
    return sorted(result, key=repr)


@pytest.fixture(scope="session")
def e2e_config() -> E2EConfig:
    _require_e2e_enabled()
    return E2EConfig.from_environment()


@pytest.fixture(scope="session")
def e2e_client(e2e_config: E2EConfig) -> httpx.Client:
    _require_auth(e2e_config)
    client = httpx.Client(timeout=e2e_config.timeout, follow_redirects=True)
    client.headers.update(e2e_config.authentication_headers())
    yield client
    client.close()


@pytest.fixture(scope="session")
def catalog(e2e_client: httpx.Client, e2e_config: E2EConfig) -> dict[str, Any]:
    payload = _assert_status(
        e2e_client.get(e2e_config.url("analytics/catalog")),
        label="analytics/catalog",
    )
    assert isinstance(payload, dict)
    assert payload.get("model_version", 0) >= 1
    assert set(payload.get("semantic_views", [])) >= set(FILTER_MEMBERS)
    assert payload.get("fields")
    assert set(payload.get("metric_targets", {})) >= set(FILTER_MEMBERS)
    for targets in payload["metric_targets"].values():
        assert targets
        assert all(target.get("metric") and target.get("aggregations") for target in targets)
    return payload


@pytest.fixture(scope="session")
def published_charts(
    e2e_client: httpx.Client, e2e_config: E2EConfig, catalog: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    payload = _assert_status(
        e2e_client.get(e2e_config.url("analytics/charts/published")),
        label="analytics/charts/published",
    )
    assert isinstance(payload, list)
    charts = {item.get("slug"): item for item in payload if isinstance(item, dict)}
    missing = sorted(set(DEFAULT_CHART_SLUGS) - charts.keys())
    assert not missing, f"Published default charts are missing: {missing}"
    for chart in charts.values():
        assert chart.get("status") == "published"
        assert chart.get("model_version") == catalog["model_version"]
        assert isinstance(chart.get("definition"), dict)
    return charts


def _filter_options(
    client: httpx.Client,
    config: E2EConfig,
    semantic_view: str,
    member: str,
) -> dict[str, Any]:
    payload = {
        "semantic_view": semantic_view,
        "member": member,
        "timezone": config.timezone,
        "limit": 100,
    }
    response = client.post(config.url("analytics/filter-options"), json=payload)
    result = _assert_status(response, label=f"analytics/filter-options/{semantic_view}.{member}")
    assert result["semantic_view"] == semantic_view
    assert result["member"] == member
    assert isinstance(result.get("values"), list)
    assert "freshness_time" in result
    return result


def _chart_data(
    client: httpx.Client,
    config: E2EConfig,
    chart: dict[str, Any],
    *,
    filters: list[dict[str, Any]] | None = None,
    bounded_time: bool = False,
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = dict(overrides or {})
    payload.setdefault("timezone", config.timezone)
    if filters is not None:
        payload["filters"] = filters
    if bounded_time and chart["semantic_view"] == "survey_responses":
        payload.update(
            {
                "time_range": [config.from_date, config.to_date],
                "time_granularity": "day",
            }
        )
    result = _assert_status(
        client.post(config.url(f"analytics/charts/{chart['id']}/data"), json=payload),
        label=f"analytics/charts/{chart['slug']}/data",
    )
    assert isinstance(result, dict)
    assert result.get("chart", {}).get("slug") == chart["slug"]
    assert result.get("model_version") == chart.get("model_version")
    assert isinstance(result.get("rows"), list)
    assert result.get("row_count") == len(result["rows"])
    assert isinstance(result.get("schema"), dict)
    assert result["schema"]["metric"]["key"] == "value"
    assert result["schema"]["metric"]["target"] == chart["definition"]["metric"]
    assert isinstance(result.get("warnings"), list)
    assert "freshness_time" in result
    return result


def test_unauthenticated_analytics_requests_are_rejected(e2e_config: E2EConfig) -> None:
    _require_e2e_enabled()
    client = httpx.Client(timeout=e2e_config.timeout, follow_redirects=False)
    try:
        for path in ("analytics/catalog", "analytics/charts/published"):
            response = client.get(e2e_config.url(path))
            _log_http_result(response, label=f"unauthenticated/{path}")
            assert response.status_code == 401, (
                f"{path} should reject unauthenticated access, got "
                f"{response.status_code}: {response.text[:500]}"
            )
            assert response.headers.get("cache-control") == "no-store, private"
    finally:
        client.close()


def test_catalog_and_published_charts_are_bearer_visible(
    catalog: dict[str, Any], published_charts: dict[str, dict[str, Any]]
) -> None:
    assert len(published_charts) >= len(DEFAULT_CHART_SLUGS)
    assert catalog["model_version"] > 0


def test_goal_first_capabilities_are_executable(
    e2e_client: httpx.Client,
    e2e_config: E2EConfig,
    catalog: dict[str, Any],
) -> None:
    for semantic_view, targets in catalog["metric_targets"].items():
        target = targets[0]
        aggregation = target["aggregations"][0]
        capabilities = _assert_status(
            e2e_client.post(
                e2e_config.url("analytics/query-capabilities"),
                json={
                    "semantic_view": semantic_view,
                    "metric": target["metric"],
                    "aggregation": aggregation["method"],
                },
            ),
            label=f"analytics/query-capabilities/{semantic_view}",
        )
        assert capabilities["metric"]["metric"] == target["metric"]
        assert capabilities["metric"]["aggregation"] == aggregation["method"]
        assert isinstance(capabilities["allowed_dimensions"], list)
        assert isinstance(capabilities["filter_members"], list)
        assert isinstance(capabilities["allowed_time_dimensions"], list)


@pytest.mark.parametrize(
    ("semantic_view", "member"),
    [
        (semantic_view, member)
        for semantic_view, members in FILTER_MEMBERS.items()
        for member in members
    ],
    ids=[f"{semantic_view}-{member}" for semantic_view, members in FILTER_MEMBERS.items() for member in members],
)
def test_filter_discovery_returns_usable_values(
    e2e_client: httpx.Client,
    e2e_config: E2EConfig,
    semantic_view: str,
    member: str,
) -> None:
    result = _filter_options(e2e_client, e2e_config, semantic_view, member)
    for item in result["values"]:
        assert isinstance(item, dict)
        assert item.get("value") is not None
        assert isinstance(item.get("count"), (int, float))


def test_every_default_chart_loads(
    e2e_client: httpx.Client,
    e2e_config: E2EConfig,
    published_charts: dict[str, dict[str, Any]],
) -> None:
    for slug in DEFAULT_CHART_SLUGS:
        _chart_data(e2e_client, e2e_config, published_charts[slug])


def test_filter_and_timezone_scenarios(
    e2e_client: httpx.Client,
    e2e_config: E2EConfig,
    published_charts: dict[str, dict[str, Any]],
) -> None:
    response_chart = published_charts["dashboard_store_distribution"]
    time_chart = published_charts["dashboard_sentiment_distribution"]
    response_values = {
        member: _filter_options(e2e_client, e2e_config, "survey_responses", member)["values"]
        for member in FILTER_MEMBERS["survey_responses"]
    }

    # No filters and a non-UTC bounded range exercise the default graph and its
    # local-day/timezone contract even when the database has no survey rows.
    _chart_data(e2e_client, e2e_config, response_chart)
    _chart_data(e2e_client, e2e_config, time_chart, bounded_time=True)

    store_key = [item["value"] for item in response_values["store_key"][:2]]
    if store_key:
        _chart_data(
            e2e_client,
            e2e_config,
            response_chart,
            filters=[{"member": "store_key", "operator": "in", "values": store_key}],
        )
    store_name = [item["value"] for item in response_values["store_name_english"][:1]]
    if store_name:
        _chart_data(
            e2e_client,
            e2e_config,
            response_chart,
            filters=[
                {
                    "member": "store_name_english",
                    "operator": "equals",
                    "value": store_name[0],
                }
            ],
        )

    # Numeric ranges and a deliberately impossible value cover the empty-result
    # path without depending on a particular tenant's data distribution.
    for member, values in (("cls", [0, 100]), ("topic_sentiment_score", [-1, 1])):
        _chart_data(
            e2e_client,
            e2e_config,
            response_chart,
            filters=[{"member": member, "operator": "between", "values": values}],
        )
    empty_result = _chart_data(
        e2e_client,
        e2e_config,
        response_chart,
        filters=[
            {
                "member": "store_name_english",
                "operator": "equals",
                "value": "__analytics_e2e_no_match__",
            }
        ],
    )
    assert empty_result["rows"] == []

    topic_chart = published_charts["dashboard_topic_distribution"]
    topic_values = _filter_options(e2e_client, e2e_config, "survey_topics", "topic")["values"]
    if topic_values:
        _chart_data(
            e2e_client,
            e2e_config,
            topic_chart,
            filters=[{"member": "topic", "operator": "in", "values": [topic_values[0]["value"]]}],
        )


def test_assignment_grains_reject_cross_assignment_filters(
    e2e_client: httpx.Client,
    e2e_config: E2EConfig,
    published_charts: dict[str, dict[str, Any]],
) -> None:
    department_chart = published_charts["dashboard_department_distribution"]
    response = e2e_client.post(
        e2e_config.url(f"analytics/charts/{department_chart['id']}/data"),
        json={
            "timezone": e2e_config.timezone,
            "filters": [{"member": "topic", "operator": "equals", "value": "Delivery"}],
        },
    )
    _log_http_result(response, label="cross-assignment-filter")
    assert response.status_code == 422, response.text[:1_000]


def test_static_bearer_has_chart_management_access(
    e2e_client: httpx.Client, e2e_config: E2EConfig
) -> None:
    response = e2e_client.get(e2e_config.url("admin/analytics/charts"))
    _log_http_result(response, label="admin/analytics/charts")
    assert response.status_code == 200, response.text[:1_000]


def test_legacy_comparison_manifest(
    e2e_client: httpx.Client,
    e2e_config: E2EConfig,
    published_charts: dict[str, dict[str, Any]],
) -> None:
    manifest_name = os.getenv("ANALYTICS_E2E_COMPARISON_MANIFEST")
    if not manifest_name:
        pytest.skip("Set ANALYTICS_E2E_COMPARISON_MANIFEST to run legacy comparisons")

    manifest_path = Path(manifest_name)
    cases = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert isinstance(cases, list) and cases, "Comparison manifest must be a non-empty list"
    legacy_base_url = os.getenv("ANALYTICS_E2E_LEGACY_BASE_URL", e2e_config.base_url).rstrip("/")
    for case in cases:
        assert isinstance(case, dict)
        name = case.get("name", case.get("chart_slug", "unnamed case"))
        chart = published_charts[case["chart_slug"]]
        legacy = case["legacy"]
        method = str(legacy.get("method", "GET")).upper()
        legacy_url = f"{legacy_base_url}/{str(legacy['path']).lstrip('/')}"
        if method == "GET":
            legacy_response = e2e_client.get(legacy_url, params=legacy.get("params"))
        elif method == "POST":
            legacy_response = e2e_client.post(legacy_url, json=legacy.get("json"))
        else:
            pytest.fail(f"{name}: unsupported legacy method {method}")
        legacy_payload = _assert_status(legacy_response, label=f"legacy/{name}")
        new_payload = _chart_data(
            e2e_client,
            e2e_config,
            chart,
            overrides=case.get("chart_payload") or {},
        )
        row_key_map = case["row_key_map"]
        assert isinstance(row_key_map, dict) and row_key_map
        old_rows = _normalised_rows(
            legacy_payload,
            case.get("legacy_rows_path", "data"),
            row_key_map,
        )
        new_rows = _normalised_rows(
            new_payload,
            "rows",
            {new_key: new_key for new_key in row_key_map},
        )
        assert new_rows == old_rows, f"{name}: legacy and governed rows differ"
