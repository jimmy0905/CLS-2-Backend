"""Structured application logging with stdout and optional persistent files."""

import contextvars
import json
import logging
import sys
import threading
import time
from datetime import UTC, datetime, timedelta
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import Any

from core.config import (
    DEPLOYMENT_PROFILE,
    LOG_SERVICE_NAME,
    SERVER_LOG_FILE,
    SERVER_LOG_FORMAT,
    SERVER_LOG_LEVEL,
    SERVER_LOG_RETENTION_DAYS,
)

request_id_context: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_id", default="-"
)

_DIAGNOSTIC_LOCK = threading.Lock()
_LAST_DIAGNOSTIC_AT: dict[str, float] = {}
_DIAGNOSTIC_INTERVAL_SECONDS = 60.0
_STRUCTURED_EXTRA_FIELDS = (
    "event",
    "request_id",
    "service",
    "deployment_profile",
    "method",
    "path",
    "status_code",
    "duration_ms",
    "client_ip",
    "count",
    "retention_cutoff",
    "survey_count",
    "action_id",
    "response_length",
    "response_type",
    "error_type",
    "upload_task_id",
    "export_job_id",
    "sequence",
    "elapsed_seconds",
    "remaining_seconds",
    "profile",
    "job_count",
)


def bind_request_id(request_id: str) -> contextvars.Token[str]:
    """Bind a request identifier to log records emitted in this context."""
    return request_id_context.set(request_id)


def reset_request_id(token: contextvars.Token[str]) -> None:
    """Restore the request identifier that preceded ``bind_request_id``."""
    request_id_context.reset(token)


class LogContextFilter(logging.Filter):
    """Populate stable deployment and request metadata on every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = getattr(record, "request_id", request_id_context.get())
        record.service = getattr(record, "service", LOG_SERVICE_NAME)
        record.deployment_profile = getattr(
            record, "deployment_profile", DEPLOYMENT_PROFILE
        )
        return True


class JsonFormatter(logging.Formatter):
    """Render safe, machine-readable logs without HTTP bodies or credentials."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "source": {
                "module": record.module,
                "function": record.funcName,
                "line": record.lineno,
            },
            "process_id": record.process,
            "thread_name": record.threadName,
        }
        for field in _STRUCTURED_EXTRA_FIELDS:
            value = getattr(record, field, None)
            if value not in (None, ""):
                payload[field] = value
        if record.exc_info:
            payload["exception"] = self._format_exception(record)
        return json.dumps(payload, default=str, ensure_ascii=False)

    def _format_exception(self, record: logging.LogRecord) -> dict[str, Any]:
        exc_info = record.exc_info
        if exc_info is None or exc_info[0] is None or exc_info[1] is None:
            return {
                "type": "Exception",
                "message": "Exception details are unavailable",
                "stack_trace": "",
            }

        exception_type, exception, traceback = exc_info
        payload: dict[str, Any] = {
            "type": exception_type.__name__,
            "message": str(exception),
            "stack_trace": self.formatException((exception_type, exception, traceback)),
        }
        cause = exception.__cause__ or exception.__context__
        if cause is not None:
            payload["cause"] = {
                "type": type(cause).__name__,
                "message": str(cause),
            }
        return payload


class TextFormatter(logging.Formatter):
    """Human-readable alternative that retains correlation and source details."""

    @staticmethod
    def converter(timestamp: float | None) -> time.struct_time:
        return time.gmtime(0 if timestamp is None else timestamp)

    def __init__(self) -> None:
        super().__init__(
            "%(asctime)s %(levelname)s %(name)s service=%(service)s "
            "profile=%(deployment_profile)s request_id=%(request_id)s "
            "source=%(module)s.%(funcName)s:%(lineno)d %(message)s"
        )


def _formatter() -> logging.Formatter:
    if SERVER_LOG_FORMAT == "json":
        return JsonFormatter()
    return TextFormatter()


def _build_stdout_handler(formatter: logging.Formatter) -> logging.Handler:
    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(LogContextFilter())
    handler.setFormatter(formatter)
    return handler


