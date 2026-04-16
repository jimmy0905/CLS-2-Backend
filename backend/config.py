import os
import dotenv

dotenv.load_dotenv()

PATH_TO_UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), "upload_tasks")

DATABASE_USER = os.getenv("DATABASE_USER")
DATABASE_PASSWORD = os.getenv("DATABASE_PASSWORD")
DATABASE_HOST = os.getenv("DATABASE_HOST")
DATABASE_PORT = os.getenv("DATABASE_PORT")
DATABASE_NAME = os.getenv("DATABASE_NAME")

SQLALCHEMY_DATABASE_URI = f"postgresql://{DATABASE_USER}:{DATABASE_PASSWORD}@{DATABASE_HOST}:{DATABASE_PORT}/{DATABASE_NAME}"

# Multi-threading configuration for survey processing
MAX_WORKER_THREADS = int(os.getenv("MAX_WORKER_THREADS", "4"))  # Default to 4 threads


def parse_bool_env(env_name: str, default: bool = False) -> bool:
    raw_value = os.getenv(env_name)
    if raw_value is None:
        return default

    normalized_value = raw_value.strip().lower()
    if not normalized_value:
        return default

    if normalized_value in {"1", "true", "yes", "on"}:
        return True
    if normalized_value in {"0", "false", "no", "off"}:
        return False
    return default


def is_survey_export_column_enabled(column_name: str) -> bool:
    env_name = f"SURVEY_EXPORT_COLUMN_{column_name.upper()}"
    return parse_bool_env(env_name, default=False)