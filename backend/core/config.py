import os
from pathlib import Path

import dotenv


dotenv.load_dotenv()

# This module moved under ``core``; runtime storage remains rooted at backend/.
BACKEND_DIR = Path(__file__).resolve().parent.parent
PATH_TO_UPLOAD_FOLDER = BACKEND_DIR / "upload_tasks"


def parse_bool_env(env_name: str, default: bool = False) -> bool:
    raw_value = os.getenv(env_name)
    if raw_value is None or not raw_value.strip():
        return default

    normalized_value = raw_value.strip().lower()
    if normalized_value in {"1", "true", "yes", "on"}:
        return True
    if normalized_value in {"0", "false", "no", "off"}:
        return False
    return default


def parse_strict_bool_env(env_name: str, default: bool = False) -> bool:
    raw_value = os.getenv(env_name)
    if raw_value is None or not raw_value.strip():
        return default

    normalized_value = raw_value.strip().lower()
    if normalized_value in {"1", "true", "yes", "on"}:
        return True
    if normalized_value in {"0", "false", "no", "off"}:
        return False

    raise ValueError(f"{env_name} must be one of: 1, true, yes, on, 0, false, no, off")


def parse_positive_int_env(env_name: str, default: int) -> int:
    raw_value = os.getenv(env_name)
    if raw_value is None or not raw_value.strip():
        return default

    try:
        value = int(raw_value)
    except ValueError as error:
        raise ValueError(f"{env_name} must be a positive integer") from error

    if value < 1:
        raise ValueError(f"{env_name} must be a positive integer")
    return value


def parse_csv_env(env_name: str, default: str = "") -> list[str]:
    raw_value = os.getenv(env_name, default)
    return [value.strip() for value in raw_value.split(",") if value.strip()]


DATABASE_USER = os.getenv("DATABASE_USER")
DATABASE_PASSWORD = os.getenv("DATABASE_PASSWORD")
DATABASE_HOST = os.getenv("DATABASE_HOST")
DATABASE_PORT = os.getenv("DATABASE_PORT")
DATABASE_NAME = os.getenv("DATABASE_NAME")
SQLALCHEMY_DATABASE_URI = (
    f"postgresql://{DATABASE_USER}:{DATABASE_PASSWORD}@"
    f"{DATABASE_HOST}:{DATABASE_PORT}/{DATABASE_NAME}"
)

# Deployment identity. These values are supplied by each Compose profile.
DEPLOYMENT_PROFILE = os.getenv("DEPLOYMENT_PROFILE", "local")
LOG_SERVICE_NAME = os.getenv("LOG_SERVICE_NAME", "clsense-backend")
IS_ECLS_ENABLED = parse_strict_bool_env("IS_ECLS_ENABLED", default=False)

# HTTP and session settings.
FASTAPI_DOCS_URL = os.getenv("FASTAPI_DOCS_URL") or None
FASTAPI_OPENAPI_URL = os.getenv("FASTAPI_OPENAPI_URL") or None
FASTAPI_REDOC_URL = os.getenv("FASTAPI_REDOC_URL") or None
FASTAPI_ROOT_PATH = os.getenv("FASTAPI_ROOT_PATH", "")
CORS_ORIGINS = parse_csv_env("CORS_ORIGINS", "*")
COOKIE_SECURE = parse_strict_bool_env("COOKIE_SECURE", default=True)

# Server logging is written to stdout by default for container collection.
SERVER_LOG_LEVEL = os.getenv("SERVER_LOG_LEVEL", "INFO").upper()
SERVER_LOG_FORMAT = os.getenv("SERVER_LOG_FORMAT", "json").lower()
SERVER_LOG_FILE = os.getenv("SERVER_LOG_FILE", "").strip()

# Retention applies only to operational/audit records and optional rotated log files.
DATA_RETENTION_DAYS = parse_positive_int_env("DATA_RETENTION_DAYS", default=30)
RETENTION_CHECK_INTERVAL_SECONDS = parse_positive_int_env(
    "RETENTION_CHECK_INTERVAL_SECONDS", default=86_400
)

