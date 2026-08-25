import contextvars
import json
import logging
import sys
from datetime import datetime, timezone
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import Any

from config import (
    DATA_RETENTION_DAYS,
    DEPLOYMENT_PROFILE,
    LOG_SERVICE_NAME,
    SERVER_LOG_FILE,
    SERVER_LOG_FORMAT,
    SERVER_LOG_LEVEL,
)


request_id_context: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_id", default="-"
)


def bind_request_id(request_id: str) -> contextvars.Token[str]:
    return request_id_context.set(request_id)


def reset_request_id(token: contextvars.Token[str]) -> None:
    request_id_context.reset(token)


class LogContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = getattr(record, "request_id", request_id_context.get())
        record.service = getattr(record, "service", LOG_SERVICE_NAME)
        record.deployment_profile = getattr(
            record, "deployment_profile", DEPLOYMENT_PROFILE
        )
        return True


class JsonFormatter(logging.Formatter):
    _EXTRA_FIELDS = (
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
    )

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(
                record.created, tz=timezone.utc
            ).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for field in self._EXTRA_FIELDS:
            value = getattr(record, field, None)
            if value not in (None, ""):
                payload[field] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, ensure_ascii=False)


def _build_handler() -> logging.Handler:
    if SERVER_LOG_FILE:
        log_path = Path(SERVER_LOG_FILE)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        handler: logging.Handler = TimedRotatingFileHandler(
            log_path,
            when="midnight",
            interval=1,
            backupCount=DATA_RETENTION_DAYS,
            encoding="utf-8",
            utc=True,
        )
    else:
        handler = logging.StreamHandler(sys.stdout)

    handler.addFilter(LogContextFilter())
    if SERVER_LOG_FORMAT == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)s %(name)s service=%(service)s "
                "profile=%(deployment_profile)s request_id=%(request_id)s %(message)s"
            )
        )
    return handler


def configure_logging() -> None:
    log_level = getattr(logging, SERVER_LOG_LEVEL, logging.INFO)
    handler = _build_handler()
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    root_logger.handlers.clear()
    root_logger.addHandler(handler)

    for logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uvicorn_logger = logging.getLogger(logger_name)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.setLevel(log_level)
        uvicorn_logger.propagate = True


logger = logging.getLogger("clsense")
