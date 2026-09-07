"""Private-network Cube API client with short-lived profile-scoped JWTs."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from jose import jwt

from features.analytics.model.semantic import (
    AnalyticsValidationError,
    validate_identifier,
)

logger = logging.getLogger(__name__)


class CubeClientError(RuntimeError):
    """Base error raised by the Cube transport abstraction."""


class CubeQueryError(CubeClientError):
    """Cube rejected a governed query or refresh request."""


class CubeUnavailableError(CubeClientError):
    """Cube could not service a request because it is unavailable."""


class CubeContinueWaitError(CubeClientError):
    """Cube is still processing an idempotent long-poll query."""


class CubeQueryPendingError(CubeUnavailableError):
    """Cube did not finish a long-poll query within the caller's budget."""


class CubePreAggregationNotReadyError(CubeUnavailableError):
    """Cube's refresh worker has not prepared the required partitions yet."""


class CubePreAggregationJobError(CubeUnavailableError):
    """A requested Cube pre-aggregation job failed or returned invalid state."""


def _cube_error(error: object) -> CubeClientError:
    """Classify Cube's error envelope without exposing it to API callers.

    Cube can report an upstream PostgreSQL outage as either a 4xx response or
    an HTTP-200 payload containing ``error``.  These are service failures, not
    invalid semantic requests, and must map to the analytics 503 contract.
    """

    detail = str(error or "Cube rejected the analytics query")
    normalized = " ".join(detail.lower().split())
    if normalized == "continue wait":
        return CubeContinueWaitError("Cube query is still processing")
    pre_aggregation_markers = (
        "no pre-aggregation partitions were built yet",
        "wasn't set up to build pre-aggregations",
        "was not set up to build pre-aggregations",
    )
    if any(marker in normalized for marker in pre_aggregation_markers):
        return CubePreAggregationNotReadyError(
            "Cube pre-aggregations are still preparing"
        )
    unavailable_markers = (
        "unable to connect to the database",
        "connection refused",
        "connection terminated",
        "server does not support ssl",
        "database is unavailable",
        "database connection",
        "connect timeout",
    )
    if any(marker in normalized for marker in unavailable_markers):
        return CubeUnavailableError("Cube analytics database is unavailable")
    return CubeQueryError(detail)


def create_cube_token(
    api_secret: str,
    profile_id: str,
    role: str,
    *,
    expires_in_seconds: int = 60,
    now: datetime | None = None,
) -> str:
    if not api_secret:
        raise ValueError("Cube API secret is required")
    validate_identifier(profile_id)
    if role not in {"viewer", "admin", "refresh_worker"}:
        raise AnalyticsValidationError("Unknown Cube analytics role")
    if not 1 <= expires_in_seconds <= 300:
        raise ValueError("Cube token lifetime must be between 1 and 300 seconds")
    issued_at = now or datetime.now(UTC)
    if issued_at.tzinfo is None:
        issued_at = issued_at.replace(tzinfo=UTC)
    issued_at = issued_at.astimezone(UTC)
    expires_at = issued_at + timedelta(seconds=expires_in_seconds)
    return jwt.encode(
        {
            "sub": f"analytics:{profile_id}",
            "aud": "cube",
            "iat": int(issued_at.timestamp()),
            "exp": int(expires_at.timestamp()),
            "profile_id": profile_id,
            "role": role,
            "securityContext": {"profile": profile_id, "role": role},
        },
        api_secret,
        algorithm="HS256",
    )


