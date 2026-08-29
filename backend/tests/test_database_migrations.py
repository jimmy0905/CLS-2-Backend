from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from infrastructure.database import migrations


def test_alembic_configuration_uses_the_backend_migration_directory() -> None:
    config = migrations._build_alembic_config()
    backend_dir = Path(__file__).resolve().parents[1]

    assert migrations.BACKEND_DIR == backend_dir
    assert migrations.MIGRATIONS_DIR == backend_dir / "migrations"
    assert migrations.GOAL_FIRST_ANALYTICS_MIGRATION.is_file()
    assert config.config_file_name == str(backend_dir / "alembic.ini")
    assert config.get_main_option("script_location") == str(backend_dir / "migrations")
