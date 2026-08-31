"""Architecture guardrails for the incremental feature-first migration."""

# ruff: noqa: E402

from __future__ import annotations

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from infrastructure.database.registry import Base


def test_database_registry_loads_every_preserved_mapping() -> None:
    assert len(Base.metadata.tables) == 20
    assert set(Base.metadata.tables) == {
        "analytics_audit_logs",
        "analytics_charts",
        "analytics_export_jobs",
        "analytics_fields",
        "analytics_field_values",
        "analytics_metrics",
        "analytics_model_versions",
        "analytics_query_logs",
        "channels",
        "delivery_services",
        "departments",
        "keywords",
        "stores",
        "surveys",
        "survey_departments",
        "survey_keywords",
        "survey_topics",
        "topics",
        "upload_tasks",
        "upload_task_errors",
    }


def test_dbo_layer_does_not_depend_on_legacy_models_or_utilities() -> None:
    for path in (BACKEND / "infrastructure" / "database" / "dbo").glob("*.py"):
        source = path.read_text()
        assert "from models." not in source, path
        assert "from utils." not in source, path


def test_migrated_master_data_endpoints_do_not_issue_sql_or_transactions() -> None:
    endpoints = BACKEND / "features" / "master_data" / "endpoints"
    for name in (
        "channels.py",
        "departments.py",
        "delivery_services.py",
        "stores.py",
        "topics.py",
    ):
        source = (endpoints / name).read_text()
        assert "db.query(" not in source, name
        assert "db.commit(" not in source, name
        assert "db.add(" not in source, name
        assert "db.delete(" not in source, name


def test_backend_identity_surface_is_bearer_only() -> None:
    identity = BACKEND / "features" / "identity"
    assert not (identity / "endpoints" / "auth.py").exists()
    assert not (identity / "endpoints" / "users.py").exists()
    security_source = (BACKEND / "core" / "security.py").read_text()
    assert "get_db" not in security_source
    assert "User" not in security_source


def test_operations_health_endpoint_delegates_database_access() -> None:
    source = (BACKEND / "features" / "operations" / "endpoint.py").read_text()
    assert "db.execute(" not in source


def test_legacy_mixed_purpose_packages_are_removed() -> None:
    for legacy_path in ("models", "routers", "utils", "config.py"):
        assert not (BACKEND / legacy_path).exists()
