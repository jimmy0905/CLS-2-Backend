"""Bounded, spreadsheet-safe writers used by asynchronous analytics exports."""

from __future__ import annotations

import asyncio
import csv
import json
import uuid
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from openpyxl import Workbook

import core.config as config
from features.analytics.model.semantic import escape_spreadsheet_formula

EXPORT_FORMATS = frozenset({"csv", "xlsx"})
_EXPORT_WORKER_SEMAPHORE = asyncio.Semaphore(config.ANALYTICS_EXPORT_WORKER_CONCURRENCY)


def authorize_export_role(requested_role: str) -> str:
    """Validate and return the immutable role captured when the job was admitted."""
    if requested_role not in {"viewer", "admin"}:
        raise ValueError("Export job contains an invalid analytics role")
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


def _collect_record_rows(
    payload: dict[str, Any], role: str, max_rows: int
) -> list[dict[str, Any]]:
    """Collect a live record query in bounded pages for an export worker."""
    from core.config import is_survey_export_column_enabled
    from features.analytics.endpoints.analytics import (
        RecordQueryInput,
        _active_model_version,
        _catalog_from_version,
        _raw_field_sources_from_version,
    )
    from features.analytics.repository.records import (
        DEFAULT_PROJECTED_RECORD_FIELDS,
        build_record_query,
        execute_projected_records,
        serialize_record,
    )
    from infrastructure.database.session import SessionLocal

    spec = RecordQueryInput.model_validate(payload)
    db = SessionLocal()
    try:
        if spec.representation == "projected":
            version = _active_model_version(db)
            catalog = _catalog_from_version(version, role)
            rows: list[dict[str, Any]] = []
            cursor = spec.cursor
            while len(rows) < max_rows:
                page = execute_projected_records(
                    db,
                    fields=spec.fields or DEFAULT_PROJECTED_RECORD_FIELDS,
                    filters=tuple(spec.filters),
                    cursor=cursor,
                    size=min(250, max_rows - len(rows)),
                    timezone_name=spec.timezone,
                    catalog=catalog,
                    role=role,
                    raw_fields=_raw_field_sources_from_version(version, role),
                )
                rows.extend(page["items"])
                if page["has_more"] and len(rows) >= max_rows:
                    raise ValueError(
                        "Analytics export exceeds the configured row limit"
                    )
                if not page["has_more"] or page["next_cursor"] is None:
                    break
                cursor = page["next_cursor"]
            return rows

        query = build_record_query(
            db,
            spec.resource,
            tuple(spec.filters),
            tuple(spec.order),
            spec.timezone,
        )
        total = query.order_by(None).count()
        if total > max_rows:
            raise ValueError("Analytics export exceeds the configured row limit")
        records = query.limit(max_rows).all()
        rows = [
            serialize_record(spec.resource, record, spec.timezone)
            if spec.resource != "surveys"
            else record.to_csv(spec.timezone)
            for record in records
        ]
        if spec.resource == "surveys":
            if not rows:
                return rows
            configured = [
                key for key in rows[0] if is_survey_export_column_enabled(key)
            ]
            if not configured:
                raise ValueError(
                    "No survey export columns are configured for "
                    "analytics record exports"
                )
            return [{key: row.get(key) for key in configured} for row in rows]
        return rows
    finally:
        db.close()


async def _execute_export_job(job_id: str) -> None:
    """Execute a prevalidated aggregate query for a persisted export job."""
    from core.config import (
        ANALYTICS_CUBE_API_SECRET,
        ANALYTICS_CUBE_API_URL,
        ANALYTICS_EXPORT_DIR,
        ANALYTICS_EXPORT_MAX_ROWS,
        ANALYTICS_QUERY_TIMEOUT_SECONDS,
        DEPLOYMENT_PROFILE,
    )
    from core.logging import logger
    from core.time import utc_now
    from infrastructure.database.dbo.AnalyticsExportJob import AnalyticsExportJob
    from infrastructure.database.dbo.AnalyticsQueryLog import AnalyticsQueryLog
    from infrastructure.database.session import SessionLocal
    from infrastructure.integrations.cube import CubeClient

    db = SessionLocal()
    output_path: Path | None = None
    try:
        job = (
            db.query(AnalyticsExportJob).filter(AnalyticsExportJob.id == job_id).first()
        )
        if job is None or job.status != "queued":
            return
        request = job.request or {}
        mode = request.get("mode", "query")
        cube_query = request.get("cube_query")
        role = authorize_export_role(request.get("role"))
        from features.analytics.endpoints.analytics import (
            _active_model_version,
            _catalog_from_version,
        )

        active_version = _active_model_version(db)
        ensure_export_model_version(
            job.model_version_id,
            active_version.id if active_version is not None else None,
        )
        catalog = _catalog_from_version(active_version, role)
        if mode not in {"query", "record_query"}:
            raise ValueError("Export job contains an invalid governed query")
        if mode == "query" and not isinstance(cube_query, dict):
            raise ValueError("Export job contains an invalid governed query")
        if mode == "record_query" and not isinstance(request.get("record_query"), dict):
            raise ValueError("Export job contains an invalid governed record query")

        job.status = "processing"
        job.started_at = utc_now()
        db.commit()

        if mode == "query":
            from features.analytics.model.semantic import (
                QuerySpec,
                compile_cube_query,
                validate_query,
            )
            from features.analytics.service.results import (
                augment_cube_query_with_supports,
                format_query_result,
            )

            semantic_query = validate_query(
                QuerySpec.model_validate(request.get("semantic_query")), catalog, role
            )
            # Recompile at execution time so a revoked/changed member cannot be
            # smuggled through a previously persisted Cube payload.
            cube_query = augment_cube_query_with_supports(
                compile_cube_query(semantic_query, catalog, role, _validated=True),
                semantic_query,
                catalog,
                role,
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
            rows = format_query_result(result, semantic_query, catalog, role)["rows"]
        else:
            rows = await asyncio.to_thread(
                _collect_record_rows,
                request["record_query"],
                role,
                ANALYTICS_EXPORT_MAX_ROWS,
            )
        db.expire_all()
        latest_version = _active_model_version(db)
        ensure_export_model_version(
            job.model_version_id,
            latest_version.id if latest_version is not None else None,
        )
        output_path = build_export_path(ANALYTICS_EXPORT_DIR, job.id, job.export_format)
        row_count = await asyncio.to_thread(
            write_export,
            rows,
            job.export_format,
            output_path,
            max_rows=ANALYTICS_EXPORT_MAX_ROWS,
        )
        db.expire_all()
        latest_version = _active_model_version(db)
        ensure_export_model_version(
            job.model_version_id,
            latest_version.id if latest_version is not None else None,
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
        job = (
            db.query(AnalyticsExportJob).filter(AnalyticsExportJob.id == job_id).first()
        )
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
