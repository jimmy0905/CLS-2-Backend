from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from infrastructure.database import migrations
from infrastructure.database import analytics_schema


def test_alembic_configuration_uses_the_backend_migration_directory() -> None:
    config = migrations._build_alembic_config()
    backend_dir = Path(__file__).resolve().parents[1]

    assert migrations.BACKEND_DIR == backend_dir
    assert migrations.MIGRATIONS_DIR == backend_dir / "migrations"
    assert migrations.GOAL_FIRST_ANALYTICS_MIGRATION.is_file()
    assert config.config_file_name == str(backend_dir / "alembic.ini")
    assert config.get_main_option("script_location") == str(backend_dir / "migrations")


def test_analytics_schema_contract_covers_cube_objects() -> None:
    assert len(analytics_schema._VIEW_NAMES) == 5
    assert len(analytics_schema._FUNCTION_SIGNATURES) == 8
    assert "analytics_survey_assignments" in analytics_schema._REQUIRED_OBJECTS_SQL
    assert "analytics_raw_timestamp(json,text)" in analytics_schema._REQUIRED_OBJECTS_SQL
