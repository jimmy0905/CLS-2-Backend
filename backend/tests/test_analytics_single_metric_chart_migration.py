from __future__ import annotations

from datetime import datetime, timezone
import importlib.util
from pathlib import Path
import sys

import sqlalchemy as sa
import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "migrations"
    / "versions"
    / "2026_08_28_0012_migrate_single_metric_analytics_charts.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location(
        "migration_0012_single_metric_charts", MIGRATION_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_single_metric_chart_migration_follows_0011() -> None:
    migration = _load_migration()

    assert migration.revision == "0012_single_metric_charts"
    assert migration.down_revision == "0011_default_analytics_charts"


def test_replacement_defaults_use_the_single_metric_contract() -> None:
    migration = _load_migration()
    charts = migration._DEFAULT_CHARTS

    assert len(charts) == 13
    assert len({chart["slug"] for chart in charts}) == len(charts)
    assert {chart["slug"] for chart in charts} == {
        "dashboard_sentiment_distribution",
        "dashboard_store_distribution",
        "dashboard_store_format_distribution",
        "dashboard_channel_delivery_distribution",
        "dashboard_topic_sentiment_counts",
        "dashboard_overall_topic_sentiment_score",
        "dashboard_mixed_topic_sentiment_score",
        "dashboard_topic_distribution",
        "dashboard_department_distribution",
        "dashboard_keyword_analysis",
        "dashboard_first_reported_at",
        "dashboard_last_reported_at",
        "dashboard_last_updated_at",
    }

    for chart in charts:
        definition = chart["definition"]
        assert "metrics" not in definition
        assert isinstance(definition["metric"], str)
        assert definition["aggregation"] in {
            "count",
            "distinct_count",
            "sum",
            "average",
            "min",
            "max",
            "median",
        }
        assert len(definition["dimensions"]) <= 3
        assert definition.get("time_dimension") not in definition["dimensions"]
        assert all(
            order["member"]
            in {
                *definition["dimensions"],
                "value",
                definition.get("time_dimension"),
            }
            for order in definition.get("order", [])
        )


def test_replacement_defaults_follow_chart_shape_matrix() -> None:
    migration = _load_migration()
    by_slug = {chart["slug"]: chart for chart in migration._DEFAULT_CHARTS}

    trend = by_slug["dashboard_sentiment_distribution"]
    assert trend["chart_type"] == "line"
    assert trend["definition"]["dimensions"] == ["topic_sentiment"]
    assert trend["definition"]["time_dimension"] == "reported_at"
    assert trend["definition"]["time_granularity"] == "day"
    assert trend["definition"]["metric"] == "id"
    assert trend["definition"]["aggregation"] == "count"

    for slug in {
        "dashboard_store_distribution",
        "dashboard_store_format_distribution",
        "dashboard_topic_distribution",
        "dashboard_department_distribution",
        "dashboard_keyword_analysis",
    }:
        chart = by_slug[slug]
        assert chart["chart_type"] == "stacked_bar"
        assert len(chart["definition"]["dimensions"]) == 2
        assert chart["definition"]["dimensions"][-1] in {
            "topic_sentiment",
            "sentiment",
        }
        assert chart["definition"]["aggregation"] == "count"

    channel = by_slug["dashboard_channel_delivery_distribution"]
    assert channel["chart_type"] == "table"
    assert channel["definition"]["dimensions"] == [
        "channel_name",
        "delivery_service_name",
        "topic_sentiment",
    ]

    for slug in {
        "dashboard_overall_topic_sentiment_score",
        "dashboard_mixed_topic_sentiment_score",
        "dashboard_first_reported_at",
        "dashboard_last_reported_at",
        "dashboard_last_updated_at",
    }:
        assert by_slug[slug]["chart_type"] == "kpi"
        assert by_slug[slug]["definition"]["dimensions"] == []


def test_replacement_defaults_validate_against_the_chart_input_model() -> None:
    migration = _load_migration()
    from features.analytics.endpoints.analytics import ChartInput

    for chart in migration._DEFAULT_CHARTS:
        parsed = ChartInput.model_validate({**chart, "visibility": "viewer"})
        assert parsed.definition.metric == chart["definition"]["metric"]


def test_legacy_marker_round_trip_preserves_original_state() -> None:
    migration = _load_migration()
    prior_marker = {"owned": "by-user"}
    definition = {
        "dimensions": ["store_format"],
        "metrics": ["response_count"],
        migration._MIGRATION_MARKER: prior_marker,
    }
    archived_at = datetime(2026, 8, 1, 12, 30, tzinfo=timezone.utc)

    archived = migration._archive_definition(
        definition,
        original_slug="custom_chart",
        original_status="draft",
        original_archived_at=archived_at,
    )
    restored, state = migration._restore_definition(archived)

    assert restored == definition
    assert state == {
        "original_slug": "custom_chart",
        "original_status": "draft",
        "original_archived_at": archived_at,
    }
    assert migration._legacy_slug(42) == "legacy_0012_42"