# Multi-threading configuration for survey processing.
MAX_WORKER_THREADS = parse_positive_int_env("MAX_WORKER_THREADS", default=4)

# Governed analytics is additive and remains disabled for every profile until
# that profile has completed the shadow-comparison rollout.
ANALYTICS_ENABLED = parse_strict_bool_env("ANALYTICS_ENABLED", default=False)
ANALYTICS_CUBE_API_URL = os.getenv(
    "ANALYTICS_CUBE_API_URL", "http://cube-api:4000"
).rstrip("/")
ANALYTICS_CUBE_API_SECRET = os.getenv("ANALYTICS_CUBE_API_SECRET", "")
ANALYTICS_INTERNAL_METADATA_SECRET = os.getenv("ANALYTICS_INTERNAL_METADATA_SECRET", "")
ANALYTICS_QUERY_TIMEOUT_SECONDS = parse_positive_int_env(
    "ANALYTICS_QUERY_TIMEOUT_SECONDS", default=30
)
ANALYTICS_CUBE_REFRESH_TIME_ZONES = tuple(
    parse_csv_env("ANALYTICS_CUBE_REFRESH_TIME_ZONES", "UTC,Asia/Hong_Kong")
)
ANALYTICS_DRILLDOWN_STATEMENT_TIMEOUT_MS = parse_positive_int_env(
    "ANALYTICS_DRILLDOWN_STATEMENT_TIMEOUT_MS", default=10_000
)
ANALYTICS_DRILLDOWN_CONCURRENCY = parse_positive_int_env(
    "ANALYTICS_DRILLDOWN_CONCURRENCY", default=8
)
ANALYTICS_EXPORT_MAX_ROWS = parse_positive_int_env(
    "ANALYTICS_EXPORT_MAX_ROWS", default=250_000
)
ANALYTICS_EXPORT_WORKER_CONCURRENCY = parse_positive_int_env(
    "ANALYTICS_EXPORT_WORKER_CONCURRENCY", default=2
)
ANALYTICS_EXPORT_MAX_OUTSTANDING_PER_USER = parse_positive_int_env(
    "ANALYTICS_EXPORT_MAX_OUTSTANDING_PER_USER", default=2
)
ANALYTICS_EXPORT_MAX_OUTSTANDING_PROFILE = parse_positive_int_env(
    "ANALYTICS_EXPORT_MAX_OUTSTANDING_PROFILE", default=20
)
ANALYTICS_EXPORT_EXPIRY_HOURS = parse_positive_int_env(
    "ANALYTICS_EXPORT_EXPIRY_HOURS", default=24
)
ANALYTICS_GOVERNANCE_RETENTION_DAYS = parse_positive_int_env(
    "ANALYTICS_GOVERNANCE_RETENTION_DAYS", default=365
)
ANALYTICS_EXPORT_DIR = Path(
    os.getenv("ANALYTICS_EXPORT_DIR", str(BACKEND_DIR / "analytics_exports"))
).resolve()

DATABASE_AUTO_MIGRATE = parse_strict_bool_env("DATABASE_AUTO_MIGRATE", default=True)
DATABASE_AUTO_GENERATE_MIGRATIONS = parse_strict_bool_env(
    "DATABASE_AUTO_GENERATE_MIGRATIONS", default=False
)
DATABASE_BOOTSTRAP_SCHEMA = parse_strict_bool_env(
    "DATABASE_BOOTSTRAP_SCHEMA", default=False
)
BOOTSTRAP_DEFAULT_ADMIN = parse_strict_bool_env(
    "BOOTSTRAP_DEFAULT_ADMIN", default=False
)
BOOTSTRAP_DEFAULT_ADMIN_USERNAME = os.getenv(
    "BOOTSTRAP_DEFAULT_ADMIN_USERNAME", "admin"
)
BOOTSTRAP_DEFAULT_ADMIN_PASSWORD = os.getenv("BOOTSTRAP_DEFAULT_ADMIN_PASSWORD")


def is_survey_export_column_enabled(column_name: str) -> bool:
    return parse_bool_env(f"SURVEY_EXPORT_COLUMN_{column_name.upper()}", default=False)
