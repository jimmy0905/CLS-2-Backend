"""Poll n8n execution summaries and publish safe operational events to Loki."""

from __future__ import annotations

import argparse
import json
import logging
import os
import random
import sqlite3
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

LOGGER = logging.getLogger("n8n_execution_collector")

PENDING_STATUSES = frozenset({"new", "running", "waiting"})
TERMINAL_STATUSES = frozenset({"success", "error", "canceled", "crashed", "unknown"})
EXECUTION_EVENT = "n8n.execution.completed"
POLL_EVENT = "n8n.collector.poll"
DEFAULT_STATE_PATH = Path("/var/lib/n8n-execution-collector/collector.sqlite3")


class CollectorRequestError(RuntimeError):
    """Base class for a request whose response is safe to report generically."""


class RetryableRequestError(CollectorRequestError):
    """Raised when a transient upstream failure should leave the outbox intact."""


class PermanentRequestError(CollectorRequestError):
    """Raised when an upstream request cannot succeed without a configuration change."""


@dataclass(frozen=True)
class CollectorConfig:
    """Runtime configuration for the execution collector."""

    n8n_api_base_url: str
    n8n_api_key: str
    loki_push_url: str
    state_path: Path = DEFAULT_STATE_PATH
    poll_interval_seconds: int = 30
    initial_backfill_hours: int = 720
    http_timeout_seconds: float = 10.0
    workflow_refresh_seconds: int = 3600
    max_retries: int = 3
    retry_base_seconds: float = 0.5

    def __post_init__(self) -> None:
        if not self.n8n_api_base_url:
            raise ValueError("N8N_API_BASE_URL is required")
        if not self.n8n_api_key:
            raise ValueError("N8N_API_KEY is required")
        if not self.loki_push_url:
            raise ValueError("LOKI_PUSH_URL is required")
        if self.poll_interval_seconds <= 0:
            raise ValueError("N8N_POLL_INTERVAL_SECONDS must be positive")
        if self.initial_backfill_hours <= 0:
            raise ValueError("N8N_INITIAL_BACKFILL_HOURS must be positive")
        if self.http_timeout_seconds <= 0:
            raise ValueError("N8N_HTTP_TIMEOUT_SECONDS must be positive")
        if self.workflow_refresh_seconds <= 0:
            raise ValueError("N8N_WORKFLOW_REFRESH_SECONDS must be positive")
        if self.max_retries < 0:
            raise ValueError("N8N_COLLECTOR_MAX_RETRIES cannot be negative")

    @classmethod
    def from_environment(cls) -> CollectorConfig:
        """Load explicit collector settings without logging their values."""

        return cls(
            n8n_api_base_url=os.environ.get(
                "N8N_API_BASE_URL", "http://n8n:5678/api/v1"
            ).rstrip("/"),
            n8n_api_key=os.environ.get("N8N_API_KEY", ""),
            loki_push_url=os.environ.get(
                "LOKI_PUSH_URL", "http://loki:3100/loki/api/v1/push"
            ),
            state_path=Path(
                os.environ.get("N8N_COLLECTOR_STATE_PATH", DEFAULT_STATE_PATH)
            ),
            poll_interval_seconds=_environment_int("N8N_POLL_INTERVAL_SECONDS", 30),
            initial_backfill_hours=_environment_int("N8N_INITIAL_BACKFILL_HOURS", 720),
            http_timeout_seconds=_environment_float("N8N_HTTP_TIMEOUT_SECONDS", 10.0),
            workflow_refresh_seconds=_environment_int(
                "N8N_WORKFLOW_REFRESH_SECONDS", 3600
            ),
            max_retries=_environment_int("N8N_COLLECTOR_MAX_RETRIES", 3),
            retry_base_seconds=_environment_float(
                "N8N_COLLECTOR_RETRY_BASE_SECONDS", 0.5
            ),
        )


@dataclass(frozen=True)
class OutboxEvent:
    """A persisted execution event that is ready for Loki delivery."""

    execution_id: str
    labels: dict[str, str]
    timestamp_ns: str
    line: str


@dataclass(frozen=True)
class PollResult:
    """Safe, aggregate information about one collector polling cycle."""

    discovered_count: int
    pending_count: int
    delivered_count: int
    api_latency_ms: int
    successful: bool


