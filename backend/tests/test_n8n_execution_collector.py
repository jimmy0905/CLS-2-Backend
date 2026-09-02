from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from infrastructure.integrations.n8n_execution_collector import (
    CollectorConfig,
    CollectorState,
    N8nExecutionCollector,
    PermanentRequestError,
    RetryableRequestError,
    _execution_event,
)

NOW = datetime(2026, 9, 2, 12, 0, tzinfo=UTC)


def _config(tmp_path: Path, **overrides: object) -> CollectorConfig:
    values: dict[str, object] = {
        "n8n_api_base_url": "http://n8n:5678/api/v1",
        "n8n_api_key": "test-api-key",
        "loki_push_url": "http://loki:3100/loki/api/v1/push",
        "state_path": tmp_path / "collector.sqlite3",
        "max_retries": 0,
    }
    values.update(overrides)
    return CollectorConfig(**values)


def _execution_summary(
    execution_id: str,
    *,
    started_at: str = "2026-09-02T11:58:00.000Z",
) -> dict[str, object]:
    return {
        "id": execution_id,
        "workflowId": "workflow-1",
        "mode": "trigger",
        "startedAt": started_at,
        "stoppedAt": "2026-09-02T11:58:02.000Z",
    }


def _workflow_response() -> dict[str, object]:
    return {
        "data": [{"id": "workflow-1", "name": "Nightly import"}],
        "nextCursor": None,
    }


def test_status_is_read_from_execution_detail_and_terminal_event_reaches_loki(
    tmp_path: Path,
) -> None:
    loki_payloads: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/workflows":
            return httpx.Response(
                200, json={"data": [{"id": 17, "name": "Nightly import"}]}
            )
        if request.url.path == "/api/v1/executions":
            return httpx.Response(
                200,
                json={
                    "data": [{**_execution_summary("42"), "workflowId": 17}],
                    "nextCursor": None,
                },
            )
        if request.url.path == "/api/v1/executions/42":
            assert request.url.params["includeData"] == "false"
            return httpx.Response(
                200,
                json={
                    **_execution_summary("42"),
                    "workflowId": 17,
                    "status": "success",
                },
            )
        if request.url.path == "/loki/api/v1/push":
            loki_payloads.append(json.loads(request.content))
            return httpx.Response(204)
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    collector = N8nExecutionCollector(
        _config(tmp_path),
        transport=httpx.MockTransport(handler),
        sleep=lambda _: None,
    )
    result = collector.run_once(now=NOW)
    collector.close()

    assert result.discovered_count == 1
    assert result.delivered_count == 1
    execution_stream = next(
        stream
        for payload in loki_payloads
        for stream in payload["streams"]
        if stream["stream"]["event"] == "n8n.execution.completed"
    )
    assert execution_stream["stream"] == {
        "event": "n8n.execution.completed",
        "level": "info",
        "service": "n8n",
        "status": "success",
        "workflow_id": "17",
    }
    event = json.loads(execution_stream["values"][0][1])
    assert event == {
        "duration_ms": 2000,
        "error_node": None,
        "error_type": None,
        "execution_id": "42",
        "mode": "trigger",
        "retry_of": None,
        "retry_success_id": None,
        "started_at": "2026-09-02T11:58:00.000Z",
        "status": "success",
        "stopped_at": "2026-09-02T11:58:02.000Z",
        "timestamp": "2026-09-02T11:58:02.000Z",
        "workflow_id": "17",
        "workflow_name": "Nightly import",
    }


def test_pending_execution_is_rechecked_until_it_is_terminal(tmp_path: Path) -> None:
    detail_statuses = iter(["waiting", "success"])
    pushes: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/workflows":
            return httpx.Response(200, json=_workflow_response())
        if request.url.path == "/api/v1/executions":
            return httpx.Response(
                200, json={"data": [_execution_summary("7")], "nextCursor": None}
            )
        if request.url.path == "/api/v1/executions/7":
            return httpx.Response(
                200,
                json={**_execution_summary("7"), "status": next(detail_statuses)},
            )
        if request.url.path == "/loki/api/v1/push":
            pushes.append(json.loads(request.content))
            return httpx.Response(204)
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    collector = N8nExecutionCollector(
        _config(tmp_path),
        transport=httpx.MockTransport(handler),
        sleep=lambda _: None,
    )
    first = collector.run_once(now=NOW)
    second = collector.run_once(now=NOW + timedelta(seconds=30))
    collector.close()

    assert first.delivered_count == 0
    assert first.pending_count == 1
    assert second.delivered_count == 1
    assert second.pending_count == 0
    execution_events = [
        stream
        for payload in pushes
        for stream in payload["streams"]
        if stream["stream"]["event"] == "n8n.execution.completed"
    ]
    assert len(execution_events) == 1


