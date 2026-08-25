"""Bounded, spreadsheet-safe writers used by asynchronous analytics exports."""
from __future__ import annotations

import csv
import asyncio
import config
import json
import uuid
from pathlib import Path
from typing import Any, Iterable

from openpyxl import Workbook

from utils.analytics import escape_spreadsheet_formula


EXPORT_FORMATS = frozenset({"csv", "xlsx"})
_EXPORT_WORKER_SEMAPHORE = asyncio.Semaphore(
    config.ANALYTICS_EXPORT_WORKER_CONCURRENCY
)


def authorize_export_role(requested_role: str, user: Any) -> str:
    """Return the least privilege captured by a job after checking revocation."""
    if requested_role not in {"viewer", "admin"}:
        raise ValueError("Export job contains an invalid analytics role")
    if user is None or bool(getattr(user, "is_deleted", False)):
        raise PermissionError("Analytics export requester is no longer active")
    current_role = "admin" if getattr(user, "role", None) == "admin" else "viewer"
    if requested_role == "admin" and current_role != "admin":
        raise PermissionError("Analytics export administrator access was revoked")
    # A later promotion must not broaden a job that was queued as a viewer.
    return requested_role


def ensure_export_model_version(
    expected_model_version_id: int | None,
    active_model_version_id: int | None,
) -> None:
    """Reject queued work whose immutable governed catalog is no longer active."""

    if expected_model_version_id != active_model_version_id:
        raise ValueError(
            "Analytics catalog changed while the export was queued; submit it again"
        )


def cube_response_rows(response: dict[str, Any]) -> list[dict[str, Any]]:
    rows = response.get("data")
    if not isinstance(rows, list):
        raise ValueError("Cube analytics response contains invalid data")
    if not all(isinstance(row, dict) for row in rows):
        raise ValueError("Cube analytics response contains an invalid row")
    return rows


def build_export_path(root: Path, job_id: str, export_format: str) -> Path:
    if export_format not in EXPORT_FORMATS:
        raise ValueError("Unsupported analytics export format")
    try:
        normalized_id = str(uuid.UUID(job_id))
    except (TypeError, ValueError, AttributeError) as error:
        raise ValueError("Invalid analytics export job identifier") from error
    export_root = root.resolve()
    path = (export_root / f"{normalized_id}.{export_format}").resolve()
    if path.parent != export_root:
        raise ValueError("Analytics export path escapes its configured root")
    return path


def remove_export_file(root: Path, storage_path: str | None) -> bool:
    """Remove an expired artifact only when it is inside the configured root."""
    if not storage_path:
        return False
    export_root = root.resolve()
    candidate = Path(storage_path).resolve()
    if candidate.parent != export_root or not candidate.is_file():
        return False
    candidate.unlink()
    return True


def _columns(rows: list[dict[str, Any]]) -> list[str]:
    result: list[str] = []
    for row in rows:
        for key in row:
            if key not in result:
                result.append(key)
    return result


def _safe_cell(value: Any) -> Any:
    if isinstance(value, (dict, list, tuple)):
        value = json.dumps(value, ensure_ascii=False, default=str)
    return escape_spreadsheet_formula(value)


def write_export(
    source_rows: Iterable[dict[str, Any]],
    export_format: str,
    path: Path,
    *,
    max_rows: int,
) -> int:
    if export_format not in EXPORT_FORMATS:
        raise ValueError("Unsupported analytics export format")
    if max_rows < 1:
        raise ValueError("Analytics export row limit must be positive")
    rows = source_rows if isinstance(source_rows, list) else list(source_rows)
    if len(rows) > max_rows:
        raise ValueError("Analytics export exceeds the configured row limit")
    columns = _columns(rows)
    path.parent.mkdir(parents=True, exist_ok=True)

    if export_format == "csv":
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
            writer.writeheader()
            for row in rows:
                writer.writerow({key: _safe_cell(row.get(key)) for key in columns})
    else:
        workbook = Workbook(write_only=True)
        sheet = workbook.create_sheet()
        sheet.title = "Analytics"
        sheet.append(columns)
        for row in rows:
            sheet.append([_safe_cell(row.get(key)) for key in columns])
        workbook.save(path)
    return len(rows)


def _collect_drilldown_rows(
    payload: dict[str, Any], role: str, max_rows: int
) -> list[dict[str, Any]]:
    """Collect governed drilldown pages in a worker thread."""
    from routers.analytics import _catalog, _raw_field_sources
    from utils.analytics_drilldown import DrilldownSpec, execute_drilldown
    from utils.database import SessionLocal

    db = SessionLocal()
    try:
        spec = DrilldownSpec.model_validate(payload)
        catalog = _catalog(db, role)
        raw_fields = _raw_field_sources(db, role)
        rows: list[dict[str, Any]] = []
        cursor = spec.cursor
        while len(rows) < max_rows:
            page_spec = spec.model_copy(
                update={"cursor": cursor, "limit": min(250, max_rows - len(rows))}
            )
            page = execute_drilldown(
                db,
                page_spec,
                catalog,
                role=role,
                raw_fields=raw_fields,
            )
            rows.extend(page["rows"])
            if not page["has_more"] or page["next_cursor"] is None:
                break
            cursor = page["next_cursor"]
        return rows
    finally:
        db.close()


