import asyncio
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import select

from config import (
    ANALYTICS_EXPORT_DIR,
    ANALYTICS_GOVERNANCE_RETENTION_DAYS,
    DATA_RETENTION_DAYS,
    RETENTION_CHECK_INTERVAL_SECONDS,
    SERVER_LOG_FILE,
)
from models.Action import Action
from models.EmailRecord import EmailRecord
from models.GeneratedEmail import GeneratedEmail
from models.LoginRecord import LoginRecord
from models.AnalyticsAuditLog import AnalyticsAuditLog
from models.AnalyticsExportJob import AnalyticsExportJob
from models.AnalyticsQueryLog import AnalyticsQueryLog
from models.UploadTask import UploadTask
from models.UploadTaskError import UploadTaskError
from utils.database import SessionLocal
from utils.analytics_exports import remove_export_file
from utils.logger import logger
from utils.utc import utc_now


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
            "login_records": db.query(LoginRecord)
            .filter(LoginRecord.login_time < cutoff)
            .delete(synchronize_session=False),
            "actions": db.query(Action)
            .filter(Action.created_at < cutoff)
            .delete(synchronize_session=False),
            "generated_emails": db.query(GeneratedEmail)
            .filter(GeneratedEmail.created_at < cutoff)
            .delete(synchronize_session=False),
            "email_records": db.query(EmailRecord)
            .filter(EmailRecord.created_at < cutoff)
            .delete(synchronize_session=False),
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


def purge_rotated_log_files(cutoff: datetime) -> int:
    if not SERVER_LOG_FILE:
        return 0

    log_path = Path(SERVER_LOG_FILE)
    if not log_path.parent.exists():
        return 0

    deleted_count = 0
    for archived_log in log_path.parent.glob(f"{log_path.name}.*"):
        if not archived_log.is_file():
            continue
        modified_at = datetime.fromtimestamp(
            archived_log.stat().st_mtime, tz=cutoff.tzinfo
        )
        if modified_at < cutoff:
            archived_log.unlink()
            deleted_count += 1
    return deleted_count


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
    deleted["rotated_log_files"] = purge_rotated_log_files(cutoff)
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
        except asyncio.TimeoutError:
            try:
                await asyncio.to_thread(run_retention)
            except Exception:
                logger.exception("Operational data retention failed")
            continue
        return