def _environment_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    if value in (None, ""):
        return default
    try:
        return int(value)
    except ValueError as error:
        raise ValueError(f"{name} must be an integer") from error


def _environment_float(name: str, default: float) -> float:
    value = os.environ.get(name)
    if value in (None, ""):
        return default
    try:
        return float(value)
    except ValueError as error:
        raise ValueError(f"{name} must be a number") from error


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _format_timestamp(value: datetime) -> str:
    return (
        value.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    )


def _timestamp_nanoseconds(value: datetime) -> str:
    utc_value = value.astimezone(UTC)
    seconds = int(utc_value.timestamp())
    return str(seconds * 1_000_000_000 + utc_value.microsecond * 1_000)


def _safe_string(value: object, *, max_length: int = 256) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = " ".join(value.split())
    return normalized[:max_length] if normalized else None


def _safe_identifier(value: object) -> str | None:
    """Normalize n8n's string-or-number identifiers without accepting objects."""

    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return None
    normalized = str(value).strip()
    return normalized or None


def _execution_id(payload: Mapping[str, object]) -> str | None:
    return _safe_identifier(payload.get("id"))


def _execution_status(payload: Mapping[str, object]) -> str:
    value = payload.get("status")
    if not isinstance(value, str):
        return "unknown"
    normalized = value.lower().strip()
    if normalized in PENDING_STATUSES | TERMINAL_STATUSES:
        return normalized
    return "unknown"


def _extract_error_metadata(
    payload: Mapping[str, object],
) -> tuple[str | None, str | None]:
    """Extract only the error class and node name, never error content or node data."""

    data = payload.get("data")
    if not isinstance(data, Mapping):
        return None, None
    result_data = data.get("resultData")
    if not isinstance(result_data, Mapping):
        return None, None

    error_type: str | None = None
    error_node: str | None = _safe_string(result_data.get("lastNodeExecuted"))
    error = result_data.get("error")
    if isinstance(error, Mapping):
        error_type = _safe_string(error.get("name")) or _safe_string(error.get("type"))
        if error_node is None:
            node = error.get("node")
            if isinstance(node, Mapping):
                error_node = _safe_string(node.get("name"))
            else:
                error_node = _safe_string(node)
    return error_type, error_node


def _duration_ms(
    started_at: datetime | None, stopped_at: datetime | None
) -> int | None:
    if started_at is None or stopped_at is None:
        return None
    duration = int((stopped_at - started_at).total_seconds() * 1000)
    return max(duration, 0)


def _execution_event(
    payload: Mapping[str, object],
    *,
    workflow_name: str,
    observed_at: datetime,
    error_type: str | None = None,
    error_node: str | None = None,
) -> tuple[dict[str, object], dict[str, str], str]:
    """Build a stable, safe execution event and its Loki labels."""

    execution_id = _execution_id(payload)
    if execution_id is None:
        raise ValueError("n8n execution response is missing an id")
    workflow_id = _safe_identifier(payload.get("workflowId")) or "unknown"
    status = _execution_status(payload)
    started_value = _safe_string(payload.get("startedAt"))
    stopped_value = _safe_string(payload.get("stoppedAt"))
    started_at = _parse_timestamp(started_value)
    stopped_at = _parse_timestamp(stopped_value)
    event_time = stopped_at or started_at or observed_at
    event_timestamp = stopped_value or started_value or _format_timestamp(observed_at)
    retry_of = _safe_identifier(payload.get("retryOf"))
    retry_success_id = _safe_identifier(payload.get("retrySuccessId"))
    level = "error" if status in {"error", "crashed"} else "info"
    event = {
        "timestamp": event_timestamp,
        "execution_id": execution_id,
        "workflow_id": workflow_id,
        "workflow_name": workflow_name,
        "status": status,
        "mode": _safe_string(payload.get("mode")),
        "started_at": started_value,
        "stopped_at": stopped_value,
        "duration_ms": _duration_ms(started_at, stopped_at),
        "retry_of": retry_of,
        "retry_success_id": retry_success_id,
        "error_type": error_type,
        "error_node": error_node,
    }
    labels = {
        "event": EXECUTION_EVENT,
        "level": level,
        "service": "n8n",
        "status": status,
        "workflow_id": workflow_id,
    }
    return event, labels, _timestamp_nanoseconds(event_time)


