from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import sqlalchemy as sa

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "migrations"
    / "versions"
    / "2026_08_29_0016_remove_analytics_usage_and_query_rendering.py"
)


def _migration():
    spec = importlib.util.spec_from_file_location(
        "migration_0016_remove_analytics_rendering", MIGRATION_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_usage_removal_migration_strips_catalog_history_without_touching_audit() -> (
    None
):
    migration = _migration()
    assert migration.revision == "0016_remove_analytics_rendering"
    assert migration.down_revision == "0015_assignment_sentiment_avg"

    metadata = sa.MetaData()
    fields = sa.Table(
        "analytics_fields",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("definition", sa.JSON, nullable=False),
    )
    versions = sa.Table(
        "analytics_model_versions",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("definition_hash", sa.String(64), nullable=False),
        sa.Column("catalog_snapshot", sa.JSON, nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False),
    )
    query_logs = sa.Table(
        "analytics_query_logs",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("request", sa.JSON, nullable=False),
    )
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    metadata.create_all(engine)

    current_snapshot = {
        "cubeCatalog": {
            "profile": "wtchk_cls",
            "catalogVersion": 7,
            "fields": [{"slug": "score", "usage": "chart"}],
            "metrics": [],
        },
        "fields": [{"slug": "legacy_copy", "usage": "table_only"}],
        "charts": [{"slug": "keep_chart_metadata", "chart_type": "pie"}],
    }
    legacy_snapshot = {
        "profile": "wtchk_cls",
        "catalogVersion": 6,
        "fields": [{"slug": "legacy_score", "usage": "table_only"}],
        "metrics": [],
    }
    audit_request = {
        "metric": "survey",
        "aggregation": "count",
        "chart_type": "pie",
        "series_limit": 12,
    }

    with engine.begin() as connection:
        connection.execute(
            fields.insert(),
            {"id": 1, "definition": {"usage": "chart", "scope": "response"}},
        )
        connection.execute(
            versions.insert(),
            [
                {
                    "id": 1,
                    "definition_hash": "old-current",
                    "catalog_snapshot": current_snapshot,
                    "status": "published",
                    "is_active": True,
                },
                {
                    "id": 2,
                    "definition_hash": "old-legacy",
                    "catalog_snapshot": legacy_snapshot,
                    "status": "superseded",
                    "is_active": False,
                },
            ],
        )
        connection.execute(
            query_logs.insert(), {"id": "audit-1", "request": audit_request}
        )

        original_get_bind = migration.op.get_bind
        migration.op.get_bind = lambda: connection
        try:
            migration.upgrade()
            migration.downgrade()
        finally:
            migration.op.get_bind = original_get_bind

        stored_field = connection.execute(sa.select(fields.c.definition)).scalar_one()
        assert stored_field == {"scope": "response"}

        stored_versions = (
            connection.execute(sa.select(versions).order_by(versions.c.id))
            .mappings()
            .all()
        )
        assert [row["status"] for row in stored_versions] == ["published", "superseded"]
        assert [row["is_active"] for row in stored_versions] == [True, False]
        assert (
            stored_versions[0]["catalog_snapshot"]["charts"]
            == current_snapshot["charts"]
        )
        for row in stored_versions:
            snapshot = row["catalog_snapshot"]
            catalogs = [snapshot]
            if isinstance(snapshot.get("cubeCatalog"), dict):
                catalogs.append(snapshot["cubeCatalog"])
            for catalog in catalogs:
                fields = catalog.get("fields", [])
                assert all("usage" not in field for field in fields)
            expected_hash = migration._snapshot_hash(snapshot)
            assert row["definition_hash"] == expected_hash

        assert (
            connection.execute(sa.select(query_logs.c.request)).scalar_one()
            == audit_request
        )


def test_usage_removal_hash_uses_canonical_snapshot_json() -> None:
    migration = _migration()
    snapshot = {"b": 2, "a": {"nested": True}}
    expected = migration._snapshot_hash(snapshot)
    assert expected == migration._snapshot_hash(json.loads(json.dumps(snapshot)))