def test_execution_pagination_follows_cursor_and_fetches_each_detail(
    tmp_path: Path,
) -> None:
    requested_cursors: list[str | None] = []
    delivered_ids: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/workflows":
            return httpx.Response(200, json=_workflow_response())
        if request.url.path == "/api/v1/executions":
            cursor = request.url.params.get("cursor")
            requested_cursors.append(cursor)
            if cursor is None:
                return httpx.Response(
                    200,
                    json={
                        "data": [_execution_summary("first")],
                        "nextCursor": "page-two",
                    },
                )
            assert cursor == "page-two"
            return httpx.Response(
                200,
                json={"data": [_execution_summary("second")], "nextCursor": None},
            )
        if request.url.path in {
            "/api/v1/executions/first",
            "/api/v1/executions/second",
        }:
            execution_id = request.url.path.rsplit("/", maxsplit=1)[-1]
            return httpx.Response(
                200, json={**_execution_summary(execution_id), "status": "success"}
            )
        if request.url.path == "/loki/api/v1/push":
            for stream in json.loads(request.content)["streams"]:
                if stream["stream"]["event"] == "n8n.execution.completed":
                    delivered_ids.extend(
                        json.loads(value[1])["execution_id"]
                        for value in stream["values"]
                    )
            return httpx.Response(204)
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    collector = N8nExecutionCollector(
        _config(tmp_path),
        transport=httpx.MockTransport(handler),
        sleep=lambda _: None,
    )
    result = collector.run_once(now=NOW)
    collector.close()

    assert requested_cursors == [None, "page-two"]
    assert result.discovered_count == 2
    assert delivered_ids == ["first", "second"]


def test_workflow_name_cache_survives_workflow_deletion(tmp_path: Path) -> None:
    workflow_calls = 0
    execution_statuses = iter(["waiting", "success"])
    emitted_events: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal workflow_calls
        if request.url.path == "/api/v1/workflows":
            workflow_calls += 1
            return httpx.Response(
                200,
                json=_workflow_response() if workflow_calls == 1 else {"data": []},
            )
        if request.url.path == "/api/v1/executions":
            return httpx.Response(
                200, json={"data": [_execution_summary("8")], "nextCursor": None}
            )
        if request.url.path == "/api/v1/executions/8":
            return httpx.Response(
                200,
                json={
                    **_execution_summary("8"),
                    "status": next(execution_statuses),
                },
            )
        if request.url.path == "/loki/api/v1/push":
            for stream in json.loads(request.content)["streams"]:
                if stream["stream"]["event"] == "n8n.execution.completed":
                    emitted_events.extend(
                        json.loads(value[1]) for value in stream["values"]
                    )
            return httpx.Response(204)
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    collector = N8nExecutionCollector(
        _config(tmp_path, workflow_refresh_seconds=1),
        transport=httpx.MockTransport(handler),
        sleep=lambda _: None,
    )
    collector.run_once(now=NOW)
    collector.run_once(now=NOW + timedelta(seconds=1))
    collector.close()

    assert workflow_calls == 2
    assert emitted_events[0]["workflow_name"] == "Nightly import"


@pytest.mark.parametrize(
    ("reported_status", "expected_status", "expected_level"),
    [
        ("success", "success", "info"),
        ("error", "error", "error"),
        ("canceled", "canceled", "info"),
        ("crashed", "crashed", "error"),
        ("unrecognized", "unknown", "info"),
    ],
)
def test_terminal_event_normalization_and_serialization_are_deterministic(
    reported_status: str,
    expected_status: str,
    expected_level: str,
) -> None:
    payload = {
        **_execution_summary("12"),
        "status": reported_status,
        "retryOf": 1,
        "retrySuccessId": 13,
    }
    first = _execution_event(payload, workflow_name="Nightly import", observed_at=NOW)
    second = _execution_event(payload, workflow_name="Nightly import", observed_at=NOW)

    event, labels, timestamp_ns = first
    assert first == second
    assert event["status"] == expected_status
    assert event["duration_ms"] == 2000
    assert event["retry_of"] == "1"
    assert event["retry_success_id"] == "13"
    assert labels["level"] == expected_level
    assert labels["status"] == expected_status
    assert timestamp_ns == "1788350282000000000"