class CollectorState:
    """SQLite-backed execution state and at-least-once Loki outbox."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.row_factory = sqlite3.Row
        self._initialize()

    def close(self) -> None:
        self.connection.close()

    def _initialize(self) -> None:
        self.connection.executescript(
            """
            PRAGMA journal_mode = WAL;
            CREATE TABLE IF NOT EXISTS metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS workflows (
                workflow_id TEXT PRIMARY KEY,
                workflow_name TEXT NOT NULL,
                refreshed_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS executions (
                execution_id TEXT PRIMARY KEY,
                workflow_id TEXT NOT NULL,
                workflow_name TEXT NOT NULL,
                status TEXT NOT NULL,
                observed_at TEXT NOT NULL,
                event_timestamp_ns TEXT,
                event_line TEXT,
                delivered_at TEXT
            );
            CREATE INDEX IF NOT EXISTS executions_pending_idx
                ON executions (status, delivered_at);
            """
        )
        self.connection.commit()

    def get_metadata(self, key: str) -> str | None:
        row = self.connection.execute(
            "SELECT value FROM metadata WHERE key = ?", (key,)
        ).fetchone()
        return str(row["value"]) if row else None

    def set_metadata(self, key: str, value: str) -> None:
        self.connection.execute(
            """
            INSERT INTO metadata (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, value),
        )
        self.connection.commit()

    def get_execution(self, execution_id: str) -> sqlite3.Row | None:
        return self.connection.execute(
            "SELECT * FROM executions WHERE execution_id = ?", (execution_id,)
        ).fetchone()

    def pending_execution_ids(self) -> list[str]:
        rows = self.connection.execute(
            """
            SELECT execution_id FROM executions
            WHERE status IN ('new', 'running', 'waiting') AND delivered_at IS NULL
            ORDER BY observed_at ASC
            """
        ).fetchall()
        return [str(row["execution_id"]) for row in rows]

    def store_pending(
        self,
        payload: Mapping[str, object],
        *,
        workflow_name: str,
        observed_at: datetime,
    ) -> None:
        execution_id = _execution_id(payload)
        if execution_id is None:
            raise ValueError("n8n execution response is missing an id")
        existing = self.get_execution(execution_id)
        if existing and existing["delivered_at"] is not None:
            return
        self.connection.execute(
            """
            INSERT INTO executions (
                execution_id, workflow_id, workflow_name, status, observed_at,
                event_timestamp_ns, event_line, delivered_at
            ) VALUES (?, ?, ?, ?, ?, NULL, NULL, NULL)
            ON CONFLICT(execution_id) DO UPDATE SET
                workflow_id = excluded.workflow_id,
                workflow_name = excluded.workflow_name,
                status = excluded.status,
                observed_at = excluded.observed_at
            WHERE executions.delivered_at IS NULL
            """,
            (
                execution_id,
                _safe_identifier(payload.get("workflowId")) or "unknown",
                workflow_name,
                _execution_status(payload),
                _format_timestamp(observed_at),
            ),
        )
        self.connection.commit()

    def store_terminal(
        self,
        payload: Mapping[str, object],
        *,
        workflow_name: str,
        observed_at: datetime,
        error_type: str | None,
        error_node: str | None,
    ) -> None:
        event, _, timestamp_ns = _execution_event(
            payload,
            workflow_name=workflow_name,
            observed_at=observed_at,
            error_type=error_type,
            error_node=error_node,
        )
        execution_id = str(event["execution_id"])
        existing = self.get_execution(execution_id)
        if existing and existing["delivered_at"] is not None:
            return
        line = json.dumps(
            event, ensure_ascii=False, separators=(",", ":"), sort_keys=True
        )
        self.connection.execute(
            """
            INSERT INTO executions (
                execution_id, workflow_id, workflow_name, status, observed_at,
                event_timestamp_ns, event_line, delivered_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL)
            ON CONFLICT(execution_id) DO UPDATE SET
                workflow_id = excluded.workflow_id,
                workflow_name = excluded.workflow_name,
                status = excluded.status,
                observed_at = excluded.observed_at,
                event_timestamp_ns = excluded.event_timestamp_ns,
                event_line = excluded.event_line
            WHERE executions.delivered_at IS NULL
            """,
            (
                execution_id,
                str(event["workflow_id"]),
                workflow_name,
                str(event["status"]),
                _format_timestamp(observed_at),
                timestamp_ns,
                line,
            ),
        )
        self.connection.commit()

    def pending_events(self) -> list[OutboxEvent]:
        rows = self.connection.execute(
            """
            SELECT execution_id, workflow_id, status, event_timestamp_ns, event_line
            FROM executions
            WHERE event_line IS NOT NULL AND delivered_at IS NULL
            ORDER BY event_timestamp_ns ASC, execution_id ASC
            """
        ).fetchall()
        events: list[OutboxEvent] = []
        for row in rows:
            status = str(row["status"])
            events.append(
                OutboxEvent(
                    execution_id=str(row["execution_id"]),
                    labels={
                        "event": EXECUTION_EVENT,
                        "level": "error" if status in {"error", "crashed"} else "info",
                        "service": "n8n",
                        "status": status,
                        "workflow_id": str(row["workflow_id"]),
                    },
                    timestamp_ns=str(row["event_timestamp_ns"]),
                    line=str(row["event_line"]),
                )
            )
        return events

    def mark_delivered(self, execution_ids: list[str], delivered_at: datetime) -> None:
        if not execution_ids:
            return
        placeholders = ",".join("?" for _ in execution_ids)
        statement = (
            "UPDATE executions SET delivered_at = ? "
            f"WHERE execution_id IN ({placeholders})"
        )
        self.connection.execute(
            statement,
            (_format_timestamp(delivered_at), *execution_ids),
        )
        self.connection.commit()

    def set_workflow(
        self, workflow_id: str, workflow_name: str, refreshed_at: datetime
    ) -> None:
        self.connection.execute(
            """
            INSERT INTO workflows (workflow_id, workflow_name, refreshed_at)
            VALUES (?, ?, ?)
            ON CONFLICT(workflow_id) DO UPDATE SET
                workflow_name = excluded.workflow_name,
                refreshed_at = excluded.refreshed_at
            """,
            (workflow_id, workflow_name, _format_timestamp(refreshed_at)),
        )
        self.connection.commit()

    def workflow_name(self, workflow_id: str) -> str | None:
        row = self.connection.execute(
            "SELECT workflow_name FROM workflows WHERE workflow_id = ?", (workflow_id,)
        ).fetchone()
        return str(row["workflow_name"]) if row else None

    def workflow_refresh_due(self, now: datetime, refresh_seconds: int) -> bool:
        refreshed_at = _parse_timestamp(self.get_metadata("workflows_refreshed_at"))
        return refreshed_at is None or now - refreshed_at >= timedelta(
            seconds=refresh_seconds
        )

    def mark_workflows_refreshed(self, now: datetime) -> None:
        self.set_metadata("workflows_refreshed_at", _format_timestamp(now))

    def initial_backfill_complete(self) -> bool:
        return self.get_metadata("initial_backfill_complete") == "true"

    def mark_initial_backfill_complete(self) -> None:
        self.set_metadata("initial_backfill_complete", "true")

    def mark_successful_poll(self, now: datetime) -> None:
        self.set_metadata("last_successful_poll", _format_timestamp(now))

    def healthy(self, now: datetime, poll_interval_seconds: int) -> bool:
        last_successful_poll = _parse_timestamp(
            self.get_metadata("last_successful_poll")
        )
        if last_successful_poll is None:
            return False
        return now - last_successful_poll <= timedelta(
            seconds=poll_interval_seconds * 3
        )

    def prune_delivered(self, cutoff: datetime) -> None:
        self.connection.execute(
            "DELETE FROM executions "
            "WHERE delivered_at IS NOT NULL AND delivered_at < ?",
            (_format_timestamp(cutoff),),
        )
        self.connection.commit()


