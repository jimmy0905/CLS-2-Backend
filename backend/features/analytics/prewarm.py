"""One-shot Cube pre-aggregation warm-up command for deployment gates."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from core import config
from features.analytics.model.semantic import validate_identifier
from infrastructure.integrations.cube import CubeClient, CubeClientError

logger = logging.getLogger(__name__)

_MAX_JOBS_PER_BATCH = 8
_CORE_ROLLUPS = {
    "survey_responses.daily_core": "month",
    "survey_responses.monthly_core": "year",
    "survey_topics.daily_assignments": "month",
    "survey_departments.daily_assignments": "month",
    "survey_keywords.daily_assignments": "month",
    "survey_assignments.daily_topic_departments": "month",
}


@dataclass(frozen=True)
class RollupSpec:
    name: str
    partition_granularity: str | None


@dataclass(frozen=True)
class WarmupBatch:
    timezone_name: str
    pre_aggregations: tuple[str, ...]
    date_range: tuple[str, str] | None


def _chunks(values: Sequence[str], size: int) -> Iterable[tuple[str, ...]]:
    for start in range(0, len(values), size):
        yield tuple(values[start : start + size])


def _catalog_rollups(snapshot: dict[str, Any] | None) -> list[RollupSpec]:
    cube_catalog = (snapshot or {}).get("cubeCatalog", snapshot or {})
    raw_rollups = (
        cube_catalog.get("rollups", []) if isinstance(cube_catalog, dict) else []
    )
    result: list[RollupSpec] = []
    for rollup in raw_rollups if isinstance(raw_rollups, list) else []:
        if not isinstance(rollup, dict):
            continue
        view = validate_identifier(str(rollup.get("semanticView", "")))
        name = validate_identifier(str(rollup.get("name", "")))
        partition_granularity = rollup.get("partitionGranularity")
        if partition_granularity not in {None, "month", "year"}:
            raise ValueError("Unsupported analytics rollup partition granularity")
        result.append(
            RollupSpec(
                name=f"{view}.{name}",
                partition_granularity=partition_granularity,
            )
        )
    return result


def _rollups(snapshot: dict[str, Any] | None) -> list[RollupSpec]:
    by_name = {
        name: RollupSpec(name=name, partition_granularity=granularity)
        for name, granularity in _CORE_ROLLUPS.items()
    }
    for rollup in _catalog_rollups(snapshot):
        by_name[rollup.name] = rollup
    return sorted(by_name.values(), key=lambda item: item.name)


def _localized_date(value: datetime, timezone_name: str) -> date:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    try:
        return value.astimezone(ZoneInfo(timezone_name)).date()
    except ZoneInfoNotFoundError as error:
        raise ValueError("Invalid analytics pre-warm timezone") from error


def _partition_ranges(
    minimum: datetime,
    maximum: datetime,
    *,
    timezone_name: str,
    granularity: str,
) -> list[tuple[str, str]]:
    first = _localized_date(minimum, timezone_name)
    last = _localized_date(maximum, timezone_name)
    if granularity == "month":
        cursor = first.replace(day=1)
        ranges: list[tuple[str, str]] = []
        while cursor <= last:
            next_start = (
                cursor.replace(year=cursor.year + 1, month=1)
                if cursor.month == 12
                else cursor.replace(month=cursor.month + 1)
            )
            ranges.append(
                (cursor.isoformat(), (next_start - timedelta(days=1)).isoformat())
            )
            cursor = next_start
        return ranges
    if granularity == "year":
        cursor = first.replace(month=1, day=1)
        ranges = []
        while cursor <= last:
            next_start = cursor.replace(year=cursor.year + 1)
            ranges.append(
                (cursor.isoformat(), (next_start - timedelta(days=1)).isoformat())
            )
            cursor = next_start
        return ranges
    raise ValueError("Unsupported analytics rollup partition granularity")


def warmup_batches(
    rollups: Sequence[RollupSpec],
    *,
    minimum: datetime | None,
    maximum: datetime | None,
    timezone_names: Sequence[str],
) -> list[WarmupBatch]:
    """Create queue-safe batches covering every historical data partition."""

    if not timezone_names:
        raise ValueError("At least one analytics pre-warm timezone is required")
    by_granularity = {
        granularity: sorted(
            rollup.name
            for rollup in rollups
            if rollup.partition_granularity == granularity
        )
        for granularity in (None, "month", "year")
    }
    result: list[WarmupBatch] = []
    for timezone_name in timezone_names:
        try:
            ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError as error:
            raise ValueError("Invalid analytics pre-warm timezone") from error
        for names in _chunks(by_granularity[None], _MAX_JOBS_PER_BATCH):
            result.append(WarmupBatch(timezone_name, names, None))
        if minimum is None or maximum is None:
            continue
        for granularity in ("month", "year"):
            for date_range in _partition_ranges(
                minimum,
                maximum,
                timezone_name=timezone_name,
                granularity=granularity,
            ):
                for names in _chunks(
                    by_granularity[granularity], _MAX_JOBS_PER_BATCH
                ):
                    result.append(WarmupBatch(timezone_name, names, date_range))
    return result


def _load_warmup_inputs() -> tuple[
    dict[str, Any] | None, datetime | None, datetime | None
]:
    # Import mapped objects together so SQLAlchemy relationships are resolved in
    # the same way as the running application before querying the shared schema.
    from sqlalchemy import func

    from infrastructure.database import registry as _database_registry  # noqa: F401
    from infrastructure.database.dbo.AnalyticsModelVersion import (
        AnalyticsModelVersion,
    )
    from infrastructure.database.dbo.Survey import Survey
    from infrastructure.database.session import SessionLocal

    db = SessionLocal()
    try:
        active_version = (
            db.query(AnalyticsModelVersion)
            .filter(AnalyticsModelVersion.is_active.is_(True))
            .order_by(AnalyticsModelVersion.catalog_version.desc())
            .first()
        )
        minimum, maximum = db.query(
            func.min(Survey.reported_at), func.max(Survey.reported_at)
        ).filter(Survey.is_deleted.is_not(True)).one()
        snapshot = active_version.catalog_snapshot if active_version else None
        return snapshot, minimum, maximum
    finally:
        db.close()


async def prewarm() -> None:
    """Build and await every scheduled rollup for the configured profile."""

    if not config.ANALYTICS_ENABLED:
        logger.info(
            "Analytics pre-warm skipped because analytics is disabled",
            extra={"event": "analytics.prewarm.skipped"},
        )
        return
    snapshot, minimum, maximum = _load_warmup_inputs()
    batches = warmup_batches(
        _rollups(snapshot),
        minimum=minimum,
        maximum=maximum,
        timezone_names=config.ANALYTICS_CUBE_REFRESH_TIME_ZONES,
    )
    request_id = f"prewarm-{config.DEPLOYMENT_PROFILE}-{uuid.uuid4()}"
    client = CubeClient(
        config.ANALYTICS_CUBE_API_URL,
        config.ANALYTICS_CUBE_API_SECRET,
        timeout_seconds=config.ANALYTICS_QUERY_TIMEOUT_SECONDS,
    )
    deadline = time.monotonic() + config.ANALYTICS_PREWARM_TIMEOUT_SECONDS
    job_count = 0
    for sequence, batch in enumerate(batches, start=1):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise RuntimeError("Analytics pre-warm exceeded its deployment deadline")
        batch_request_id = f"{request_id}-batch-{sequence}"
        tokens = await client.refresh_pre_aggregations(
            profile_id=config.DEPLOYMENT_PROFILE,
            timezone_name=batch.timezone_name,
            date_range=batch.date_range,
            pre_aggregations=batch.pre_aggregations,
            request_id=batch_request_id,
            timeout_seconds=remaining,
        )
        if not tokens:
            raise RuntimeError("Cube did not schedule a pre-aggregation warm-up job")
        job_count += len(tokens)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise RuntimeError("Analytics pre-warm exceeded its deployment deadline")
        await client.wait_for_pre_aggregation_jobs(
            tokens,
            profile_id=config.DEPLOYMENT_PROFILE,
            request_id=batch_request_id,
            timeout_seconds=remaining,
        )
    logger.info(
        "Analytics pre-warm completed",
        extra={
            "event": "analytics.prewarm.completed",
            "profile": config.DEPLOYMENT_PROFILE,
            "job_count": job_count,
        },
    )


def main() -> int:
    logging.basicConfig(level=config.SERVER_LOG_LEVEL)
    try:
        asyncio.run(prewarm())
    except (CubeClientError, RuntimeError, ValueError, ZoneInfoNotFoundError):
        logger.exception(
            "Analytics pre-warm failed",
            extra={
                "event": "analytics.prewarm.failed",
                "profile": config.DEPLOYMENT_PROFILE,
            },
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
