"""replace legacy analytics charts with the single-metric contract

Revision ID: 0012_single_metric_charts
Revises: 0011_default_analytics_charts
Create Date: 2026-08-28 00:00:00.000000
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from typing import Any, Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0012_single_metric_charts"
down_revision: Union[str, Sequence[str], None] = "0011_default_analytics_charts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_MIGRATION_MARKER = "__migration_0012_single_metric_contract"
_LEGACY_SLUG_PREFIX = "legacy_0012_"


_DEFAULT_CHARTS = (
    {
        "slug": "dashboard_sentiment_distribution",
        "title": "Sentiment distribution",
        "description": "Daily response counts grouped by canonical topic sentiment.",
        "chart_type": "line",
        "semantic_view": "survey_responses",
        "definition": {
            "dimensions": ["topic_sentiment"],
            "metric": "id",
            "aggregation": "count",
            "time_dimension": "reported_at",
            "time_granularity": "day",
            "order": [{"member": "reported_at", "direction": "asc"}],
            "limit": 1000,
        },
    },
    {
        "slug": "dashboard_store_distribution",
        "title": "Sentiment by store",
        "description": "Response counts grouped by store and canonical topic sentiment.",
        "chart_type": "stacked_bar",
        "semantic_view": "survey_responses",
        "definition": {
            "dimensions": ["store_name_english", "topic_sentiment"],
            "metric": "id",
            "aggregation": "count",
            "order": [{"member": "value", "direction": "desc"}],
            "limit": 1000,
        },
    },
    {
        "slug": "dashboard_store_format_distribution",
        "title": "Sentiment by store format",
        "description": "Response counts grouped by store format and canonical topic sentiment.",
        "chart_type": "stacked_bar",
        "semantic_view": "survey_responses",
        "definition": {
            "dimensions": ["store_format", "topic_sentiment"],
            "metric": "id",
            "aggregation": "count",
            "filters": [{"member": "store_format", "operator": "set"}],
            "order": [{"member": "value", "direction": "desc"}],
            "limit": 1000,
        },
    },
    {
        "slug": "dashboard_channel_delivery_distribution",
        "title": "Sentiment by channel and delivery service",
        "description": "Response counts by channel, delivery service, and sentiment.",
        "chart_type": "table",
        "semantic_view": "survey_responses",
        "definition": {
            "dimensions": [
                "channel_name",
                "delivery_service_name",
                "topic_sentiment",
            ],
            "metric": "id",
            "aggregation": "count",
            "order": [{"member": "value", "direction": "desc"}],
            "limit": 1000,
        },
    },
    {
        "slug": "dashboard_topic_sentiment_counts",
        "title": "Topic sentiment counts",
        "description": "Response counts grouped by canonical topic sentiment.",
        "chart_type": "bar",
        "semantic_view": "survey_responses",
        "definition": {
            "dimensions": ["topic_sentiment"],
            "metric": "id",
            "aggregation": "count",
            "order": [{"member": "value", "direction": "desc"}],
            "limit": 10,
        },
    },
    {
        "slug": "dashboard_overall_topic_sentiment_score",
        "title": "Overall topic sentiment score",
        "description": "Average response-level topic sentiment score.",
        "chart_type": "kpi",
        "semantic_view": "survey_responses",
        "definition": {
            "dimensions": [],
            "metric": "topic_sentiment_score",
            "aggregation": "average",
            "limit": 1,
        },
    },
    {
        "slug": "dashboard_mixed_topic_sentiment_score",
        "title": "Mixed topic sentiment score",
        "description": "Average topic sentiment score for mixed responses.",
        "chart_type": "kpi",
        "semantic_view": "survey_responses",
        "definition": {
            "dimensions": [],
            "metric": "topic_sentiment_score",
            "aggregation": "average",
            "filters": [
                {"member": "topic_sentiment", "operator": "equals", "value": "MIXED"}
            ],
            "limit": 1,
        },
    },
    {
        "slug": "dashboard_topic_distribution",
        "title": "Sentiment by topic",
        "description": "Assignment counts grouped by topic and assignment sentiment.",
        "chart_type": "stacked_bar",
        "semantic_view": "survey_topics",
        "definition": {
            "dimensions": ["topic", "sentiment"],
            "metric": "assignment_id",
            "aggregation": "count",
            "order": [{"member": "value", "direction": "desc"}],
            "limit": 1000,
        },
    },
    {
        "slug": "dashboard_department_distribution",
        "title": "Sentiment by department",
        "description": "Assignment counts grouped by department and assignment sentiment.",
        "chart_type": "stacked_bar",
        "semantic_view": "survey_departments",
        "definition": {
            "dimensions": ["department", "sentiment"],
            "metric": "assignment_id",
            "aggregation": "count",
            "order": [{"member": "value", "direction": "desc"}],
            "limit": 1000,
        },
    },
    {
        "slug": "dashboard_keyword_analysis",
        "title": "Sentiment by keyword",
        "description": "Assignment counts grouped by keyword and assignment sentiment.",
        "chart_type": "stacked_bar",
        "semantic_view": "survey_keywords",
        "definition": {
            "dimensions": ["keyword", "sentiment"],
            "metric": "assignment_id",
            "aggregation": "count",
            "order": [{"member": "value", "direction": "desc"}],
            "limit": 10,
        },
    },
    {
        "slug": "dashboard_first_reported_at",
        "title": "First reported date",
        "description": "First non-deleted response reported timestamp.",
        "chart_type": "kpi",
        "semantic_view": "survey_responses",
        "definition": {
            "dimensions": [],
            "metric": "reported_at",
            "aggregation": "min",
            "limit": 1,
        },
    },
    {
        "slug": "dashboard_last_reported_at",
        "title": "Last reported date",
        "description": "Last non-deleted response reported timestamp.",
        "chart_type": "kpi",
        "semantic_view": "survey_responses",
        "definition": {
            "dimensions": [],
            "metric": "reported_at",
            "aggregation": "max",
            "limit": 1,
        },
    },
    {
        "slug": "dashboard_last_updated_at",
        "title": "Last updated date",
        "description": "Latest active survey update timestamp.",
        "chart_type": "kpi",
        "semantic_view": "survey_responses",
        "definition": {
            "dimensions": [],
            "metric": "updated_at",
            "aggregation": "max",
            "limit": 1,
        },
    },
)


def _iso(value: str | datetime | None) -> str | None:
    if value is None or isinstance(value, str):
        return value
    return value.isoformat()


def _timestamp(value: str | datetime | None) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    return datetime.fromisoformat(value)


def _legacy_slug(chart_id: int) -> str:
    return f"{_LEGACY_SLUG_PREFIX}{chart_id}"


def _json_object(value: Any, *, label: str) -> dict[str, Any]:
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, dict):
        raise RuntimeError(f"{label} must be a JSON object")
    return value


def _archive_definition(
    definition: dict[str, Any] | None,
    *,
    original_slug: str | None,
    original_status: str,
    original_archived_at: datetime | None,
) -> dict[str, Any]:
    archived = deepcopy(_json_object(definition or {}, label="Chart definition"))
    had_previous_marker = _MIGRATION_MARKER in archived
    previous_marker = archived.get(_MIGRATION_MARKER)
    archived[_MIGRATION_MARKER] = {
        "revision": revision,
        "kind": "legacy",
        "original_slug": original_slug,
        "original_status": original_status,
        "original_archived_at": _iso(original_archived_at),
        "had_previous_marker": had_previous_marker,
        "previous_marker": previous_marker,
    }
    return archived


def _restore_definition(
    definition: dict[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    restored = deepcopy(_json_object(definition or {}, label="Chart definition"))
    marker = restored.pop(_MIGRATION_MARKER, None)
    if not isinstance(marker, dict) or marker.get("revision") != revision:
        raise RuntimeError("Chart is missing the 0012 legacy migration marker")
    if marker.get("kind") != "legacy":
        raise RuntimeError("Chart has an invalid 0012 legacy migration marker")
    if marker.get("had_previous_marker"):
        restored[_MIGRATION_MARKER] = marker.get("previous_marker")
    return restored, {
        "original_slug": marker.get("original_slug"),
        "original_status": marker["original_status"],
        "original_archived_at": _timestamp(marker.get("original_archived_at")),
    }


def _replacement_snapshot(
    active_snapshot: dict[str, Any],
    replacement_charts: list[dict[str, Any]],
    *,
    next_version: int,
    previous_active_id: int | None,
    previous_active_status: str | None,
    previous_active_archived_at: datetime | None,
    seeded_chart_ids: list[int],
) -> dict[str, Any]:
    snapshot = deepcopy(active_snapshot)
    cube_catalog = snapshot.get("cubeCatalog")
    cube_catalog = deepcopy(cube_catalog) if isinstance(cube_catalog, dict) else {}
    cube_catalog["catalogVersion"] = next_version
    # Rollups contain metric member names from chart definitions. Every legacy
    # chart used the removed metrics[] contract, so none may cross this boundary.
    cube_catalog["rollups"] = []
    snapshot["cubeCatalog"] = cube_catalog
    snapshot["charts"] = deepcopy(replacement_charts)
    snapshot[_MIGRATION_MARKER] = {
        "revision": revision,
        "kind": "catalog_v2",
        "previous_active_id": previous_active_id,
        "previous_active_status": previous_active_status,
        "previous_active_archived_at": _iso(previous_active_archived_at),
        "seeded_chart_ids": sorted(seeded_chart_ids),
    }
    return snapshot


def _bootstrap_snapshot() -> dict[str, Any]:
    profile = os.environ.get("DEPLOYMENT_PROFILE", "").strip()
    if not profile:
        raise RuntimeError(
            "DEPLOYMENT_PROFILE is required to create the first analytics catalog"
        )
    return {
        "cubeCatalog": {
            "profile": profile,
            "catalogVersion": 0,
            "fields": [],
            "metrics": [],
            "rollups": [],
        },
        "charts": [],
    }


def _validate_default_metric_pairs(snapshot: dict[str, Any]) -> None:
    """Fail closed when any local measure shadows a default core pair.

    Viewer charts are also executable by administrators.  An admin-only local
    measure therefore cannot share their public ``(field, aggregation)`` pair:
    it would make the otherwise valid chart ambiguous only for administrators.
    """

    cube_catalog = snapshot.get("cubeCatalog")
    if cube_catalog is None:
        cube_catalog = snapshot
    if not isinstance(cube_catalog, dict):
        raise RuntimeError("Analytics Cube catalog must be a JSON object")
    local_metrics = cube_catalog.get("metrics", [])
    if not isinstance(local_metrics, list):
        raise RuntimeError("Analytics Cube metrics must be a JSON array")
    default_pairs = {
        (
            chart["semantic_view"],
            chart["definition"]["metric"],
            chart["definition"]["aggregation"],
        )
        for chart in _DEFAULT_CHARTS
    }
    conflicts = sorted(
        {
            (
                str(item.get("semanticView")),
                str(item.get("sourceField")),
                str(item.get("operation")),
            )
            for item in local_metrics
            if isinstance(item, dict)
            and item.get("visibility") in {"viewer", "admin"}
            and (
                item.get("semanticView"),
                item.get("sourceField"),
                item.get("operation"),
            )
            in default_pairs
        }
    )
    if conflicts:
        rendered = ", ".join("/".join(pair) for pair in conflicts)
        raise RuntimeError(
            "Default analytics charts conflict with local metrics: " + rendered
        )


def _rollback_snapshot(
    source_snapshot: dict[str, Any],
    *,
    next_version: int,
    fallback_charts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    snapshot = deepcopy(source_snapshot)
    snapshot.pop(_MIGRATION_MARKER, None)
    if fallback_charts is not None:
        snapshot["charts"] = deepcopy(fallback_charts)
    cube_catalog = snapshot.get("cubeCatalog")
    cube_catalog = deepcopy(cube_catalog) if isinstance(cube_catalog, dict) else {}
    cube_catalog["catalogVersion"] = next_version
    cube_catalog["rollups"] = []
    snapshot["cubeCatalog"] = cube_catalog
    return snapshot


def _snapshot_chart(row: sa.RowMapping) -> dict[str, Any]:
    def iso(value: str | datetime | None) -> str | None:
        parsed = _timestamp(value)
        return parsed.astimezone(timezone.utc).isoformat() if parsed else None

    return {
        "id": row["id"],
        "slug": row["slug"],
        "title": row["title"],
        "description": row["description"],
        "chart_type": row["chart_type"],
        "semantic_view": row["semantic_view"],
        "definition": row["definition"] or {},
        "visibility": row["visibility"],
        "status": row["status"],
        "validation_errors": row["validation_errors"] or [],
        "published_model_version_id": row["published_model_version_id"],
        "validated_at": iso(row["validated_at"]),
        "published_at": iso(row["published_at"]),
        "archived_at": iso(row["archived_at"]),
        "created_at": iso(row["created_at"]),
        "updated_at": iso(row["updated_at"]),
    }


def _chart_table() -> sa.TableClause:
    return sa.table(
        "analytics_charts",
        sa.column("id", sa.Integer()),
        sa.column("slug", sa.String(length=64)),
        sa.column("title", sa.String(length=160)),
        sa.column("description", sa.Text()),
        sa.column("chart_type", sa.String(length=16)),
        sa.column("semantic_view", sa.String(length=32)),
        sa.column("definition", sa.JSON()),
        sa.column("visibility", sa.String(length=16)),
        sa.column("status", sa.String(length=16)),
        sa.column("validation_errors", sa.JSON()),
        sa.column("created_by_id", sa.CHAR(length=36)),
        sa.column("published_model_version_id", sa.Integer()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
        sa.column("validated_at", sa.DateTime(timezone=True)),
        sa.column("published_at", sa.DateTime(timezone=True)),
        sa.column("archived_at", sa.DateTime(timezone=True)),
    )


def _version_table() -> sa.TableClause:
    return sa.table(
        "analytics_model_versions",
        sa.column("id", sa.Integer()),
        sa.column("catalog_version", sa.BigInteger()),
        sa.column("status", sa.String(length=16)),
        sa.column("definition_hash", sa.String(length=64)),
        sa.column("catalog_snapshot", sa.JSON()),
        sa.column("validation_errors", sa.JSON()),
        sa.column("is_active", sa.Boolean()),
        sa.column("created_by_id", sa.CHAR(length=36)),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("published_at", sa.DateTime(timezone=True)),
        sa.column("activated_at", sa.DateTime(timezone=True)),
        sa.column("archived_at", sa.DateTime(timezone=True)),
    )


def _apply_upgrade(bind: Any) -> None:
    # Prevent chart writes between the all-row archive and replacement inserts.
    # SELECTs remain available while this short metadata migration runs.
    bind.execute(sa.text("LOCK TABLE analytics_charts IN SHARE ROW EXCLUSIVE MODE"))
    now = datetime.now(timezone.utc)
    legacy_rows = bind.execute(
        sa.text(
            """
            SELECT id, slug, status, definition, archived_at
            FROM analytics_charts
            ORDER BY id
            """
        )
    ).mappings().all()
    active = bind.execute(
        sa.text(
            """
            SELECT id, status, catalog_snapshot, created_by_id, archived_at
            FROM analytics_model_versions
            WHERE is_active = true
            ORDER BY catalog_version DESC
            LIMIT 1
            """
        )
    ).mappings().first()
    base_version = active
    if base_version is None:
        base_version = bind.execute(
            sa.text(
                """
                SELECT id, status, catalog_snapshot, created_by_id, archived_at
                FROM analytics_model_versions
                ORDER BY catalog_version DESC
                LIMIT 1
                """
            )
        ).mappings().first()
    user_id = base_version["created_by_id"] if base_version is not None else None
    if user_id is None:
        user_id = bind.execute(
            sa.text(
                """
                SELECT id
                FROM users
                WHERE COALESCE(is_deleted, false) = false
                ORDER BY CASE WHEN role = 'admin' THEN 0 ELSE 1 END, created_at, id
                LIMIT 1
                """
            )
        ).scalar()
    if user_id is None:
        # Foreign keys make charts/catalog versions impossible without a user.
        # On an empty install the application bootstrap will publish defaults.
        if legacy_rows or active is not None:
            raise RuntimeError("Analytics rows exist without a usable owner")
        return

    chart_table = _chart_table()
    for row in legacy_rows:
        bind.execute(
            chart_table.update()
            .where(chart_table.c.id == row["id"])
            .values(
                definition=_archive_definition(
                    row["definition"],
                    original_slug=row["slug"],
                    original_status=row["status"],
                    original_archived_at=row["archived_at"],
                ),
                status="archived",
                archived_at=now,
            )
        )
    if legacy_rows:
        # Clear all old unique values first, then assign deterministic archival
        # slugs. This also handles an old slug that already looks like ours.
        bind.execute(sa.text("UPDATE analytics_charts SET slug = NULL"))
        for row in legacy_rows:
            bind.execute(
                chart_table.update()
                .where(chart_table.c.id == row["id"])
                .values(slug=_legacy_slug(row["id"]))
            )

    seeded_chart_ids: list[int] = []
    for chart in _DEFAULT_CHARTS:
        chart_id = bind.execute(
            chart_table.insert()
            .values(
                **chart,
                visibility="viewer",
                status="published",
                validation_errors=[],
                created_by_id=user_id,
                published_model_version_id=None,
                created_at=now,
                updated_at=now,
                validated_at=now,
                published_at=now,
                archived_at=None,
            )
            .returning(chart_table.c.id)
        ).scalar_one()
        seeded_chart_ids.append(chart_id)

    active_snapshot = (
        _json_object(
            base_version["catalog_snapshot"] or {},
            label="Analytics catalog snapshot",
        )
        if base_version is not None
        else _bootstrap_snapshot()
    )
    _validate_default_metric_pairs(active_snapshot)

    replacement_rows = bind.execute(
        sa.text(
            """
            SELECT id, slug, title, description, chart_type, semantic_view,
                   definition, visibility, status, validation_errors,
                   published_model_version_id, validated_at, published_at,
                   archived_at, created_at, updated_at
            FROM analytics_charts
            WHERE id IN ("""
            + ", ".join(
                f":chart_id_{index}" for index in range(len(seeded_chart_ids))
            )
            + ") ORDER BY slug"
        ),
        {
            f"chart_id_{index}": chart_id
            for index, chart_id in enumerate(seeded_chart_ids)
        },
    ).mappings().all()
    next_version = bind.execute(
        sa.text(
            "SELECT COALESCE(MAX(catalog_version), 0) + 1 "
            "FROM analytics_model_versions"
        )
    ).scalar_one()
    snapshot = _replacement_snapshot(
        active_snapshot,
        [_snapshot_chart(row) for row in replacement_rows],
        next_version=next_version,
        previous_active_id=active["id"] if active is not None else None,
        previous_active_status=active["status"] if active is not None else None,
        previous_active_archived_at=(
            active["archived_at"] if active is not None else None
        ),
        seeded_chart_ids=seeded_chart_ids,
    )
    definition_hash = hashlib.sha256(
        json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()

    if active is not None:
        bind.execute(
            sa.text(
                """
                UPDATE analytics_model_versions
                SET is_active = false, status = 'superseded', archived_at = :now
                WHERE id = :active_id
                """
            ),
            {"now": now, "active_id": active["id"]},
        )
    version_table = _version_table()
    version_id = bind.execute(
        version_table.insert()
        .values(
            catalog_version=next_version,
            status="published",
            definition_hash=definition_hash,
            catalog_snapshot=snapshot,
            validation_errors=[],
            is_active=True,
            created_by_id=user_id,
            created_at=now,
            published_at=now,
            activated_at=now,
            archived_at=None,
        )
        .returning(version_table.c.id)
    ).scalar_one()
    bind.execute(
        sa.text("SELECT setval('analytics_catalog_version_seq', :version, true)"),
        {"version": next_version},
    )
    bind.execute(
        chart_table.update()
        .where(chart_table.c.id.in_(seeded_chart_ids))
        .values(published_model_version_id=version_id)
    )


def bootstrap_empty_install(bind: Any) -> bool:
    """Finish the no-user migration path after the first user is bootstrapped.

    This is deliberately limited to a completely empty analytics catalog.  It
    must never infer ownership of or rewrite data created after the migration.
    """

    bind.execute(sa.text("LOCK TABLE analytics_charts IN SHARE ROW EXCLUSIVE MODE"))
    version_count = bind.execute(
        sa.text("SELECT COUNT(*) FROM analytics_model_versions")
    ).scalar_one()
    chart_count = bind.execute(
        sa.text("SELECT COUNT(*) FROM analytics_charts")
    ).scalar_one()
    if version_count or chart_count:
        return False
    owner_count = bind.execute(
        sa.text(
            "SELECT COUNT(*) FROM users "
            "WHERE COALESCE(is_deleted, false) = false"
        )
    ).scalar_one()
    if not owner_count:
        return False
    _apply_upgrade(bind)
    return True


def upgrade() -> None:
    _apply_upgrade(op.get_bind())


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text("LOCK TABLE analytics_charts IN SHARE ROW EXCLUSIVE MODE"))
    version_rows = bind.execute(
        sa.text(
            """
            SELECT id, catalog_version, catalog_snapshot, created_by_id
            FROM analytics_model_versions
            ORDER BY catalog_version DESC
            """
        )
    ).mappings().all()
    migration_version = None
    migration_state: dict[str, Any] | None = None
    for row in version_rows:
        snapshot = _json_object(
            row["catalog_snapshot"] or {}, label="Analytics catalog snapshot"
        )
        marker = snapshot.get(_MIGRATION_MARKER)
        if (
            isinstance(marker, dict)
            and marker.get("revision") == revision
            and marker.get("kind") == "catalog_v2"
        ):
            migration_version = row
            migration_state = marker
            break

    # An empty-install upgrade without a usable owner makes no changes and
    # creates no marker. Do not infer ownership from stable slugs: charts with
    # those names may have been created legitimately after that no-op upgrade.
    if migration_version is None or migration_state is None:
        return

    seeded_chart_ids = list(migration_state.get("seeded_chart_ids") or [])
    chart_table = _chart_table()
    if seeded_chart_ids:
        bind.execute(
            chart_table.delete().where(chart_table.c.id.in_(seeded_chart_ids))
        )
    else:
        # Empty-install upgrades do not create a catalog snapshot. Since every
        # pre-existing slug was moved away first, these stable slugs identify
        # only replacement rows created by this revision.
        slugs = [chart["slug"] for chart in _DEFAULT_CHARTS]
        bind.execute(chart_table.delete().where(chart_table.c.slug.in_(slugs)))

    all_chart_rows = bind.execute(
        sa.text("SELECT id, slug, definition FROM analytics_charts ORDER BY id")
    ).mappings().all()
    legacy: list[tuple[sa.RowMapping, dict[str, Any], dict[str, Any]]] = []
    occupied_slugs: set[str] = set()
    for row in all_chart_rows:
        definition = _json_object(
            row["definition"] or {}, label="Chart definition"
        )
        marker = definition.get(_MIGRATION_MARKER)
        if (
            isinstance(marker, dict)
            and marker.get("revision") == revision
            and marker.get("kind") == "legacy"
        ):
            restored, state = _restore_definition(definition)
            legacy.append((row, restored, state))
        elif row["slug"] is not None:
            occupied_slugs.add(row["slug"])

    conflicts = sorted(
        {
            state["original_slug"]
            for _, _, state in legacy
            if state["original_slug"] is not None
            and state["original_slug"] in occupied_slugs
        }
    )
    if conflicts:
        raise RuntimeError(
            "Cannot restore pre-0012 chart slugs because newer charts use: "
            + ", ".join(conflicts)
        )
    if legacy:
        bind.execute(
            chart_table.update()
            .where(chart_table.c.id.in_([row["id"] for row, _, _ in legacy]))
            .values(slug=None)
        )
        for row, restored, state in legacy:
            bind.execute(
                chart_table.update()
                .where(chart_table.c.id == row["id"])
                .values(
                    slug=state["original_slug"],
                    status=state["original_status"],
                    definition=restored,
                    archived_at=state["original_archived_at"],
                )
            )

    previous_active_id = migration_state.get("previous_active_id")
    previous = None
    if previous_active_id is not None:
        previous = bind.execute(
            sa.text(
                """
                SELECT id, catalog_snapshot, created_by_id
                FROM analytics_model_versions
                WHERE id = :id
                """
            ),
            {"id": previous_active_id},
        ).mappings().first()
    fallback_charts = None
    if previous is not None:
        source_snapshot = _json_object(
            previous["catalog_snapshot"] or {},
            label="Previous analytics catalog snapshot",
        )
        created_by_id = previous["created_by_id"]
    else:
        source_snapshot = _json_object(
            migration_version["catalog_snapshot"] or {},
            label="Migration analytics catalog snapshot",
        )
        restored_rows = bind.execute(
            sa.text(
                """
                SELECT id, slug, title, description, chart_type, semantic_view,
                       definition, visibility, status, validation_errors,
                       published_model_version_id, validated_at, published_at,
                       archived_at, created_at, updated_at
                FROM analytics_charts
                WHERE status = 'published' AND archived_at IS NULL
                ORDER BY slug
                """
            )
        ).mappings().all()
        fallback_charts = [_snapshot_chart(row) for row in restored_rows]
        created_by_id = migration_version["created_by_id"]
    next_version = bind.execute(
        sa.text(
            "SELECT COALESCE(MAX(catalog_version), 0) + 1 "
            "FROM analytics_model_versions"
        )
    ).scalar_one()
    rollback_snapshot = _rollback_snapshot(
        source_snapshot,
        next_version=next_version,
        fallback_charts=fallback_charts,
    )
    definition_hash = hashlib.sha256(
        json.dumps(
            rollback_snapshot, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()
    now = datetime.now(timezone.utc)
    bind.execute(
        sa.text(
            """
            UPDATE analytics_model_versions
            SET is_active = false, status = 'superseded', archived_at = :now
            WHERE is_active = true
            """
        ),
        {"now": now},
    )
    version_table = _version_table()
    rollback_version_id = bind.execute(
        version_table.insert()
        .values(
            catalog_version=next_version,
            status="published",
            definition_hash=definition_hash,
            catalog_snapshot=rollback_snapshot,
            validation_errors=[],
            is_active=True,
            created_by_id=created_by_id,
            created_at=now,
            published_at=now,
            activated_at=now,
            archived_at=None,
        )
        .returning(version_table.c.id)
    ).scalar_one()
    bind.execute(
        sa.text("SELECT setval('analytics_catalog_version_seq', :version, true)"),
        {"version": next_version},
    )
    linked_version_ids = [migration_version["id"]]
    if previous_active_id is not None:
        linked_version_ids.append(previous_active_id)
    bind.execute(
        chart_table.update()
        .where(chart_table.c.published_model_version_id.in_(linked_version_ids))
        .values(published_model_version_id=rollback_version_id)
    )
    bind.execute(
        sa.text(
            """
            UPDATE analytics_metrics
            SET published_model_version_id = :rollback_version_id
            WHERE published_model_version_id IN :linked_version_ids
            """
        ).bindparams(sa.bindparam("linked_version_ids", expanding=True)),
        {
            "rollback_version_id": rollback_version_id,
            "linked_version_ids": linked_version_ids,
        },
    )