class N8nClient:
    """n8n public-API client that never includes response bodies in raised errors."""

    def __init__(
        self,
        config: CollectorConfig,
        client: httpx.Client,
        *,
        sleep: Callable[[float], None],
    ) -> None:
        self.base_url = config.n8n_api_base_url.rstrip("/")
        self.api_key = config.n8n_api_key
        self.client = client
        self.max_retries = config.max_retries
        self.retry_base_seconds = config.retry_base_seconds
        self.sleep = sleep

    def list_executions(self, cursor: str | None = None) -> dict[str, object]:
        params: dict[str, str] = {"includeData": "false", "limit": "100"}
        if cursor:
            params["cursor"] = cursor
        return self._get_json("/executions", params=params)

    def get_execution(
        self, execution_id: str, *, include_data: bool
    ) -> dict[str, object]:
        return self._get_json(
            f"/executions/{execution_id}",
            params={"includeData": str(include_data).lower()},
        )

    def list_workflows(self, cursor: str | None = None) -> dict[str, object]:
        params: dict[str, str] = {"limit": "100"}
        if cursor:
            params["cursor"] = cursor
        return self._get_json("/workflows", params=params)

    def _get_json(self, path: str, *, params: Mapping[str, str]) -> dict[str, object]:
        response = self._request(
            "GET",
            self.base_url + path,
            params=params,
            headers={"X-N8N-API-KEY": self.api_key, "Accept": "application/json"},
            upstream="n8n",
        )
        try:
            payload = response.json()
        except ValueError as error:
            raise RetryableRequestError("n8n returned invalid JSON") from error
        if not isinstance(payload, dict):
            raise RetryableRequestError("n8n returned an invalid response")
        return payload

    def _request(
        self,
        method: str,
        url: str,
        *,
        params: Mapping[str, str] | None = None,
        headers: Mapping[str, str] | None = None,
        json_payload: Mapping[str, object] | None = None,
        upstream: str,
    ) -> httpx.Response:
        for attempt in range(self.max_retries + 1):
            try:
                response = self.client.request(
                    method,
                    url,
                    params=params,
                    headers=headers,
                    json=json_payload,
                )
            except httpx.RequestError as error:
                if attempt == self.max_retries:
                    raise RetryableRequestError(f"{upstream} is unavailable") from error
                self._sleep_before_retry(attempt)
                continue

            if response.status_code in {401, 403}:
                raise PermanentRequestError(
                    f"{upstream} rejected collector authentication"
                )
            if response.status_code == 429 or response.status_code >= 500:
                if attempt == self.max_retries:
                    raise RetryableRequestError(
                        f"{upstream} is temporarily unavailable"
                    )
                self._sleep_before_retry(attempt)
                continue
            if response.status_code >= 400:
                raise PermanentRequestError(
                    f"{upstream} rejected the collector request "
                    f"with HTTP {response.status_code}"
                )
            return response
        raise AssertionError("request loop must return or raise")

    def _sleep_before_retry(self, attempt: int) -> None:
        delay = self.retry_base_seconds * (2**attempt)
        self.sleep(delay + random.uniform(0, delay / 2))


