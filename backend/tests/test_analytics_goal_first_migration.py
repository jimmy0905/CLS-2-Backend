from __future__ import annotations

from datetime import datetime, timezone
import importlib.util
from pathlib import Path
import sys

import pytest
import sqlalchemy as sa


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from features.analytics.endpoints.analytics import _catalog_from_records
from features.analytics.model.semantic import metric_targets, validate_chart_definition


MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "migrations"
    / "versions"
    / "2026_08_28_0013_migrate_goal_first_analytics.py"
)


def _migration():
    spec = importlib.util.spec_from_file_location(
        "migration_0013_goal_first_analytics", MIGRATION_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_goal_first_migration_follows_immutable_0012() -> None:
    migration = _migration()
    assert migration.revision == "0013_goal_first_analytics"
    assert migration.down_revision == "0012_single_metric_charts"


def test_goal_first_defaults_have_unique_stable_slugs_and_public_targets() -> None:
    migration = _migration()
    catalog = _catalog_from_records([], [])
    published = {
        view: {
            (target.metric, aggregation.method.value)
            for target in metric_targets(catalog, view)
            for aggregation in target.aggregations
        }
        for view in catalog.views
    }
    slugs = [chart["slug"] for chart in migration._DEFAULT_CHARTS]

    assert len(slugs) == len(set(slugs)) == 13
    assert "dashboard_keyword_analysis" in slugs
    for chart in migration._DEFAULT_CHARTS:
        definition = chart["definition"]
        assert (
            definition["metric"],
            definition["aggregation"],
        ) in published[chart["semantic_view"]]
        assert definition["metric"] not in {"id", "assignment_id", "survey_id"}
        validate_chart_definition(
            chart["chart_type"],
            definition["dimensions"],
            definition["metric"],
            definition["aggregation"],
            catalog,
            semantic_view=chart["semantic_view"],
            time_dimension=definition.get("time_dimension"),
            time_granularity=definition.get("time_granularity"),
        )


def test_goal_first_archive_and_snapshot_markers_preserve_downgrade_state() -> None:
    migration = _migration()
    archived_at = datetime(2026, 8, 27, tzinfo=timezone.utc)
    archived = migration._archive_definition(
        {"metric": "id", "aggregation": "count"},
        original_slug="responses_by_store",
        original_status="published",
        original_archived_at=archived_at,
    )
    marker = archived[migration._MIGRATION_MARKER]

    assert marker["original_slug"] == "responses_by_store"
    assert marker["original_status"] == "published"
    assert marker["original_archived_at"] == archived_at.isoformat()

    snapshot = migration._replacement_snapshot(
        {
            "cubeCatalog": {
                "profile": "wtchk_cls",
                "catalogVersion": 8,
                "fields": [],
                "metrics": [],
                "rollups": [{"name": "legacy"}],
            },
            "charts": [{"slug": "legacy"}],
        },
        [{"slug": "dashboard_keyword_analysis"}],
        next_version=9,
        previous_active_id=4,
        seeded_chart_ids=[12, 11],
    )
    assert snapshot["cubeCatalog"]["catalogVersion"] == 9
    assert snapshot["cubeCatalog"]["rollups"] == []
    assert snapshot["charts"] == [{"slug": "dashboard_keyword_analysis"}]
    assert snapshot[migration._MIGRATION_MARKER]["seeded_chart_ids"] == [11, 12]


def test_goal_first_defaults_fail_closed_on_local_target_ambiguity() -> None:
    migration = _migration()
    snapshot = {
        "cubeCatalog": {
            "metrics": [
                {
                    "semanticView": "survey_responses",
                    "queryTarget": "survey",
                    "publicAggregation": "count",
                }
            ]
        }
    }
    with pytest.raises(RuntimeError, match="conflict"):
        migration._validate_default_metric_targets(snapshot)


def test_goal_first_upgrade_and_downgrade_round_trip() -> None:
    migration = _migration()
    metadata = sa.MetaData()
    users = sa.Table(
        "users",
        metadata,
        sa.Column("id", sa.CHAR(36), primary_key=True),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("is_deleted", sa.Boolean, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    versions = sa.Table(
        "analytics_model_versions",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("catalog_version", sa.BigInteger, nullable=False, unique=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("definition_hash", sa.String(64), nullable=False),
        sa.Column("catalog_snapshot", sa.JSON, nullable=False),
        sa.Column("validation_errors", sa.JSON, nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False),
        sa.Column("created_by_id", sa.CHAR(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("activated_at", sa.DateTime(timezone=True)),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
    )
    charts = sa.Table(
        "analytics_charts",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("slug", sa.String(64), unique=True),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("description", sa.Text),
        sa.Column("chart_type", sa.String(16), nullable=False),
        sa.Column("semantic_view", sa.String(32)),
        sa.Column("definition", sa.JSON, nullable=False),
        sa.Column("visibility", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("validation_errors", sa.JSON, nullable=False),
        sa.Column("created_by_id", sa.CHAR(36), nullable=False),
        sa.Column("published_model_version_id", sa.Integer),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("validated_at", sa.DateTime(timezone=True)),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
    )
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    metadata.create_all(engine)
    now = datetime(2026, 8, 27, 9, tzinfo=timezone.utc)
    original_snapshot = {
        "cubeCatalog": {
            "profile": "wtchk_cls",
            "catalogVersion": 12,
            "fields": [],
            "metrics": [],
            "rollups": [{"name": "single_metric_rollup"}],
        },
        "charts": [{"slug": "dashboard_sentiment_distribution"}],
    }

    class SQLiteMigrationConnection:
        def __init__(self, connection):
            self.connection = connection

        def execute(self, statement, *args, **kwargs):
            sql = str(statement).strip()
            if sql.startswith("LOCK TABLE") or sql.startswith("SELECT setval"):
                return self.connection.execute(sa.select(sa.literal(1)))
            return self.connection.execute(statement, *args, **kwargs)

    with engine.begin() as connection:
        connection.execute(
            users.insert(),
            {"id": "owner", "role": "admin", "is_deleted": False, "created_at": now},
        )
        active_id = connection.execute(
            versions.insert()
            .values(
                catalog_version=12,
                status="published",
                definition_hash="old",
                catalog_snapshot=original_snapshot,
                validation_errors=[],
                is_active=True,
                created_by_id="owner",
                created_at=now,
                published_at=now,
                activated_at=now,
            )
            .returning(versions.c.id)
        ).scalar_one()
        originals = (
            (
                "dashboard_sentiment_distribution",
                "published",
                {"dimensions": ["topic_sentiment"], "metric": "id", "aggregation": "count"},
            ),
            (
                "custom_single_metric_chart",
                "draft",
                {"dimensions": ["store_format"], "metric": "id", "aggregation": "count"},
            ),
        )
        for slug, status, definition in originals:
            connection.execute(
                charts.insert().values(
                    slug=slug,
                    title=slug,
                    chart_type="table",
                    semantic_view="survey_responses",
                    definition=definition,
                    visibility="viewer",
                    status=status,
                    validation_errors=[],
                    created_by_id="owner",
                    published_model_version_id=active_id,
                    created_at=now,
                    updated_at=now,
                )
            )

        wrapped = SQLiteMigrationConnection(connection)
        migration._apply_upgrade(wrapped)

        upgraded = connection.execute(sa.select(charts).order_by(charts.c.id)).mappings().all()
        legacy = [row for row in upgraded if migration._MIGRATION_MARKER in row["definition"]]
        seeded = [row for row in upgraded if row["id"] not in {item["id"] for item in legacy}]
        assert len(legacy) == 2
        assert all(row["status"] == "archived" for row in legacy)
        assert all(row["slug"] == f"legacy_0013_{row['id']}" for row in legacy)
        assert len(seeded) == 13
        assert all(row["definition"]["metric"] not in {"id", "assignment_id", "survey_id"} for row in seeded)
        upgraded_active = connection.execute(
            sa.select(versions).where(versions.c.is_active.is_(True))
        ).mappings().one()
        assert upgraded_active["catalog_snapshot"]["cubeCatalog"]["rollups"] == []
        assert len(upgraded_active["catalog_snapshot"]["charts"]) == 13

        original_get_bind = migration.op.get_bind
        migration.op.get_bind = lambda: wrapped
        try:
            migration.downgrade()
        finally:
            migration.op.get_bind = original_get_bind

        restored = connection.execute(sa.select(charts).order_by(charts.c.id)).mappings().all()
        assert [row["slug"] for row in restored] == [item[0] for item in originals]
        assert [row["status"] for row in restored] == [item[1] for item in originals]
        assert [row["definition"] for row in restored] == [item[2] for item in originals]
        rollback_active = connection.execute(
            sa.select(versions).where(versions.c.is_active.is_(True))
        ).mappings().one()
        assert rollback_active["catalog_version"] > upgraded_active["catalog_version"]
        assert rollback_active["catalog_snapshot"]["charts"] == original_snapshot["charts"]