def _emit_file_logging_diagnostic(error: BaseException, event: str) -> None:
    """Report logging-sink failures without recursively invoking logging."""
    now = time.monotonic()
    with _DIAGNOSTIC_LOCK:
        last_reported_at = _LAST_DIAGNOSTIC_AT.get(event, 0.0)
        if now - last_reported_at < _DIAGNOSTIC_INTERVAL_SECONDS:
            return
        _LAST_DIAGNOSTIC_AT[event] = now

    payload = {
        "timestamp": datetime.now(tz=UTC).isoformat(),
        "level": "CRITICAL",
        "logger": "clsense.logging",
        "event": event,
        "message": "Persistent log sink is unavailable; continuing with stdout only",
        "service": LOG_SERVICE_NAME,
        "deployment_profile": DEPLOYMENT_PROFILE,
        "error_type": type(error).__name__,
        "exception": {
            "type": type(error).__name__,
            "message": str(error),
        },
    }
    try:
        sys.stderr.write(json.dumps(payload, default=str, ensure_ascii=False) + "\n")
        sys.stderr.flush()
    except OSError:
        pass


class ResilientTimedRotatingFileHandler(TimedRotatingFileHandler):
    """A rotating file sink that never makes logging failure fatal to the app."""

    def handleError(self, record: logging.LogRecord) -> None:
        error = sys.exc_info()[1]
        if isinstance(error, BaseException):
            _emit_file_logging_diagnostic(error, "logging.file_write_failed")


def _build_file_handler(formatter: logging.Formatter) -> logging.Handler | None:
    if not SERVER_LOG_FILE:
        return None

    try:
        log_path = Path(SERVER_LOG_FILE)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        handler: logging.Handler = ResilientTimedRotatingFileHandler(
            log_path,
            when="midnight",
            interval=1,
            backupCount=SERVER_LOG_RETENTION_DAYS,
            encoding="utf-8",
            utc=True,
        )
    except OSError as error:
        _emit_file_logging_diagnostic(error, "logging.file_initialization_failed")
        return None

    handler.addFilter(LogContextFilter())
    handler.setFormatter(formatter)
    return handler


def _replace_handlers(
    logger_to_configure: logging.Logger, handlers: list[logging.Handler]
) -> None:
    for existing_handler in logger_to_configure.handlers[:]:
        logger_to_configure.removeHandler(existing_handler)
        existing_handler.close()
    for handler in handlers:
        logger_to_configure.addHandler(handler)


def log_retention_cutoff(
    retention_days: int = SERVER_LOG_RETENTION_DAYS, now: datetime | None = None
) -> datetime:
    """Return the UTC cutoff used exclusively for rotated application logs."""
    return (now or datetime.now(tz=UTC)) - timedelta(days=retention_days)


def purge_rotated_log_files(
    now: datetime | None = None,
    log_file: str | None = None,
    retention_days: int = SERVER_LOG_RETENTION_DAYS,
) -> int:
    """Remove archived logs older than the configured application-log retention."""
    configured_log_file = SERVER_LOG_FILE if log_file is None else log_file
    if not configured_log_file:
        return 0

    log_path = Path(configured_log_file)
    if not log_path.parent.exists():
        return 0

    cutoff = log_retention_cutoff(retention_days=retention_days, now=now)
    deleted_count = 0
    for archived_log in log_path.parent.glob(f"{log_path.name}.*"):
        try:
            if not archived_log.is_file():
                continue
            modified_at = datetime.fromtimestamp(archived_log.stat().st_mtime, tz=UTC)
            if modified_at < cutoff:
                archived_log.unlink()
                deleted_count += 1
        except OSError as error:
            _emit_file_logging_diagnostic(error, "logging.file_cleanup_failed")
    return deleted_count


def configure_logging() -> None:
    """Configure one stdout sink and an optional persistent rotating file sink."""
    log_level = getattr(logging, SERVER_LOG_LEVEL, logging.INFO)
    formatter = _formatter()
    handlers = [_build_stdout_handler(formatter)]
    file_handler = _build_file_handler(formatter)
    if file_handler is not None:
        handlers.append(file_handler)

    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    _replace_handlers(root_logger, handlers)

    for logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uvicorn_logger = logging.getLogger(logger_name)
        _replace_handlers(uvicorn_logger, [])
        uvicorn_logger.setLevel(log_level)
        uvicorn_logger.propagate = True

    try:
        purge_rotated_log_files()
    except OSError as error:
        _emit_file_logging_diagnostic(error, "logging.file_cleanup_failed")


logger = logging.getLogger("clsense")
