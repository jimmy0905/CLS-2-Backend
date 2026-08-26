"""Private-network Cube API client with short-lived profile-scoped JWTs."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Sequence

import httpx
from jose import jwt

from utils.analytics import AnalyticsValidationError, validate_identifier


class CubeClientError(RuntimeError):
    """Base error raised by the Cube transport abstraction."""


class CubeQueryError(CubeClientError):
    """Cube rejected a governed query or refresh request."""


class CubeUnavailableError(CubeClientError):
    """Cube could not service a request because it is unavailable."""


def _cube_error(error: object) -> CubeClientError:
    """Classify Cube's error envelope without exposing it to API callers.

    Cube can report an upstream PostgreSQL outage as either a 4xx response or
    an HTTP-200 payload containing ``error``.  These are service failures, not
    invalid semantic requests, and must map to the analytics 503 contract.
    """

    detail = str(error or "Cube rejected the analytics query")
    normalized = detail.lower()
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
    issued_at = now or datetime.now(timezone.utc)
    if issued_at.tzinfo is None:
        issued_at = issued_at.replace(tzinfo=timezone.utc)
    issued_at = issued_at.astimezone(timezone.utc)
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
    ) -> dict[str, Any] | list[Any]:
        token = create_cube_token(self.api_secret, profile_id, role)
        headers = {"Authorization": f"Bearer {token}"}
        if request_id:
            headers["X-Request-ID"] = request_id
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout_seconds,
                transport=self.transport,
            ) as client:
                response = await client.post(
                    self.base_url + path,
                    json=dict(payload),
                    headers=headers,
                )
        except httpx.HTTPError as error:
            raise CubeUnavailableError("Cube analytics service is unavailable") from error

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
        result = await self._post(
            "/cubejs-api/v1/load",
            {"query": dict(query)},
            profile_id=profile_id,
            role=role,
            request_id=request_id,
        )
        if not isinstance(result, dict):
            raise CubeUnavailableError("Cube returned an invalid query response")
        return result

    async def refresh_pre_aggregations(
        self,
        *,
        profile_id: str,
        role: str = "refresh_worker",
        date_range: Sequence[str],
        pre_aggregations: Sequence[str],
        request_id: str | None = None,
        timezone_name: str = "UTC",
    ) -> dict[str, Any] | list[Any]:
        if len(date_range) != 2:
            raise ValueError("Pre-aggregation refresh date range requires two values")
        if not pre_aggregations:
            raise ValueError("At least one pre-aggregation is required")
        for pre_aggregation in pre_aggregations:
            parts = pre_aggregation.split(".")
            if len(parts) != 2:
                raise AnalyticsValidationError("Invalid pre-aggregation name")
            for part in parts:
                validate_identifier(part)
        selector = {
            "contexts": [{"securityContext": {"profile": profile_id, "role": role}}],
            "timezones": [timezone_name],
            "preAggregations": list(pre_aggregations),
            "dateRange": list(date_range),
        }
        result = await self._post(
            "/cubejs-api/v1/pre-aggregations/jobs",
            {"action": "post", "selector": selector},
            profile_id=profile_id,
            role=role,
            request_id=request_id,
        )
        if not isinstance(result, (dict, list)):
            raise CubeUnavailableError("Cube returned an invalid refresh response")
        return result