def test_replacement_snapshot_preserves_catalog_and_clears_stale_rollups() -> None:
    migration = _load_migration()
    active_snapshot = {
        "cubeCatalog": {
            "catalogVersion": 11,
            "fields": [{"slug": "store_format"}],
            "metrics": [{"slug": "response_count"}],
            "rollups": [{"metrics": ["response_count", "other_metric"]}],
        },
        "charts": [{"slug": "legacy"}],
        "extension": {"keep": True},
    }
    replacement_charts = [{"id": 21, "slug": "dashboard_sentiment_distribution"}]

    snapshot = migration._replacement_snapshot(
        active_snapshot,
        replacement_charts,
        next_version=12,
        previous_active_id=7,
        previous_active_status="published",
        previous_active_archived_at=None,
        seeded_chart_ids=[21],
    )

    assert snapshot["cubeCatalog"]["catalogVersion"] == 12
    assert snapshot["cubeCatalog"]["fields"] == [{"slug": "store_format"}]
    assert snapshot["cubeCatalog"]["metrics"] == [{"slug": "response_count"}]
    assert snapshot["cubeCatalog"]["rollups"] == []
    assert snapshot["charts"] == replacement_charts
    assert snapshot["extension"] == {"keep": True}
    assert snapshot[migration._MIGRATION_MARKER] == {
        "revision": migration.revision,
        "kind": "catalog_v2",
        "previous_active_id": 7,
        "previous_active_status": "published",
        "previous_active_archived_at": None,
        "seeded_chart_ids": [21],
    }


def test_bootstrap_snapshot_requires_profile_and_default_pairs_fail_closed(
    monkeypatch,
) -> None:
    migration = _load_migration()
    monkeypatch.delenv("DEPLOYMENT_PROFILE", raising=False)
    with pytest.raises(RuntimeError, match="DEPLOYMENT_PROFILE"):
        migration._bootstrap_snapshot()

    monkeypatch.setenv("DEPLOYMENT_PROFILE", "wtchk_cls")
    bootstrap = migration._bootstrap_snapshot()
    assert bootstrap["cubeCatalog"] == {
        "profile": "wtchk_cls",
        "catalogVersion": 0,
        "fields": [],
        "metrics": [],
        "rollups": [],
    }

    conflicting = {
        "cubeCatalog": {
            "metrics": [
                {
                    "slug": "duplicate_response_count",
                    "semanticView": "survey_responses",
                    "sourceField": "id",
                    "operation": "count",
                    "visibility": "viewer",
                }
            ]
        }
    }
    with pytest.raises(RuntimeError, match="survey_responses/id/count"):
        migration._validate_default_metric_pairs(conflicting)

    conflicting["cubeCatalog"]["metrics"][0]["visibility"] = "admin"
    with pytest.raises(RuntimeError, match="survey_responses/id/count"):
        migration._validate_default_metric_pairs(conflicting)


def test_empty_install_bootstrap_requires_owner_and_empty_catalog(monkeypatch) -> None:
    migration = _load_migration()

    class ScalarResult:
        def __init__(self, value: int):
            self.value = value

        def scalar_one(self) -> int:
            return self.value

    class BootstrapConnection:
        def __init__(self, counts: list[int]):
            self.counts = iter(counts)

        def execute(self, statement, *args, **kwargs):
            if str(statement).startswith("LOCK TABLE"):
                return ScalarResult(0)
            return ScalarResult(next(self.counts))

    applied: list[object] = []
    monkeypatch.setattr(migration, "_apply_upgrade", applied.append)

    assert migration.bootstrap_empty_install(BootstrapConnection([0, 0, 0])) is False
    assert applied == []
    owner_connection = BootstrapConnection([0, 0, 1])
    assert migration.bootstrap_empty_install(owner_connection) is True
    assert applied == [owner_connection]


def test_rollback_snapshot_advances_version_without_reusing_migration_marker() -> None:
    migration = _load_migration()
    source = {
        "cubeCatalog": {
            "profile": "wtchk_cls",
            "catalogVersion": 8,
            "fields": [],
            "metrics": [],
            "rollups": [{"name": "stale"}],
        },
        "charts": [{"slug": "old"}],
        migration._MIGRATION_MARKER: {"revision": migration.revision},
    }

    rollback = migration._rollback_snapshot(source, next_version=9)

    assert rollback["cubeCatalog"]["catalogVersion"] == 9
    assert rollback["cubeCatalog"]["rollups"] == []
    assert rollback["charts"] == [{"slug": "old"}]
    assert migration._MIGRATION_MARKER not in rollback


