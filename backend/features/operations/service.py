import asyncio
from datetime import datetime, timedelta

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from core.config import (
    ANALYTICS_EXPORT_DIR,
    ANALYTICS_GOVERNANCE_RETENTION_DAYS,
    DATA_RETENTION_DAYS,
    DEPLOYMENT_PROFILE,
    RETENTION_CHECK_INTERVAL_SECONDS,
)
from core.logging import logger, purge_rotated_log_files
from core.time import utc_now
from features.analytics.service.exports import remove_export_file
from infrastructure.database.dbo.AnalyticsAuditLog import AnalyticsAuditLog
from infrastructure.database.dbo.AnalyticsExportJob import AnalyticsExportJob
from infrastructure.database.dbo.AnalyticsQueryLog import AnalyticsQueryLog
from infrastructure.database.dbo.UploadTask import UploadTask
from infrastructure.database.dbo.UploadTaskError import UploadTaskError
from infrastructure.database.session import SessionLocal


def retention_cutoff(
    retention_days: int = DATA_RETENTION_DAYS, now: datetime | None = None
) -> datetime:
    return (now or utc_now()) - timedelta(days=retention_days)


def purge_operational_records(cutoff: datetime) -> dict[str, int]:
    """Delete expired operational records while preserving all survey/business data."""
    db = SessionLocal()
    try:
        expired_upload_task_ids = select(UploadTask.id).where(
            UploadTask.updated_at < cutoff,
            UploadTask.status != "processing",
        )
        deleted = {
            "upload_task_errors": db.query(UploadTaskError)
            .filter(UploadTaskError.upload_task_id.in_(expired_upload_task_ids))
            .delete(synchronize_session=False),
            "upload_tasks": db.query(UploadTask)
            .filter(UploadTask.id.in_(expired_upload_task_ids))
            .delete(synchronize_session=False),
        }
        db.commit()
        return deleted
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def purge_analytics_records(now: datetime) -> dict[str, int]:
    """Expire files promptly while retaining governance records for 365 days."""
    governance_cutoff = now - timedelta(days=ANALYTICS_GOVERNANCE_RETENTION_DAYS)
    db = SessionLocal()
    try:
        expired_files = 0
        expired_jobs = (
            db.query(AnalyticsExportJob)
            .filter(
                AnalyticsExportJob.expires_at < now,
                AnalyticsExportJob.storage_path.isnot(None),
            )
            .all()
        )
        for job in expired_jobs:
            if remove_export_file(ANALYTICS_EXPORT_DIR, job.storage_path):
                expired_files += 1
            job.storage_path = None
            if job.status == "completed":
                job.status = "expired"

        deleted_export_jobs = (
            db.query(AnalyticsExportJob)
            .filter(AnalyticsExportJob.created_at < governance_cutoff)
            .delete(synchronize_session=False)
        )
        referenced_query_ids = select(AnalyticsExportJob.query_log_id).where(
            AnalyticsExportJob.query_log_id.isnot(None)
        )
        deleted_query_logs = (
            db.query(AnalyticsQueryLog)
            .filter(
                AnalyticsQueryLog.created_at < governance_cutoff,
                AnalyticsQueryLog.id.not_in(referenced_query_ids),
            )
            .delete(synchronize_session=False)
        )
        deleted_audit_logs = (
            db.query(AnalyticsAuditLog)
            .filter(AnalyticsAuditLog.created_at < governance_cutoff)
            .delete(synchronize_session=False)
        )
        db.commit()
        return {
            "analytics_export_files": expired_files,
            "analytics_export_jobs": deleted_export_jobs,
            "analytics_query_logs": deleted_query_logs,
            "analytics_audit_logs": deleted_audit_logs,
        }
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def run_retention() -> dict[str, int]:
    now = utc_now()
    cutoff = retention_cutoff(now=now)
    deleted = purge_operational_records(cutoff)
    deleted["rotated_log_files"] = purge_rotated_log_files(now=now)
    deleted.update(purge_analytics_records(now))
    logger.info(
        "Operational data retention completed",
        extra={
            "event": "retention.completed",
            "retention_cutoff": cutoff.isoformat(),
            "count": sum(deleted.values()),
        },
    )
    return deleted


async def retention_loop(stop_event: asyncio.Event) -> None:
    while True:
        try:
            await asyncio.wait_for(
                stop_event.wait(), timeout=RETENTION_CHECK_INTERVAL_SECONDS
            )
        except TimeoutError:
            try:
                await asyncio.to_thread(run_retention)
            except Exception:
                logger.exception("Operational data retention failed")
            continue
        return


class HealthService:
    """Operational database readiness check used by the health endpoint."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def check(self) -> dict[str, str]:
        try:
            self._session.execute(text("SELECT 1"))
            return {"status": "healthy", "profile": DEPLOYMENT_PROFILE}
        except Exception:
            logger.exception("Health check database query failed")
            raise


def health_service(session: Session) -> HealthService:
    return HealthService(session)