class CubeClient:
    _continue_wait_max_attempts = 10
    _continue_wait_backoff_seconds = (0.1, 0.25, 0.5, 1.0)

    def __init__(
        self,
        base_url: str,
        api_secret: str,
        timeout_seconds: float = 10.0,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not base_url:
            raise ValueError("Cube base URL is required")
        if not api_secret:
            raise ValueError("Cube API secret is required")
        self.base_url = base_url.rstrip("/")
        self.api_secret = api_secret
        self.timeout_seconds = timeout_seconds
        self.transport = transport

    async def _post(
        self,
        path: str,
        payload: Mapping[str, Any],
        *,
        profile_id: str,
        role: str,
        request_id: str | None,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any] | list[Any]:
        token = create_cube_token(self.api_secret, profile_id, role)
        headers = {"Authorization": f"Bearer {token}"}
        if request_id:
            headers["X-Request-ID"] = request_id
        try:
            async with httpx.AsyncClient(
                timeout=timeout_seconds or self.timeout_seconds,
                transport=self.transport,
            ) as client:
                response = await client.post(
                    self.base_url + path,
                    json=dict(payload),
                    headers=headers,
                )
        except httpx.HTTPError as error:
            raise CubeUnavailableError(
                "Cube analytics service is unavailable"
            ) from error

        if 400 <= response.status_code < 500:
            try:
                detail = response.json().get("error") or response.text
            except ValueError:
                detail = response.text
            raise _cube_error(detail)
        if response.status_code >= 500:
            raise CubeUnavailableError("Cube analytics service failed the request")
        try:
            result = response.json()
        except ValueError as error:
            raise CubeUnavailableError("Cube returned an invalid response") from error
        if isinstance(result, dict) and result.get("error"):
            raise _cube_error(result["error"])
        if not isinstance(result, (dict, list)):
            raise CubeUnavailableError("Cube returned an invalid response")
        return result

    async def execute(
        self,
        query: Mapping[str, Any],
        *,
        profile_id: str,
        role: str,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        started_at = time.monotonic()
        deadline = started_at + self.timeout_seconds
        span_id = request_id or str(uuid.uuid4())
        attempt = 0
        while True:
            attempt += 1
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise CubeQueryPendingError(
                    "Cube query is still processing after the retry deadline"
                )
            try:
                result = await self._post(
                    "/cubejs-api/v1/load",
                    {"query": dict(query)},
                    profile_id=profile_id,
                    role=role,
                    request_id=f"{span_id}-span-{attempt}",
                    timeout_seconds=remaining,
                )
            except CubeContinueWaitError as error:
                remaining = deadline - time.monotonic()
                logger.info(
                    "Cube query is still processing",
                    extra={
                        "event": "analytics.cube.continue_wait",
                        "request_id": span_id,
                        "sequence": attempt,
                        "elapsed_seconds": round(time.monotonic() - started_at, 3),
                        "remaining_seconds": round(max(remaining, 0), 3),
                    },
                )
                if attempt >= self._continue_wait_max_attempts or remaining <= 0:
                    logger.warning(
                        "Cube query exceeded the retry budget",
                        extra={
                            "event": "analytics.cube.query_pending",
                            "request_id": span_id,
                            "sequence": attempt,
                        },
                    )
                    raise CubeQueryPendingError(
                        "Cube query is still processing after the retry deadline"
                    ) from error
                backoff_index = min(
                    attempt - 1, len(self._continue_wait_backoff_seconds) - 1
                )
                delay = min(
                    self._continue_wait_backoff_seconds[backoff_index],
                    1.0,
                    remaining,
                )
                if delay >= remaining:
                    raise CubeQueryPendingError(
                        "Cube query is still processing after the retry deadline"
                    ) from error
                await asyncio.sleep(delay)
                continue
            if not isinstance(result, dict):
                raise CubeUnavailableError("Cube returned an invalid query response")
            return result

    async def refresh_pre_aggregations(
        self,
        *,
        profile_id: str,
        role: str = "refresh_worker",
        date_range: Sequence[str] | None = None,
        pre_aggregations: Sequence[str] | None = None,
        request_id: str | None = None,
        timezone_name: str = "UTC",
        timezone_names: Sequence[str] | None = None,
        timeout_seconds: float | None = None,
    ) -> list[str]:
        if date_range is not None and len(date_range) != 2:
            raise ValueError("Pre-aggregation refresh date range requires two values")
        for pre_aggregation in pre_aggregations or ():
            parts = pre_aggregation.split(".")
            if len(parts) != 2:
                raise AnalyticsValidationError("Invalid pre-aggregation name")
            for part in parts:
                validate_identifier(part)
        selected_timezones = list(timezone_names or (timezone_name,))
        if not selected_timezones or any(not item for item in selected_timezones):
            raise ValueError("At least one pre-aggregation timezone is required")
        selector: dict[str, Any] = {
            "contexts": [{"securityContext": {"profile": profile_id, "role": role}}],
            "timezones": selected_timezones,
        }
        if pre_aggregations:
            selector["preAggregations"] = list(pre_aggregations)
        if date_range is not None:
            selector["dateRange"] = list(date_range)
        result = await self._post(
            "/cubejs-api/v1/pre-aggregations/jobs",
            {"action": "post", "selector": selector},
            profile_id=profile_id,
            role=role,
            request_id=request_id,
            timeout_seconds=timeout_seconds,
        )
        if not isinstance(result, list) or any(
            not isinstance(token, str) or not token for token in result
        ):
            raise CubeUnavailableError("Cube returned an invalid refresh response")
        return result

    async def pre_aggregation_job_statuses(
        self,
        tokens: Sequence[str],
        *,
        profile_id: str,
        role: str = "refresh_worker",
        request_id: str | None = None,
        timeout_seconds: float | None = None,
    ) -> list[dict[str, Any]]:
        if not tokens or any(
            not isinstance(token, str) or not token for token in tokens
        ):
            raise ValueError("At least one valid pre-aggregation job token is required")
        result = await self._post(
            "/cubejs-api/v1/pre-aggregations/jobs",
            {"action": "get", "tokens": list(tokens)},
            profile_id=profile_id,
            role=role,
            request_id=request_id,
            timeout_seconds=timeout_seconds,
        )
        if not isinstance(result, list) or any(
            not isinstance(item, dict)
            or not isinstance(item.get("token"), str)
            or not isinstance(item.get("status"), str)
            for item in result
        ):
            raise CubeUnavailableError("Cube returned invalid refresh job statuses")
        return result

    async def wait_for_pre_aggregation_jobs(
        self,
        tokens: Sequence[str],
        *,
        profile_id: str,
        role: str = "refresh_worker",
        request_id: str | None = None,
        timeout_seconds: float = 600.0,
        poll_interval_seconds: float = 2.0,
    ) -> list[dict[str, Any]]:
        if timeout_seconds <= 0:
            raise ValueError("Pre-aggregation wait timeout must be positive")
        if poll_interval_seconds <= 0:
            raise ValueError("Pre-aggregation poll interval must be positive")
        expected_tokens = set(tokens)
        if not expected_tokens or len(expected_tokens) != len(tokens):
            raise ValueError("Pre-aggregation job tokens must be non-empty and unique")
        deadline = time.monotonic() + timeout_seconds
        poll_number = 0
        while True:
            poll_number += 1
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise CubePreAggregationJobError(
                    "Cube pre-aggregation jobs did not finish before the deadline"
                )
            statuses = await self.pre_aggregation_job_statuses(
                tokens,
                profile_id=profile_id,
                role=role,
                request_id=(
                    f"{request_id}-status-{poll_number}" if request_id else None
                ),
                timeout_seconds=remaining,
            )
            statuses_by_token = {item["token"]: item for item in statuses}
            if (
                len(statuses_by_token) != len(statuses)
                or set(statuses_by_token) != expected_tokens
            ):
                raise CubePreAggregationJobError(
                    "Cube returned incomplete pre-aggregation job statuses"
                )
            values = {item["status"] for item in statuses}
            if values == {"done"}:
                return statuses
            if "missing_partition" in values:
                raise CubePreAggregationJobError("Cube pre-aggregation job failed")
            if not values.issubset({"scheduled", "processing", "done"}):
                raise CubePreAggregationJobError(
                    "Cube pre-aggregation job returned an unknown status"
                )
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise CubePreAggregationJobError(
                    "Cube pre-aggregation jobs did not finish before the deadline"
                )
            await asyncio.sleep(min(poll_interval_seconds, remaining))