def test_downgrade_without_a_migration_marker_does_not_delete_stable_slugs(
    monkeypatch,
) -> None:
    migration = _load_migration()

    class EmptyResult:
        def mappings(self):
            return self

        def all(self):
            return []

    class RecordingConnection:
        def __init__(self):
            self.statements: list[str] = []

        def execute(self, statement, *args, **kwargs):
            self.statements.append(str(statement))
            return EmptyResult()

    connection = RecordingConnection()
    monkeypatch.setattr(migration.op, "get_bind", lambda: connection)

    migration.downgrade()

    assert not any("DELETE FROM analytics_charts" in sql for sql in connection.statements)
    assert not any("UPDATE analytics_charts" in sql for sql in connection.statements)


def test_upgrade_and_downgrade_round_trip_chart_and_catalog_data(monkeypatch) -> None:
    migration = _load_migration()
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
    sa.Table(
        "analytics_metrics",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("published_model_version_id", sa.Integer),
    )
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    metadata.create_all(engine)
    now = datetime(2026, 8, 27, 9, tzinfo=timezone.utc)
    original_snapshot = {
        "cubeCatalog": {
            "catalogVersion": 7,
            "fields": [{"slug": "topic_sentiment"}],
            "metrics": [{"slug": "response_count"}],
            "rollups": [{"metrics": ["response_count"]}],
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
                catalog_version=7,
                status="published",
                definition_hash="old",
                catalog_snapshot=original_snapshot,
                validation_errors=[],
                is_active=True,
                created_by_id="owner",
                created_at=now,
                published_at=now,
                activated_at=now,
                archived_at=None,
            )
            .returning(versions.c.id)
        ).scalar_one()
        legacy_definitions = [
            {
                "slug": "dashboard_sentiment_distribution",
                "status": "published",
                "definition": {"dimensions": [], "metrics": ["response_count"]},
                "archived_at": None,
            },
            {
                "slug": "custom_draft",
                "status": "draft",
                "definition": {"dimensions": ["store_format"], "metrics": []},
                "archived_at": now,
            },
        ]
        for item in legacy_definitions:
            connection.execute(
                charts.insert().values(
                    **item,
                    title=item["slug"],
                    description=None,
                    chart_type="table",
                    semantic_view="survey_responses",
                    visibility="viewer",
                    validation_errors=[],
                    created_by_id="owner",
                    published_model_version_id=active_id,
                    created_at=now,
                    updated_at=now,
                    validated_at=None,
                    published_at=None,
                )
            )

        monkeypatch.setattr(
            migration.op, "get_bind", lambda: SQLiteMigrationConnection(connection)
        )
        migration.upgrade()

        upgraded_charts = connection.execute(
            sa.select(charts).order_by(charts.c.id)
        ).mappings().all()
        legacy_rows = [
            row
            for row in upgraded_charts
            if migration._MIGRATION_MARKER in row["definition"]
        ]
        seeded_rows = [
            row
            for row in upgraded_charts
            if row["slug"] in {chart["slug"] for chart in migration._DEFAULT_CHARTS}
        ]
        assert len(legacy_rows) == 2
        assert all(row["status"] == "archived" for row in legacy_rows)
        assert {row["slug"] for row in legacy_rows} == {
            f"legacy_0012_{legacy_rows[0]['id']}",
            f"legacy_0012_{legacy_rows[1]['id']}",
        }
        assert len(seeded_rows) == 13
        assert all("metrics" not in row["definition"] for row in seeded_rows)

        active_version = connection.execute(
            sa.select(versions).where(versions.c.is_active.is_(True))
        ).mappings().one()
        assert active_version["id"] != active_id
        assert active_version["catalog_snapshot"]["cubeCatalog"]["rollups"] == []
        assert len(active_version["catalog_snapshot"]["charts"]) == 13

        migration.downgrade()

        restored_charts = connection.execute(
            sa.select(charts).order_by(charts.c.id)
        ).mappings().all()
        assert [row["slug"] for row in restored_charts] == [
            "dashboard_sentiment_distribution",
            "custom_draft",
        ]
        assert [row["status"] for row in restored_charts] == ["published", "draft"]
        assert all(
            migration._MIGRATION_MARKER not in row["definition"]
            for row in restored_charts
        )
        restored_active = connection.execute(
            sa.select(versions).where(versions.c.is_active.is_(True))
        ).mappings().one()
        assert restored_active["id"] != active_id
        assert restored_active["catalog_version"] > active_version["catalog_version"]
        assert restored_active["catalog_snapshot"]["charts"] == original_snapshot["charts"]
        assert restored_active["catalog_snapshot"]["cubeCatalog"] == {
            **original_snapshot["cubeCatalog"],
            "catalogVersion": restored_active["catalog_version"],
            "rollups": [],
        }
        assert connection.scalar(sa.select(sa.func.count()).select_from(versions)) == 3
