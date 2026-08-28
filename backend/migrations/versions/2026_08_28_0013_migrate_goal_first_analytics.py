"""replace raw-field analytics charts with goal-first metric targets

Revision ID: 0013_goal_first_analytics
Revises: 0012_single_metric_charts
Create Date: 2026-08-28 08:00:00.000000
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


revision: str = "0013_goal_first_analytics"
down_revision: Union[str, Sequence[str], None] = "0012_single_metric_charts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_MIGRATION_MARKER = "__migration_0013_goal_first_contract"
_LEGACY_SLUG_PREFIX = "legacy_0013_"


def _count_chart(
    slug: str,
    title: str,
    description: str,
    chart_type: str,
    semantic_view: str,
    dimensions: list[str],
    metric: str,
    **definition: Any,
) -> dict[str, Any]:
    return {
        "slug": slug,
        "title": title,
        "description": description,
        "chart_type": chart_type,
        "semantic_view": semantic_view,
        "definition": {
            "dimensions": dimensions,
            "metric": metric,
            "aggregation": "count",
            **definition,
        },
    }


_DEFAULT_CHARTS = (
    _count_chart(
        "dashboard_sentiment_distribution",
        "Sentiment distribution",
        "Daily survey counts grouped by canonical topic sentiment.",
        "line",
        "survey_responses",
        ["topic_sentiment"],
        "survey",
        time_dimension="reported_at",
        time_granularity="day",
        order=[{"member": "reported_at", "direction": "asc"}],
        limit=1000,
    ),
    _count_chart(
        "dashboard_store_distribution",
        "Sentiment by store",
        "Survey counts grouped by store and canonical topic sentiment.",
        "stacked_bar",
        "survey_responses",
        ["store_name_english", "topic_sentiment"],
        "survey",
        order=[{"member": "value", "direction": "desc"}],
        limit=1000,
    ),
    _count_chart(
        "dashboard_store_format_distribution",
        "Sentiment by store format",
        "Survey counts grouped by store format and canonical topic sentiment.",
        "stacked_bar",
        "survey_responses",
        ["store_format", "topic_sentiment"],
        "survey",
        filters=[{"member": "store_format", "operator": "set"}],
        order=[{"member": "value", "direction": "desc"}],
        limit=1000,
    ),
    _count_chart(
        "dashboard_channel_delivery_distribution",
        "Sentiment by channel and delivery service",
        "Survey counts by channel, delivery service, and sentiment.",
        "table",
        "survey_responses",
        ["channel_name", "delivery_service_name", "topic_sentiment"],
        "survey",
        order=[{"member": "value", "direction": "desc"}],
        limit=1000,
    ),
    _count_chart(
        "dashboard_topic_sentiment_counts",
        "Topic sentiment counts",
        "Survey counts grouped by canonical topic sentiment.",
        "bar",
        "survey_responses",
        ["topic_sentiment"],
        "survey",
        order=[{"member": "value", "direction": "desc"}],
        limit=10,
    ),
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
    _count_chart(
        "dashboard_topic_distribution",
        "Sentiment by topic",
        "Topic-assignment counts grouped by topic and assignment sentiment.",
        "stacked_bar",
        "survey_topics",
        ["topic", "sentiment"],
        "topic_assignment",
        order=[{"member": "value", "direction": "desc"}],
        limit=1000,
    ),
    _count_chart(
        "dashboard_department_distribution",
        "Sentiment by department",
        "Department-assignment counts grouped by department and assignment sentiment.",
        "stacked_bar",
        "survey_departments",
        ["department", "sentiment"],
        "department_assignment",
        order=[{"member": "value", "direction": "desc"}],
        limit=1000,
    ),
    _count_chart(
        "dashboard_keyword_analysis",
        "Sentiment by keyword",
        "Keyword-assignment counts grouped by keyword and assignment sentiment.",
        "stacked_bar",
        "survey_keywords",
        ["keyword", "sentiment"],
        "keyword_assignment",
        order=[{"member": "value", "direction": "desc"}],
        limit=10,
    ),
    *(
        {
            "slug": slug,
            "title": title,
            "description": description,
            "chart_type": "kpi",
            "semantic_view": "survey_responses",
            "definition": {
                "dimensions": [],
                "metric": metric,
                "aggregation": aggregation,
                "limit": 1,
            },
        }
        for slug, title, description, metric, aggregation in (
            (
                "dashboard_first_reported_at",
                "First reported date",
                "First non-deleted survey reported timestamp.",
                "reported_at",
                "min",
            ),
            (
                "dashboard_last_reported_at",
                "Last reported date",
                "Last non-deleted survey reported timestamp.",
                "reported_at",
                "max",
            ),
            (
                "dashboard_last_updated_at",
                "Last updated date",
                "Latest active survey update timestamp.",
                "updated_at",
                "max",
            ),
        )
    ),
)


def _json_object(value: Any, *, label: str) -> dict[str, Any]:
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, dict):
        raise RuntimeError(f"{label} must be a JSON object")
    return value


def _iso(value: str | datetime | None) -> str | None:
    if value is None or isinstance(value, str):
        return value
    return value.isoformat()


def _timestamp(value: str | datetime | None) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    return datetime.fromisoformat(value)


def _archive_definition(
    definition: dict[str, Any] | None,
    *,
    original_slug: str | None,
    original_status: str,
    original_archived_at: datetime | None,
) -> dict[str, Any]:
    archived = deepcopy(_json_object(definition or {}, label="Chart definition"))
    archived[_MIGRATION_MARKER] = {
        "revision": revision,
        "kind": "legacy",
        "original_slug": original_slug,
        "original_status": original_status,
        "original_archived_at": _iso(original_archived_at),
    }
    return archived


def _legacy_slug(chart_id: int) -> str:
    return f"{_LEGACY_SLUG_PREFIX}{chart_id}"


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


def _snapshot_chart(row: sa.RowMapping) -> dict[str, Any]:
    def utc(value: str | datetime | None) -> str | None:
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
        "validated_at": utc(row["validated_at"]),
        "published_at": utc(row["published_at"]),
        "archived_at": utc(row["archived_at"]),
        "created_at": utc(row["created_at"]),
        "updated_at": utc(row["updated_at"]),
    }


def _bootstrap_snapshot() -> dict[str, Any]:
    profile = os.environ.get("DEPLOYMENT_PROFILE", "").strip()
    if not profile:
        raise RuntimeError("DEPLOYMENT_PROFILE is required to bootstrap analytics")
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


def _validate_default_metric_targets(snapshot: dict[str, Any]) -> None:
    cube_catalog = snapshot.get("cubeCatalog", snapshot)
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
                str(item.get("queryTarget")),
                str(item.get("publicAggregation")),
            )
            for item in local_metrics
            if isinstance(item, dict)
            and (
                item.get("semanticView"),
                item.get("queryTarget"),
                item.get("publicAggregation"),
            )
            in default_pairs
        }
    )
    if conflicts:
        raise RuntimeError(
            "Default analytics charts conflict with local metric targets: "
            + ", ".join("/".join(pair) for pair in conflicts)
        )


def _replacement_snapshot(
    source: dict[str, Any],
    charts: list[dict[str, Any]],
    *,
    next_version: int,
    previous_active_id: int | None,
    seeded_chart_ids: list[int],
) -> dict[str, Any]:
    snapshot = deepcopy(source)
    cube_catalog = snapshot.get("cubeCatalog")
    cube_catalog = deepcopy(cube_catalog) if isinstance(cube_catalog, dict) else {}
    cube_catalog["catalogVersion"] = next_version
    cube_catalog["rollups"] = []
    snapshot["cubeCatalog"] = cube_catalog
    snapshot["charts"] = deepcopy(charts)
    snapshot[_MIGRATION_MARKER] = {
        "revision": revision,
        "kind": "goal_first",
        "previous_active_id": previous_active_id,
        "seeded_chart_ids": sorted(seeded_chart_ids),
    }
    return snapshot


def _next_version(bind: Any) -> int:
    return bind.execute(
        sa.text(
            "SELECT COALESCE(MAX(catalog_version), 0) + 1 "
            "FROM analytics_model_versions"
        )
    ).scalar_one()


def _insert_version(
    bind: Any,
    snapshot: dict[str, Any],
    user_id: str,
    now: datetime,
) -> int:
    definition_hash = hashlib.sha256(
        json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    version_table = _version_table()
    return bind.execute(
        version_table
        .insert()
        .values(
            catalog_version=snapshot["cubeCatalog"]["catalogVersion"],
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


def _apply_upgrade(bind: Any) -> None:
    bind.execute(sa.text("LOCK TABLE analytics_charts IN SHARE ROW EXCLUSIVE MODE"))
    now = datetime.now(timezone.utc)
    active = bind.execute(
        sa.text(
            "SELECT id, catalog_snapshot, created_by_id FROM analytics_model_versions "
            "WHERE is_active = true ORDER BY catalog_version DESC LIMIT 1"
        )
    ).mappings().first()
    base = active or bind.execute(
        sa.text(
            "SELECT id, catalog_snapshot, created_by_id FROM analytics_model_versions "
            "ORDER BY catalog_version DESC LIMIT 1"
        )
    ).mappings().first()
    user_id = base["created_by_id"] if base is not None else None
    if user_id is None:
        user_id = bind.execute(
            sa.text(
                "SELECT id FROM users WHERE COALESCE(is_deleted, false) = false "
                "ORDER BY CASE WHEN role = 'admin' THEN 0 ELSE 1 END, created_at, id LIMIT 1"
            )
        ).scalar()
    current = bind.execute(
        sa.text(
            "SELECT id, slug, status, definition, archived_at FROM analytics_charts "
            "WHERE archived_at IS NULL AND status <> 'archived' ORDER BY id"
        )
    ).mappings().all()
    if user_id is None:
        if current or active is not None:
            raise RuntimeError("Analytics rows exist without a usable owner")
        return

    chart_table = _chart_table()
    for row in current:
        bind.execute(
            chart_table.update()
            .where(chart_table.c.id == row["id"])
            .values(
                slug=_legacy_slug(row["id"]),
                definition=_archive_definition(
                    row["definition"],
                    original_slug=row["slug"],
                    original_status=row["status"],
                    original_archived_at=row["archived_at"],
                ),
                status="archived",
                archived_at=now,
                updated_at=now,
            )
        )

    seeded_ids: list[int] = []
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
        seeded_ids.append(chart_id)

    source_snapshot = (
        _json_object(base["catalog_snapshot"] or {}, label="Analytics catalog snapshot")
        if base is not None
        else _bootstrap_snapshot()
    )
    _validate_default_metric_targets(source_snapshot)
    rows = bind.execute(
        sa.text(
            "SELECT id, slug, title, description, chart_type, semantic_view, definition, "
            "visibility, status, validation_errors, published_model_version_id, validated_at, "
            "published_at, archived_at, created_at, updated_at FROM analytics_charts "
            "WHERE id IN :ids ORDER BY slug"
        ).bindparams(sa.bindparam("ids", expanding=True)),
        {"ids": seeded_ids},
    ).mappings().all()
    next_version = _next_version(bind)
    snapshot = _replacement_snapshot(
        source_snapshot,
        [_snapshot_chart(row) for row in rows],
        next_version=next_version,
        previous_active_id=active["id"] if active is not None else None,
        seeded_chart_ids=seeded_ids,
    )
    bind.execute(
        sa.text(
            "UPDATE analytics_model_versions SET is_active = false, status = 'superseded', "
            "archived_at = :now WHERE is_active = true"
        ),
        {"now": now},
    )
    version_id = _insert_version(bind, snapshot, user_id, now)
    bind.execute(
        sa.text("SELECT setval('analytics_catalog_version_seq', :version, true)"),
        {"version": next_version},
    )
    bind.execute(
        chart_table.update()
        .where(chart_table.c.id.in_(seeded_ids))
        .values(published_model_version_id=version_id)
    )


def bootstrap_empty_install(bind: Any) -> bool:
    bind.execute(sa.text("LOCK TABLE analytics_charts IN SHARE ROW EXCLUSIVE MODE"))
    if bind.execute(sa.text("SELECT COUNT(*) FROM analytics_model_versions")).scalar_one():
        return False
    if bind.execute(sa.text("SELECT COUNT(*) FROM analytics_charts")).scalar_one():
        return False
    if not bind.execute(
        sa.text(
            "SELECT COUNT(*) FROM users WHERE COALESCE(is_deleted, false) = false"
        )
    ).scalar_one():
        return False
    _apply_upgrade(bind)
    return True


def upgrade() -> None:
    _apply_upgrade(op.get_bind())


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text("LOCK TABLE analytics_charts IN SHARE ROW EXCLUSIVE MODE"))
    versions = bind.execute(
        sa.text(
            "SELECT id, catalog_snapshot, created_by_id FROM analytics_model_versions "
            "ORDER BY catalog_version DESC"
        )
    ).mappings().all()
    migration_version = None
    marker = None
    for row in versions:
        snapshot = _json_object(row["catalog_snapshot"] or {}, label="Catalog snapshot")
        candidate = snapshot.get(_MIGRATION_MARKER)
        if isinstance(candidate, dict) and candidate.get("revision") == revision:
            migration_version = row
            marker = candidate
            break
    if migration_version is None or marker is None:
        return

    chart_table = _chart_table()
    seeded_ids = list(marker.get("seeded_chart_ids") or [])
    if seeded_ids:
        bind.execute(chart_table.delete().where(chart_table.c.id.in_(seeded_ids)))

    rows = bind.execute(
        sa.text("SELECT id, slug, definition FROM analytics_charts ORDER BY id")
    ).mappings().all()
    legacy: list[tuple[Any, dict[str, Any]]] = []
    occupied = {row["slug"] for row in rows if row["slug"] is not None}
    for row in rows:
        definition = _json_object(row["definition"] or {}, label="Chart definition")
        state = definition.get(_MIGRATION_MARKER)
        if not isinstance(state, dict) or state.get("revision") != revision:
            continue
        original_slug = state.get("original_slug")
        if original_slug in occupied and original_slug != row["slug"]:
            raise RuntimeError(f"Cannot restore chart slug {original_slug}")
        restored = deepcopy(definition)
        restored.pop(_MIGRATION_MARKER, None)
        legacy.append((row, {**state, "definition": restored}))
    for row, state in legacy:
        bind.execute(
            chart_table.update()
            .where(chart_table.c.id == row["id"])
            .values(
                slug=state.get("original_slug"),
                status=state["original_status"],
                definition=state["definition"],
                archived_at=_timestamp(state.get("original_archived_at")),
            )
        )

    previous_id = marker.get("previous_active_id")
    previous = next((row for row in versions if row["id"] == previous_id), None)
    source = _json_object(
        (previous or migration_version)["catalog_snapshot"] or {},
        label="Rollback catalog snapshot",
    )
    rollback = deepcopy(source)
    rollback.pop(_MIGRATION_MARKER, None)
    next_version = _next_version(bind)
    cube_catalog = rollback.get("cubeCatalog")
    cube_catalog = deepcopy(cube_catalog) if isinstance(cube_catalog, dict) else {}
    cube_catalog["catalogVersion"] = next_version
    cube_catalog["rollups"] = []
    rollback["cubeCatalog"] = cube_catalog
    now = datetime.now(timezone.utc)
    bind.execute(
        sa.text(
            "UPDATE analytics_model_versions SET is_active = false, status = 'superseded', "
            "archived_at = :now WHERE is_active = true"
        ),
        {"now": now},
    )
    rollback_id = _insert_version(
        bind, rollback, (previous or migration_version)["created_by_id"], now
    )
    bind.execute(
        sa.text("SELECT setval('analytics_catalog_version_seq', :version, true)"),
        {"version": next_version},
    )
    bind.execute(
        chart_table.update()
        .where(chart_table.c.published_model_version_id == migration_version["id"])
        .values(published_model_version_id=rollback_id)
    )