def test_failed_execution_only_retains_allowlisted_error_metadata(
    tmp_path: Path,
) -> None:
    captured: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/workflows":
            return httpx.Response(200, json=_workflow_response())
        if request.url.path == "/api/v1/executions":
            return httpx.Response(
                200, json={"data": [_execution_summary("99")], "nextCursor": None}
            )
        if request.url.path == "/api/v1/executions/99":
            if request.url.params["includeData"] == "false":
                return httpx.Response(
                    200, json={**_execution_summary("99"), "status": "error"}
                )
            return httpx.Response(
                200,
                json={
                    **_execution_summary("99"),
                    "status": "error",
                    "data": {
                        "resultData": {
                            "lastNodeExecuted": "Upload customer file",
                            "error": {
                                "name": "NodeApiError",
                                "message": "Bearer very-secret-token",
                                "stack": "https://example.test/?api_key=very-secret-token",
                                "node": {"name": "Upload customer file"},
                            },
                            "runData": {"contains": "customer payload"},
                        }
                    },
                },
            )
        if request.url.path == "/loki/api/v1/push":
            for stream in json.loads(request.content)["streams"]:
                if stream["stream"]["event"] == "n8n.execution.completed":
                    captured.extend(value[1] for value in stream["values"])
            return httpx.Response(204)
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    collector = N8nExecutionCollector(
        _config(tmp_path),
        transport=httpx.MockTransport(handler),
        sleep=lambda _: None,
    )
    collector.run_once(now=NOW)
    collector.close()

    assert len(captured) == 1
    event = json.loads(captured[0])
    assert event["error_type"] == "NodeApiError"
    assert event["error_node"] == "Upload customer file"
    for forbidden in (
        "very-secret-token",
        "customer payload",
        "https://example.test",
        "message",
        "stack",
        "runData",
    ):
        assert forbidden not in captured[0]


def test_initial_backfill_stops_when_execution_is_older_than_cutoff(
    tmp_path: Path,
) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/api/v1/workflows":
            return httpx.Response(200, json=_workflow_response())
        if request.url.path == "/api/v1/executions":
            return httpx.Response(
                200,
                json={
                    "data": [
                        _execution_summary("new"),
                        _execution_summary(
                            "old",
                            started_at="2026-08-01T00:00:00.000Z",
                        ),
                    ],
                    "nextCursor": "should-not-be-requested",
                },
            )
        if request.url.path == "/api/v1/executions/new":
            return httpx.Response(
                200, json={**_execution_summary("new"), "status": "success"}
            )
        if request.url.path == "/loki/api/v1/push":
            return httpx.Response(204)
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    collector = N8nExecutionCollector(
        _config(tmp_path, initial_backfill_hours=24),
        transport=httpx.MockTransport(handler),
        sleep=lambda _: None,
    )
    result = collector.run_once(now=NOW)
    collector.close()

    assert result.discovered_count == 1
    execution_list_requests = [
        request for request in requests if request.url.path == "/api/v1/executions"
    ]
    assert len(execution_list_requests) == 1


@pytest.mark.parametrize("loki_status", [400, 503])
def test_loki_failure_keeps_deterministic_outbox_event_for_replay(
    tmp_path: Path, loki_status: int
) -> None:
    first_pushes: list[dict[str, object]] = []
    replay_pushes: list[dict[str, object]] = []

    def n8n_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/workflows":
            return httpx.Response(200, json=_workflow_response())
        if request.url.path == "/api/v1/executions":
            return httpx.Response(
                200, json={"data": [_execution_summary("5")], "nextCursor": None}
            )
        if request.url.path == "/api/v1/executions/5":
            return httpx.Response(
                200, json={**_execution_summary("5"), "status": "success"}
            )
        raise AssertionError(f"Unexpected n8n request: {request.method} {request.url}")

    def failing_handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "n8n":
            return n8n_handler(request)
        first_pushes.append(json.loads(request.content))
        return httpx.Response(loki_status)

    first = N8nExecutionCollector(
        _config(tmp_path),
        transport=httpx.MockTransport(failing_handler),
        sleep=lambda _: None,
    )
    first_result = first.run_once(now=NOW)
    first.close()

    def replay_handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "n8n":
            return n8n_handler(request)
        replay_pushes.append(json.loads(request.content))
        return httpx.Response(204)

    replay = N8nExecutionCollector(
        _config(tmp_path),
        transport=httpx.MockTransport(replay_handler),
        sleep=lambda _: None,
    )
    replay_result = replay.run_once(now=NOW + timedelta(seconds=30))
    replay.close()

    assert first_result.delivered_count == 0
    assert replay_result.delivered_count == 1
    first_event = next(
        stream
        for payload in first_pushes
        for stream in payload["streams"]
        if stream["stream"]["event"] == "n8n.execution.completed"
    )
    replay_event = next(
        stream
        for payload in replay_pushes
        for stream in payload["streams"]
        if stream["stream"]["event"] == "n8n.execution.completed"
    )
    assert first_event == replay_event


