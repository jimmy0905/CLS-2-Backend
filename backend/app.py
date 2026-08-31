import asyncio
import time
import uuid
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi_pagination import add_pagination

from core.config import (
    CORS_ORIGINS,
    DEPLOYMENT_PROFILE,
    FASTAPI_DOCS_URL,
    FASTAPI_OPENAPI_URL,
    FASTAPI_REDOC_URL,
    FASTAPI_ROOT_PATH,
    LOG_SERVICE_NAME,
)
from core.errors import ApplicationError
from core.logging import bind_request_id, configure_logging, logger, reset_request_id
from core.openapi import install_openapi_component_compatibility
from features.analytics.endpoints import analytics
from features.dashboard.endpoints import dashboard
from features.feedback.endpoint import surveys
from features.ingestion.endpoints import tasks
from features.master_data.endpoints import (
    channels,
    delivery_services,
    departments,
    stores,
    topics,
)
from features.operations.endpoint import router as operations_router
from features.operations.lifecycle import (
    reset_analytics_export_jobs,
    reset_processing_upload_tasks,
)
from features.operations.service import retention_loop, run_retention
from features.strategy.endpoints import strategy
from features.translation.endpoints import translator
from infrastructure.database.migrations import (
    bootstrap_single_metric_analytics_defaults,
    run_database_migrations,
)
from infrastructure.database.session import check_tables_exist


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
    migrations_ran = run_database_migrations()
    if migrations_ran:
        check_tables_exist()
    else:
        check_tables_exist()
    bootstrap_single_metric_analytics_defaults()
    reset_processing_upload_tasks()
    reset_analytics_export_jobs()

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


async def unhandled_exception_handler(_: Request, exception: Exception) -> JSONResponse:
    logger.exception("Unhandled server error", exc_info=exception)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


async def application_exception_handler(
    _: Request, exception: ApplicationError
) -> JSONResponse:
    """Translate service-layer failures to the existing HTTP error shape."""

    return JSONResponse(
        status_code=exception.status_code,
        content={"detail": exception.detail},
    )


_reset_processing_upload_tasks = reset_processing_upload_tasks
_reset_analytics_export_jobs = reset_analytics_export_jobs


def create_app() -> FastAPI:
    """Build the stable ASGI application used by deployment and tests."""

    application = FastAPI(
        title="CLS Connex",
        docs_url=FASTAPI_DOCS_URL,
        redoc_url=FASTAPI_REDOC_URL,
        openapi_url=FASTAPI_OPENAPI_URL,
        root_path=FASTAPI_ROOT_PATH,
        lifespan=lifespan,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=CORS_ORIGINS,
        allow_credentials=CORS_ORIGINS != ["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.middleware("http")(log_request)
    application.add_exception_handler(Exception, unhandled_exception_handler)
    application.add_exception_handler(ApplicationError, application_exception_handler)
    add_pagination(application)
    application.include_router(operations_router)
    application.include_router(analytics.router)
    application.include_router(surveys.router)
    application.include_router(dashboard.router)
    application.include_router(strategy.router)
    application.include_router(stores.router)
    application.include_router(departments.router)
    application.include_router(tasks.router)
    application.include_router(channels.router)
    application.include_router(delivery_services.router)
    application.include_router(topics.router)
    application.include_router(translator.router)
    install_openapi_component_compatibility(application)
    return application


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