class LokiClient:
    """Loki push client for persisted collector events."""

    def __init__(
        self,
        config: CollectorConfig,
        n8n_client: N8nClient,
    ) -> None:
        self.push_url = config.loki_push_url
        self.request = n8n_client._request

    def push(self, events: list[OutboxEvent]) -> None:
        if not events:
            return
        streams: dict[tuple[tuple[str, str], ...], list[list[str]]] = {}
        for event in events:
            labels = tuple(sorted(event.labels.items()))
            streams.setdefault(labels, []).append([event.timestamp_ns, event.line])
        payload = {
            "streams": [
                {
                    "stream": dict(labels),
                    "values": sorted(values, key=lambda value: (value[0], value[1])),
                }
                for labels, values in sorted(streams.items())
            ]
        }
        self.request(
            "POST",
            self.push_url,
            headers={"Content-Type": "application/json"},
            json_payload=payload,
            upstream="Loki",
        )


class N8nExecutionCollector:
    """Coordinates discovery, safe normalization, delivery, and heartbeats."""

    def __init__(
        self,
        config: CollectorConfig,
        *,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.config = config
        self.state = CollectorState(config.state_path)
        self.http_client = httpx.Client(
            timeout=config.http_timeout_seconds,
            transport=transport,
        )
        self.n8n = N8nClient(config, self.http_client, sleep=sleep)
        self.loki = LokiClient(config, self.n8n)
        self.sleep = sleep

    def close(self) -> None:
        self.http_client.close()
        self.state.close()

    def run_forever(self) -> None:
        """Run polling cycles until the process receives an interrupt signal."""

        while True:
            try:
                result = self.run_once()
                if not result.successful:
                    LOGGER.warning(
                        "Collector cycle completed without Loki confirmation"
                    )
            except CollectorRequestError as error:
                LOGGER.warning("Collector cycle failed: %s", error)
            except ValueError as error:
                LOGGER.warning("Collector received an invalid n8n record: %s", error)
            self.sleep(self.config.poll_interval_seconds)

    def run_once(self, *, now: datetime | None = None) -> PollResult:
        """Run one cycle and retain undelivered events when Loki is unavailable."""

        poll_started = (now or datetime.now(UTC)).astimezone(UTC)
        monotonic_started = time.monotonic()
        try:
            self._refresh_workflows_if_due(poll_started)
        except RetryableRequestError as error:
            # A transient workflow-list issue must not prevent execution polling;
            # cached names remain valid until the next successful refresh.
            LOGGER.warning("Workflow cache refresh deferred: %s", error)
        summaries, initial_backfill_complete = self._discover_summaries(poll_started)

        discovered_count = 0
        candidate_ids: set[str] = set(self.state.pending_execution_ids())
        for summary in summaries:
            execution_id = _execution_id(summary)
            if execution_id is None:
                LOGGER.warning("Skipping n8n execution summary without an id")
                continue
            existing = self.state.get_execution(execution_id)
            if existing is None:
                discovered_count += 1
                candidate_ids.add(execution_id)
            elif (
                existing["status"] in PENDING_STATUSES
                and existing["delivered_at"] is None
            ):
                candidate_ids.add(execution_id)

        for execution_id in sorted(candidate_ids):
            existing = self.state.get_execution(execution_id)
            if existing and existing["event_line"] is not None:
                continue
            self._process_execution(execution_id, poll_started)

        if initial_backfill_complete:
            self.state.mark_initial_backfill_complete()

        try:
            delivered_count = self._flush_outbox(poll_started)
        except CollectorRequestError as error:
            LOGGER.warning("Loki delivery deferred: %s", error)
            return PollResult(
                discovered_count=discovered_count,
                pending_count=len(self.state.pending_execution_ids()),
                delivered_count=0,
                api_latency_ms=int((time.monotonic() - monotonic_started) * 1000),
                successful=False,
            )

        api_latency_ms = int((time.monotonic() - monotonic_started) * 1000)
        heartbeat = self._heartbeat_event(
            poll_started,
            discovered_count=discovered_count,
            pending_count=len(self.state.pending_execution_ids()),
            delivered_count=delivered_count,
            api_latency_ms=api_latency_ms,
        )
        try:
            self.loki.push([heartbeat])
        except CollectorRequestError as error:
            LOGGER.warning("Collector heartbeat delivery deferred: %s", error)
            return PollResult(
                discovered_count=discovered_count,
                pending_count=len(self.state.pending_execution_ids()),
                delivered_count=delivered_count,
                api_latency_ms=api_latency_ms,
                successful=False,
            )

        self.state.mark_successful_poll(poll_started)
        self.state.prune_delivered(poll_started - timedelta(days=31))
        return PollResult(
            discovered_count=discovered_count,
            pending_count=len(self.state.pending_execution_ids()),
            delivered_count=delivered_count,
            api_latency_ms=api_latency_ms,
            successful=True,
        )

    def _refresh_workflows_if_due(self, now: datetime) -> None:
        if not self.state.workflow_refresh_due(
            now, self.config.workflow_refresh_seconds
        ):
            return
        cursor: str | None = None
        while True:
            payload = self.n8n.list_workflows(cursor)
            workflows = payload.get("data")
            if not isinstance(workflows, list):
                raise RetryableRequestError("n8n returned invalid workflow data")
            for workflow in workflows:
                if not isinstance(workflow, Mapping):
                    continue
                workflow_id = _safe_identifier(workflow.get("id"))
                workflow_name = _safe_string(workflow.get("name"), max_length=512)
                if workflow_id and workflow_name:
                    self.state.set_workflow(workflow_id, workflow_name, now)
            cursor_value = payload.get("nextCursor")
            cursor = (
                cursor_value if isinstance(cursor_value, str) and cursor_value else None
            )
            if cursor is None:
                break
        self.state.mark_workflows_refreshed(now)

    def _discover_summaries(
        self, now: datetime
    ) -> tuple[list[Mapping[str, object]], bool]:
        initial_backfill = not self.state.initial_backfill_complete()
        cutoff = now - timedelta(hours=self.config.initial_backfill_hours)
        cursor: str | None = None
        summaries: list[Mapping[str, object]] = []
        reached_boundary = False

        while True:
            payload = self.n8n.list_executions(cursor)
            data = payload.get("data")
            if not isinstance(data, list):
                raise RetryableRequestError("n8n returned invalid execution data")
            page: list[Mapping[str, object]] = [
                item for item in data if isinstance(item, Mapping)
            ]

            for summary in page:
                started_at = _parse_timestamp(summary.get("startedAt"))
                if initial_backfill and started_at is not None and started_at < cutoff:
                    reached_boundary = True
                    break
                summaries.append(summary)

            if reached_boundary:
                return summaries, True
            if (
                not initial_backfill
                and page
                and all(
                    (execution_id := _execution_id(summary)) is not None
                    and self.state.get_execution(execution_id) is not None
                    for summary in page
                )
            ):
                return summaries, False

            cursor_value = payload.get("nextCursor")
            cursor = (
                cursor_value if isinstance(cursor_value, str) and cursor_value else None
            )
            if cursor is None:
                return summaries, initial_backfill

    def _process_execution(self, execution_id: str, now: datetime) -> None:
        detail = self.n8n.get_execution(execution_id, include_data=False)
        status = _execution_status(detail)
        workflow_id = _safe_identifier(detail.get("workflowId")) or "unknown"
        workflow_name = self.state.workflow_name(workflow_id) or workflow_id
        if status in PENDING_STATUSES:
            self.state.store_pending(
                detail, workflow_name=workflow_name, observed_at=now
            )
            return

        error_type: str | None = None
        error_node: str | None = None
        if status in {"error", "crashed"}:
            try:
                error_detail = self.n8n.get_execution(execution_id, include_data=True)
            except RetryableRequestError as error:
                LOGGER.warning("Unable to retrieve safe failure metadata: %s", error)
            else:
                error_type, error_node = _extract_error_metadata(error_detail)
        self.state.store_terminal(
            detail,
            workflow_name=workflow_name,
            observed_at=now,
            error_type=error_type,
            error_node=error_node,
        )

    def _flush_outbox(self, now: datetime) -> int:
        events = self.state.pending_events()
        if not events:
            return 0
        self.loki.push(events)
        self.state.mark_delivered([event.execution_id for event in events], now)
        return len(events)

    @staticmethod
    def _heartbeat_event(
        now: datetime,
        *,
        discovered_count: int,
        pending_count: int,
        delivered_count: int,
        api_latency_ms: int,
    ) -> OutboxEvent:
        payload = {
            "timestamp": _format_timestamp(now),
            "poll_timestamp_seconds": int(now.timestamp()),
            "discovered_count": discovered_count,
            "pending_count": pending_count,
            "delivered_count": delivered_count,
            "api_latency_ms": api_latency_ms,
        }
        return OutboxEvent(
            execution_id="collector-heartbeat",
            labels={"event": POLL_EVENT, "level": "info", "service": "n8n"},
            timestamp_ns=_timestamp_nanoseconds(now),
            line=json.dumps(payload, separators=(",", ":"), sort_keys=True),
        )


def main() -> int:
    """Run the collector or evaluate its local health state."""

    parser = argparse.ArgumentParser(description="n8n execution collector")
    parser.add_argument("--healthcheck", action="store_true")
    arguments = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    try:
        config = CollectorConfig.from_environment()
        if arguments.healthcheck:
            state = CollectorState(config.state_path)
            try:
                return (
                    0
                    if state.healthy(datetime.now(UTC), config.poll_interval_seconds)
                    else 1
                )
            finally:
                state.close()
        collector = N8nExecutionCollector(config)
        try:
            collector.run_forever()
        finally:
            collector.close()
    except (OSError, ValueError, sqlite3.Error) as error:
        LOGGER.error("Collector configuration or state is invalid: %s", error)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
