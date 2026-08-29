"""Restart-recovery actions for operational background work."""

from core.logging import logger
from core.time import utc_now
from infrastructure.database.dbo.AnalyticsExportJob import AnalyticsExportJob
from infrastructure.database.dbo.AnalyticsQueryLog import AnalyticsQueryLog
from infrastructure.database.dbo.UploadTask import UploadTask
from infrastructure.database.session import SessionLocal


def reset_processing_upload_tasks() -> None:
    db = SessionLocal()
    try:
        updated = (
            db.query(UploadTask)
            .filter(UploadTask.status == "processing")
            .update(
                {"status": "Stop: Restart", "updated_at": utc_now()},
                synchronize_session="fetch",
            )
        )
        db.commit()
        if updated:
            logger.info(
                "Reset processing upload tasks",
                extra={"event": "upload_tasks.reset_after_restart", "count": updated},
            )
    except Exception:
        db.rollback()
        logger.exception("Failed to reset processing upload tasks")
        raise
    finally:
        db.close()


def reset_analytics_export_jobs() -> None:
    """Fail in-process exports that cannot survive a service restart."""

    db = SessionLocal()
    try:
        jobs = (
            db.query(AnalyticsExportJob)
            .filter(AnalyticsExportJob.status.in_(("queued", "processing")))
            .all()
        )
        now = utc_now()
        query_ids = [job.query_log_id for job in jobs if job.query_log_id]
        for job in jobs:
            job.status = "failed"
            job.error_message = "Analytics export interrupted by service restart"
            job.completed_at = now
        if query_ids:
            for query_log in (
                db.query(AnalyticsQueryLog)
                .filter(AnalyticsQueryLog.id.in_(query_ids))
                .all()
            ):
                query_log.status = "failed"
                query_log.error_message = (
                    "Analytics export interrupted by service restart"
                )
                query_log.completed_at = now
        db.commit()
        if jobs:
            logger.info(
                "Reset interrupted analytics exports",
                extra={
                    "event": "analytics.exports.reset_after_restart",
                    "count": len(jobs),
                },
            )
    except Exception:
        db.rollback()
        logger.exception("Failed to reset interrupted analytics exports")
        raise
    finally:
        db.close()
