import asyncio
import os
import time
import uuid
from contextlib import asynccontextmanager, suppress

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi_pagination import add_pagination
from sqlalchemy import text
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

from config import (
    COOKIE_SECURE,
    CORS_ORIGINS,
    DEPLOYMENT_PROFILE,
    FASTAPI_DOCS_URL,
    FASTAPI_OPENAPI_URL,
    FASTAPI_REDOC_URL,
    FASTAPI_ROOT_PATH,
    LOG_SERVICE_NAME,
)
from routers import (
    analytics,
    auth,
    channels,
    dashboard,
    delivery_services,
    departments,
    stores,
    strategy,
    surveys,
    tasks,
    topics,
    translator,
    users,
)
from utils.database import (
    check_tables_exist,
    ensure_default_user,
    get_db,
    users_table_exists,
)
from utils.database_migrations import run_database_migrations
from utils.logger import bind_request_id, configure_logging, logger, reset_request_id
from utils.retention import retention_loop, run_retention


def _client_ip(request: Request) -> str | None:
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",", maxsplit=1)[0].strip()
    return request.client.host if request.client else None


def _is_analytics_path(path: str) -> bool:
    return path.startswith(("/analytics", "/admin/analytics", "/internal/analytics"))


@asynccontextmanager
async def lifespan(_: FastAPI):
    configure_logging()
    logger.info(
        "Server starting",
        extra={
            "event": "server.starting",
            "service": LOG_SERVICE_NAME,
            "deployment_profile": DEPLOYMENT_PROFILE,
        },
    )
    users_table_existed = users_table_exists()
    migrations_ran = run_database_migrations()
    if migrations_ran:
        if users_table_exists():
            if not users_table_existed:
                ensure_default_user()
        else:
            check_tables_exist()
    else:
        check_tables_exist()
    _reset_processing_upload_tasks()
    _reset_analytics_export_jobs()

    try:
        await asyncio.to_thread(run_retention)
    except Exception:
        logger.exception("Initial operational data retention failed")

    stop_event = asyncio.Event()
    retention_task = asyncio.create_task(retention_loop(stop_event))
    logger.info("Server ready", extra={"event": "server.ready"})
    try:
        yield
    finally:
        stop_event.set()
        retention_task.cancel()
        with suppress(asyncio.CancelledError):
            await retention_task
        logger.info("Server stopped", extra={"event": "server.stopped"})


app = FastAPI(
    title="CLS Connex",
    docs_url=FASTAPI_DOCS_URL,
    redoc_url=FASTAPI_REDOC_URL,
    openapi_url=FASTAPI_OPENAPI_URL,
    root_path=FASTAPI_ROOT_PATH,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=CORS_ORIGINS != ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(
    SessionMiddleware,
    secret_key=os.environ["SESSION_SECRET_KEY"],
    session_cookie="clsense_session",
    same_site="lax",
    https_only=COOKIE_SECURE,
)


@app.middleware("http")
async def log_request(request: Request, call_next) -> Response:
    request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
    request_id = request_id[:128]
    request_token = bind_request_id(request_id)
    started_at = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        logger.exception(
            "Request failed",
            extra={
                "event": "http.request.failed",
                "method": request.method,
                "path": request.url.path,
                "client_ip": _client_ip(request),
            },
        )
        raise
    else:
        response.headers["X-Request-ID"] = request_id
        if _is_analytics_path(request.url.path):
            response.headers["Cache-Control"] = "no-store, private"
        logger.info(
            "Request completed",
            extra={
                "event": "http.request.completed",
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": round((time.perf_counter() - started_at) * 1000, 2),
                "client_ip": _client_ip(request),
            },
        )
        return response
    finally:
        reset_request_id(request_token)


@app.exception_handler(Exception)
async def unhandled_exception_handler(_: Request, exception: Exception) -> JSONResponse:
    logger.exception("Unhandled server error", exc_info=exception)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


def _reset_processing_upload_tasks() -> None:
    from models.UploadTask import UploadTask
    from utils.database import SessionLocal
    from utils.utc import utc_now

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


def _reset_analytics_export_jobs() -> None:
    """Fail in-process export work that cannot survive a service restart."""
    from models.AnalyticsExportJob import AnalyticsExportJob
    from models.AnalyticsQueryLog import AnalyticsQueryLog
    from utils.database import SessionLocal
    from utils.utc import utc_now

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
                query_log.error_message = "Analytics export interrupted by service restart"
                query_log.completed_at = now
        db.commit()
        if jobs:
            logger.info(
                "Reset interrupted analytics exports",
                extra={"event": "analytics.exports.reset_after_restart", "count": len(jobs)},
            )
    except Exception:
        db.rollback()
        logger.exception("Failed to reset interrupted analytics exports")
        raise
    finally:
        db.close()


@app.get("/health")
async def health_check(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
        return {"status": "healthy", "profile": DEPLOYMENT_PROFILE}
    except Exception as error:
        logger.exception("Health check database query failed")
        raise HTTPException(status_code=500, detail="Database unavailable") from error


add_pagination(app)
app.include_router(auth.router)
app.include_router(analytics.router)
app.include_router(surveys.router)
app.include_router(dashboard.router)
app.include_router(strategy.router)
app.include_router(stores.router)
app.include_router(departments.router)
app.include_router(tasks.router)
app.include_router(users.router)
app.include_router(channels.router)
app.include_router(delivery_services.router)
app.include_router(topics.router)
app.include_router(translator.router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
