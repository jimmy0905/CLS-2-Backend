from __future__ import annotations

import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from jose import jwt

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from infrastructure.integrations.cube import (
    CubeClient,
    CubePreAggregationJobError,
    CubePreAggregationNotReadyError,
    CubeQueryError,
    CubeQueryPendingError,
    CubeUnavailableError,
    create_cube_token,
)


def test_cube_token_is_short_lived_and_scoped_to_profile_and_role() -> None:
    now = datetime(2026, 8, 25, 12, 0, tzinfo=UTC)
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
    assert captured["request_id"] == "query-123-span-1"
    assert captured["body"] == (
        b'{"query":{"measures":["survey_responses.response_count"]}}'
    )


def test_cube_client_retries_continue_wait_with_one_request_span(monkeypatch) -> None:
    requests: list[tuple[str | None, bytes]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append((request.headers.get("X-Request-ID"), request.read()))
        if len(requests) < 3:
            return httpx.Response(200, json={"error": "Continue wait"})
        return httpx.Response(
            200,
            json={"data": [{"survey_responses.survey_count": "5"}]},
        )

    monkeypatch.setattr(
        CubeClient, "_continue_wait_backoff_seconds", (0.001, 0.001, 0.001)
    )
    client = CubeClient(
        "http://cube-api:4000",
        "secret",
        timeout_seconds=1,
        transport=httpx.MockTransport(handler),
    )

    result = asyncio.run(
        client.execute(
            {"measures": ["survey_responses.survey_count"]},
            profile_id="wtchk_cls",
            role="viewer",
            request_id="query-456",
        )
    )

    assert result["data"] == [{"survey_responses.survey_count": "5"}]
    assert [request_id for request_id, _ in requests] == [
        "query-456-span-1",
        "query-456-span-2",
        "query-456-span-3",
    ]
    assert len({body for _, body in requests}) == 1


def test_cube_client_stops_continue_wait_after_bounded_attempts(monkeypatch) -> None:
    request_ids: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        request_ids.append(request.headers.get("X-Request-ID"))
        return httpx.Response(200, json={"error": "Continue wait"})

    monkeypatch.setattr(CubeClient, "_continue_wait_max_attempts", 2)
    monkeypatch.setattr(
        CubeClient, "_continue_wait_backoff_seconds", (0.001, 0.001, 0.001)
    )
    client = CubeClient(
        "http://cube-api:4000",
        "secret",
        timeout_seconds=1,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(CubeQueryPendingError, match="retry deadline"):
        asyncio.run(
            client.execute(
                {},
                profile_id="wtchk_cls",
                role="viewer",
                request_id="query-pending",
            )
        )

    assert request_ids == ["query-pending-span-1", "query-pending-span-2"]


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

    warming = CubeClient(
        "http://cube-api:4000",
        "secret",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={
                    "error": "No pre-aggregation partitions were built yet for the "
                    "pre-aggregation serving this query and this API instance "
                    "wasn't set up to build pre-aggregations."
                },
            )
        ),
    )
    with pytest.raises(CubePreAggregationNotReadyError):
        asyncio.run(warming.execute({}, profile_id="profile", role="viewer"))


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


def test_cube_client_warms_all_rollups_and_waits_for_job_tokens() -> None:
    payloads: list[dict[str, object]] = []
    status_polls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal status_polls
        payload = json.loads(request.read())
        payloads.append(payload)
        if payload["action"] == "post":
            return httpx.Response(200, json=["job-1", "job-2"])
        status_polls += 1
        status = "processing" if status_polls == 1 else "done"
        return httpx.Response(
            200,
            json=[
                {"token": "job-1", "status": status},
                {"token": "job-2", "status": status},
            ],
        )

    client = CubeClient(
        "http://cube-api:4000",
        "secret",
        transport=httpx.MockTransport(handler),
    )
    tokens = asyncio.run(
        client.refresh_pre_aggregations(
            profile_id="wtchk_cls",
            timezone_names=["UTC", "Asia/Hong_Kong"],
            request_id="prewarm-1",
        )
    )
    statuses = asyncio.run(
        client.wait_for_pre_aggregation_jobs(
            tokens,
            profile_id="wtchk_cls",
            request_id="prewarm-1",
            poll_interval_seconds=0.001,
        )
    )

    assert payloads[0] == {
        "action": "post",
        "selector": {
            "contexts": [
                {
                    "securityContext": {
                        "profile": "wtchk_cls",
                        "role": "refresh_worker",
                    }
                }
            ],
            "timezones": ["UTC", "Asia/Hong_Kong"],
        },
    }
    assert [item["status"] for item in statuses] == ["done", "done"]
    assert status_polls == 2


def test_cube_client_fails_closed_on_missing_pre_aggregation_job() -> None:
    client = CubeClient(
        "http://cube-api:4000",
        "secret",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json=[{"token": "job-1", "status": "missing_partition"}],
            )
        ),
    )

    with pytest.raises(CubePreAggregationJobError, match="job failed"):
        asyncio.run(
            client.wait_for_pre_aggregation_jobs(
                ["job-1"],
                profile_id="wtchk_cls",
                poll_interval_seconds=0.001,
            )
        )