@pytest.mark.parametrize("status_code", [401, 403])
def test_n8n_authentication_rejection_does_not_create_state(
    tmp_path: Path, status_code: int
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/workflows"
        return httpx.Response(status_code)

    collector = N8nExecutionCollector(
        _config(tmp_path),
        transport=httpx.MockTransport(handler),
        sleep=lambda _: None,
    )
    try:
        with pytest.raises(PermanentRequestError, match="authentication"):
            collector.run_once(now=NOW)
        assert collector.state.get_execution("42") is None
    finally:
        collector.close()


def test_failure_metadata_authentication_rejection_does_not_create_state(
    tmp_path: Path,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/workflows":
            return httpx.Response(200, json=_workflow_response())
        if request.url.path == "/api/v1/executions":
            return httpx.Response(
                200, json={"data": [_execution_summary("99")], "nextCursor": None}
            )
        if request.url.path == "/api/v1/executions/99":
            if request.url.params["includeData"] == "false":
                return httpx.Response(
                    200, json={**_execution_summary("99"), "status": "error"}
                )
            return httpx.Response(403)
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    collector = N8nExecutionCollector(
        _config(tmp_path),
        transport=httpx.MockTransport(handler),
        sleep=lambda _: None,
    )
    try:
        with pytest.raises(PermanentRequestError, match="authentication"):
            collector.run_once(now=NOW)
        assert collector.state.get_execution("99") is None
    finally:
        collector.close()


def test_n8n_rate_limit_retries_before_success(tmp_path: Path) -> None:
    requests = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        assert request.url.path == "/api/v1/workflows"
        if requests == 1:
            return httpx.Response(429)
        return httpx.Response(200, json=_workflow_response())

    collector = N8nExecutionCollector(
        _config(tmp_path, max_retries=1),
        transport=httpx.MockTransport(handler),
        sleep=lambda _: None,
    )
    try:
        assert collector.n8n.list_workflows() == _workflow_response()
    finally:
        collector.close()

    assert requests == 2


@pytest.mark.parametrize(
    "response_or_error",
    [
        pytest.param(httpx.Response(200, content=b"{"), id="malformed-json"),
        pytest.param(httpx.ConnectTimeout("n8n is down"), id="n8n-timeout"),
    ],
)
def test_n8n_invalid_or_unavailable_response_is_retryable(
    tmp_path: Path, response_or_error: httpx.Response | httpx.RequestError
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/workflows"
        if isinstance(response_or_error, httpx.RequestError):
            raise response_or_error
        return response_or_error

    collector = N8nExecutionCollector(
        _config(tmp_path),
        transport=httpx.MockTransport(handler),
        sleep=lambda _: None,
    )
    try:
        with pytest.raises(RetryableRequestError):
            collector.n8n.list_workflows()
    finally:
        collector.close()


def test_health_state_requires_a_recent_successful_loki_poll(tmp_path: Path) -> None:
    state = CollectorState(tmp_path / "collector.sqlite3")
    try:
        assert not state.healthy(NOW, poll_interval_seconds=30)
        state.mark_successful_poll(NOW)
        assert state.healthy(NOW + timedelta(seconds=90), poll_interval_seconds=30)
        assert not state.healthy(NOW + timedelta(seconds=91), poll_interval_seconds=30)
    finally:
        state.close()


def test_collector_configuration_requires_an_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("N8N_API_KEY", raising=False)

    with pytest.raises(ValueError, match="N8N_API_KEY is required"):
        CollectorConfig.from_environment()