async def _execute_export_job(job_id: str) -> None:
    """Execute a prevalidated aggregate query for a persisted export job."""
    from config import (
        ANALYTICS_CUBE_API_SECRET,
        ANALYTICS_CUBE_API_URL,
        ANALYTICS_EXPORT_DIR,
        ANALYTICS_EXPORT_MAX_ROWS,
        ANALYTICS_QUERY_TIMEOUT_SECONDS,
        DEPLOYMENT_PROFILE,
    )
    from models.AnalyticsExportJob import AnalyticsExportJob
    from models.AnalyticsQueryLog import AnalyticsQueryLog
    from models.User import User
    from utils.analytics_cube import CubeClient
    from utils.database import SessionLocal
    from utils.logger import logger
    from utils.utc import utc_now

    db = SessionLocal()
    output_path: Path | None = None
    try:
        job = db.query(AnalyticsExportJob).filter(AnalyticsExportJob.id == job_id).first()
        if job is None or job.status != "queued":
            return
        request = job.request or {}
        mode = request.get("mode", "query")
        cube_query = request.get("cube_query")
        role = authorize_export_role(
            request.get("role"),
            db.query(User).filter(User.id == job.requested_by_id).first(),
        )
        from routers.analytics import _active_model_version

        active_version = _active_model_version(db)
        ensure_export_model_version(
            job.model_version_id,
            active_version.id if active_version is not None else None,
        )
        if mode not in {"query", "drilldown"}:
            raise ValueError("Export job contains an invalid governed query")
        if mode == "query" and not isinstance(cube_query, dict):
            raise ValueError("Export job contains an invalid governed query")
        if mode == "drilldown" and not isinstance(request.get("drilldown"), dict):
            raise ValueError("Export job contains an invalid governed drilldown")

        job.status = "processing"
        job.started_at = utc_now()
        db.commit()

        if mode == "query":
            from routers.analytics import _catalog
            from utils.analytics import QuerySpec, compile_cube_query
            from utils.analytics_results import (
                augment_cube_query_with_supports,
                format_query_result,
            )

            semantic_query = QuerySpec.model_validate(request.get("semantic_query"))
            catalog = _catalog(db, role)
            # Recompile at execution time so a revoked/changed member cannot be
            # smuggled through a previously persisted Cube payload.
            cube_query = augment_cube_query_with_supports(
                compile_cube_query(semantic_query, catalog, role),
                semantic_query,
                catalog,
            )
            result = await CubeClient(
                ANALYTICS_CUBE_API_URL,
                ANALYTICS_CUBE_API_SECRET,
                ANALYTICS_QUERY_TIMEOUT_SECONDS,
            ).execute(
                cube_query,
                profile_id=DEPLOYMENT_PROFILE,
                role=role,
                request_id=job.id,
            )
            rows = format_query_result(result, semantic_query, catalog)["rows"]
        else:
            rows = await asyncio.to_thread(
                _collect_drilldown_rows,
                request["drilldown"],
                role,
                ANALYTICS_EXPORT_MAX_ROWS,
            )
        output_path = build_export_path(
            ANALYTICS_EXPORT_DIR, job.id, job.export_format
        )
        row_count = await asyncio.to_thread(
            write_export,
            rows,
            job.export_format,
            output_path,
            max_rows=ANALYTICS_EXPORT_MAX_ROWS,
        )

        job.status = "completed"
        job.row_count = row_count
        job.storage_path = str(output_path)
        job.content_type = (
            "text/csv; charset=utf-8"
            if job.export_format == "csv"
            else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        job.completed_at = utc_now()
        if job.query_log_id:
            query_log = (
                db.query(AnalyticsQueryLog)
                .filter(AnalyticsQueryLog.id == job.query_log_id)
                .first()
            )
            if query_log:
                query_log.status = "completed"
                query_log.row_count = row_count
                query_log.completed_at = utc_now()
        db.commit()
    except Exception:
        db.rollback()
        if output_path is not None:
            remove_export_file(ANALYTICS_EXPORT_DIR, str(output_path))
        job = db.query(AnalyticsExportJob).filter(AnalyticsExportJob.id == job_id).first()
        if job:
            job.status = "failed"
            job.error_message = "Analytics export failed"
            job.completed_at = utc_now()
            if job.query_log_id:
                query_log = (
                    db.query(AnalyticsQueryLog)
                    .filter(AnalyticsQueryLog.id == job.query_log_id)
                    .first()
                )
                if query_log:
                    query_log.status = "failed"
                    query_log.error_message = "Analytics export failed"
                    query_log.completed_at = utc_now()
            db.commit()
        logger.exception(
            "Analytics export job failed",
            extra={"event": "analytics.export.failed", "export_job_id": job_id},
        )
    finally:
        db.close()


async def execute_export_job(job_id: str) -> None:
    """Run an export under the bounded in-process worker pool."""
    async with _EXPORT_WORKER_SEMAPHORE:
        await _execute_export_job(job_id)
