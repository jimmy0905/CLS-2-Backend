from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
import sys

import httpx
from jose import jwt
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utils.analytics_cube import (
    CubeClient,
    CubeQueryError,
    CubeUnavailableError,
    create_cube_token,
)


def test_cube_token_is_short_lived_and_scoped_to_profile_and_role() -> None:
    now = datetime(2026, 8, 25, 12, 0, tzinfo=timezone.utc)
    token = create_cube_token(
        "test-secret",
        profile_id="wtchk_cls",
        role="viewer",
        expires_in_seconds=60,
        now=now,
    )

    claims = jwt.decode(
        token,
        "test-secret",
        algorithms=["HS256"],
        options={"verify_exp": False, "verify_aud": False},
    )
    assert claims["sub"] == "analytics:wtchk_cls"
    assert claims["profile_id"] == "wtchk_cls"
    assert claims["role"] == "viewer"
    assert claims["securityContext"] == {
        "profile": "wtchk_cls",
        "role": "viewer",
    }
    assert claims["iat"] == int(now.timestamp())
    assert claims["exp"] == int(now.timestamp()) + 60
    assert claims["aud"] == "cube"


def test_cube_client_executes_load_query_with_defense_in_depth_token() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers.get("Authorization")
        captured["request_id"] = request.headers.get("X-Request-ID")
        captured["body"] = request.read()
        return httpx.Response(
            200,
            json={"data": [{"survey_responses.response_count": "2"}]},
        )

    client = CubeClient(
        "http://cube-api:4000",
        "test-secret",
        transport=httpx.MockTransport(handler),
    )
    result = asyncio.run(
        client.execute(
            {"measures": ["survey_responses.response_count"]},
            profile_id="wtchk_cls",
            role="viewer",
            request_id="query-123",
        )
    )

    assert result["data"] == [{"survey_responses.response_count": "2"}]
    assert captured["url"] == "http://cube-api:4000/cubejs-api/v1/load"
    assert str(captured["authorization"]).startswith("Bearer ")
    assert captured["request_id"] == "query-123"
    assert captured["body"] == b'{"query":{"measures":["survey_responses.response_count"]}}'


def test_cube_client_distinguishes_rejected_and_unavailable_queries() -> None:
    rejected = CubeClient(
        "http://cube-api:4000",
        "secret",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(400, json={"error": "Unknown member"})
        ),
    )
    with pytest.raises(CubeQueryError, match="Unknown member"):
        asyncio.run(rejected.execute({}, profile_id="profile", role="viewer"))

    database_unavailable = CubeClient(
        "http://cube-api:4000",
        "secret",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                400,
                json={"error": "Unable to connect to the database: SSL is disabled"},
            )
        ),
    )
    with pytest.raises(CubeUnavailableError):
        asyncio.run(
            database_unavailable.execute({}, profile_id="profile", role="viewer")
        )

    unavailable_envelope = CubeClient(
        "http://cube-api:4000",
        "secret",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={"error": "Unable to connect to the database"},
            )
        ),
    )
    with pytest.raises(CubeUnavailableError):
        asyncio.run(
            unavailable_envelope.execute({}, profile_id="profile", role="viewer")
        )

    unavailable = CubeClient(
        "http://cube-api:4000",
        "secret",
        transport=httpx.MockTransport(
            lambda request: (_ for _ in ()).throw(httpx.ConnectError("down"))
        ),
    )
    with pytest.raises(CubeUnavailableError):
        asyncio.run(unavailable.execute({}, profile_id="profile", role="viewer"))


def test_cube_client_requests_targeted_pre_aggregation_refresh() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["payload"] = request.read()
        return httpx.Response(200, json=["job-1", "job-2"])

    client = CubeClient(
        "http://cube-api:4000",
        "secret",
        transport=httpx.MockTransport(handler),
    )
    result = asyncio.run(
        client.refresh_pre_aggregations(
            profile_id="wtchk_cls",
            date_range=["2026-07-01", "2026-07-31"],
            pre_aggregations=["survey_responses.daily_core"],
        )
    )

    assert result == ["job-1", "job-2"]
    assert captured["url"] == (
        "http://cube-api:4000/cubejs-api/v1/pre-aggregations/jobs"
    )
    assert captured["payload"] == (
        b'{"action":"post","selector":{"contexts":[{"securityContext":'
        b'{"profile":"wtchk_cls","role":"refresh_worker"}}],"timezones":'
        b'["UTC"],"preAggregations":["survey_responses.daily_core"],'
        b'"dateRange":["2026-07-01","2026-07-31"]}}'
    )
