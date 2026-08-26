"""seed governed charts for the legacy dashboard replacements

Revision ID: 0011_default_analytics_charts
Revises: 0010_remove_legacy_history
Create Date: 2026-08-26 00:00:00.000000
"""

from datetime import datetime, timezone
import hashlib
import json
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0011_default_analytics_charts"
down_revision: Union[str, Sequence[str], None] = "0010_remove_legacy_history"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_DEFAULT_CHARTS = (
    {
        "slug": "dashboard_sentiment_distribution",
        "title": "Sentiment distribution",
        "description": "Daily response-level sentiment counts and average score.",
        "chart_type": "line",
        "semantic_view": "survey_responses",
        "definition": {
            "dimensions": [],
            "metrics": [
                "topic_sentiment_positive_count",
                "topic_sentiment_negative_count",
                "topic_sentiment_neutral_count",
                "topic_sentiment_mixed_count",
                "topic_sentiment_score_average",
            ],
            "time_dimension": "reported_at",
            "time_granularity": "day",
            "order": [{"member": "reported_at", "direction": "asc"}],
            "limit": 1000,
        },
    },
    {
        "slug": "dashboard_store_distribution",
        "title": "Sentiment by store",
        "description": "Response-level sentiment distribution grouped by store.",
        "chart_type": "bar",
        "semantic_view": "survey_responses",
        "definition": {
            "dimensions": ["store_key", "store_name_english"],
            "metrics": [
                "topic_sentiment_positive_count",
                "topic_sentiment_negative_count",
                "topic_sentiment_neutral_count",
                "topic_sentiment_mixed_count",
                "topic_sentiment_score_average",
            ],
            "order": [{"member": "topic_sentiment_negative_count", "direction": "desc"}],
            "limit": 1000,
        },
    },
    {
        "slug": "dashboard_store_format_distribution",
        "title": "Sentiment by store format",
        "description": "Default graph for the store-column dashboard using store format.",
        "chart_type": "bar",
        "semantic_view": "survey_responses",
        "definition": {
            "dimensions": ["store_format"],
            "metrics": [
                "topic_sentiment_positive_count",
                "topic_sentiment_negative_count",
                "topic_sentiment_neutral_count",
                "topic_sentiment_mixed_count",
                "topic_sentiment_score_average",
            ],
            "filters": [{"member": "store_format", "operator": "set"}],
            "order": [{"member": "topic_sentiment_negative_count", "direction": "desc"}],
            "limit": 1000,
        },
    },
    {
        "slug": "dashboard_channel_delivery_distribution",
        "title": "Sentiment by channel and delivery service",
        "description": "Response-level sentiment distribution by channel and delivery service.",
        "chart_type": "bar",
        "semantic_view": "survey_responses",
        "definition": {
            "dimensions": ["channel_name", "delivery_service_name"],
            "metrics": [
                "topic_sentiment_positive_count",
                "topic_sentiment_negative_count",
                "topic_sentiment_neutral_count",
                "topic_sentiment_mixed_count",
                "topic_sentiment_score_average",
            ],
            "order": [{"member": "topic_sentiment_negative_count", "direction": "desc"}],
            "limit": 1000,
        },
    },
    {
        "slug": "dashboard_topic_sentiment_counts",
        "title": "Topic sentiment counts",
        "description": "Response counts by canonical topic sentiment.",
        "chart_type": "bar",
        "semantic_view": "survey_responses",
        "definition": {
            "dimensions": ["topic_sentiment"],
            "metrics": ["response_count"],
            "order": [{"member": "response_count", "direction": "desc"}],
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
            "metrics": ["topic_sentiment_score_average"],
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
            "metrics": ["topic_sentiment_score_average"],
            "filters": [
                {"member": "topic_sentiment", "operator": "equals", "value": "MIXED"}
            ],
            "limit": 1,
        },
    },
    {
        "slug": "dashboard_topic_distribution",
        "title": "Sentiment by topic",
        "description": "Assignment-level sentiment counts grouped by topic.",
        "chart_type": "bar",
        "semantic_view": "survey_topics",
        "definition": {
            "dimensions": ["topic"],
            "metrics": [
                "assignment_count",
                "topic_assignment_positive_count",
                "topic_assignment_negative_count",
                "topic_assignment_neutral_count",
            ],
            "order": [{"member": "assignment_count", "direction": "desc"}],
            "limit": 1000,
        },
    },
    {
        "slug": "dashboard_department_distribution",
        "title": "Sentiment by department",
        "description": "Assignment-level sentiment counts grouped by department.",
        "chart_type": "bar",
        "semantic_view": "survey_departments",
        "definition": {
            "dimensions": ["department"],
            "metrics": [
                "assignment_count",
                "department_assignment_positive_count",
                "department_assignment_negative_count",
                "department_assignment_neutral_count",
            ],
            "order": [{"member": "assignment_count", "direction": "desc"}],
            "limit": 1000,
        },
    },
    {
        "slug": "dashboard_keyword_analysis",
        "title": "Sentiment by keyword",
        "description": "Top keyword assignment counts and sentiment breakdown.",
        "chart_type": "bar",
        "semantic_view": "survey_keywords",
        "definition": {
            "dimensions": ["keyword"],
            "metrics": [
                "assignment_count",
                "keyword_assignment_positive_count",
                "keyword_assignment_negative_count",
                "keyword_assignment_neutral_count",
            ],
            "order": [{"member": "assignment_count", "direction": "desc"}],
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
            "metrics": ["first_reported_at"],
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
            "metrics": ["last_reported_at"],
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
            "metrics": ["last_updated_at"],
            "limit": 1,
        },
    },
)


def upgrade() -> None:
    bind = op.get_bind()
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
        # A fresh installation may not have a user until application bootstrap.
        # The migration remains safe; an administrator can create the defaults
        # through the chart API after the first user is available.
        return

    slugs = [chart["slug"] for chart in _DEFAULT_CHARTS]
    existing = set(
        bind.execute(
            sa.text(
                "SELECT slug FROM analytics_charts WHERE slug IN "
                + "(" + ", ".join(f":slug_{index}" for index in range(len(slugs))) + ")"
            ),
            {f"slug_{index}": slug for index, slug in enumerate(slugs)},
        ).scalars()
    )
    now = datetime.now(timezone.utc)
    chart_table = sa.table(
        "analytics_charts",
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
    rows = [
        {
            **chart,
            "visibility": "viewer",
            "status": "published",
            "validation_errors": [],
            "created_by_id": user_id,
            "published_model_version_id": None,
            "created_at": now,
            "updated_at": now,
            "validated_at": now,
            "published_at": now,
            "archived_at": None,
        }
        for chart in _DEFAULT_CHARTS
        if chart["slug"] not in existing
    ]
    if rows:
        bind.execute(chart_table.insert(), rows)

    # Published charts are served from the immutable active catalog snapshot,
    # not directly from analytics_charts. If a catalog has already been
    # published, activate a replacement snapshot so the seeded graphs are
    # immediately visible to viewers. If no catalog exists yet, the published
    # chart rows will be included by the first normal catalog publication.
    active = bind.execute(
        sa.text(
            """
            SELECT id, catalog_snapshot
            FROM analytics_model_versions
            WHERE is_active = true
            ORDER BY catalog_version DESC
            LIMIT 1
            """
        )
    ).mappings().first()
    if active is None:
        return

    chart_rows = bind.execute(
        sa.text(
            """
            SELECT id, slug, title, description, chart_type, semantic_view,
                   definition, visibility, status, validation_errors,
                   published_model_version_id, validated_at, published_at,
                   archived_at, created_at, updated_at
            FROM analytics_charts
            WHERE slug IN ("""
            + ", ".join(f":slug_{index}" for index in range(len(slugs)))
            + ") AND status = 'published' AND archived_at IS NULL"
        ),
        {f"slug_{index}": slug for index, slug in enumerate(slugs)},
    ).mappings().all()

    def snapshot_chart(row: dict) -> dict:
        def iso(value):
            return value.astimezone(timezone.utc).isoformat() if value else None

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

    active_snapshot = active["catalog_snapshot"] or {}
    if not isinstance(active_snapshot, dict):
        raise RuntimeError("Active analytics catalog snapshot is invalid")
    snapshot = dict(active_snapshot)
    existing_charts = snapshot.get("charts")
    chart_snapshot = list(existing_charts) if isinstance(existing_charts, list) else []
    existing_slugs = {
        item.get("slug")
        for item in chart_snapshot
        if isinstance(item, dict)
    }
    chart_snapshot.extend(
        snapshot_chart(row)
        for row in chart_rows
        if row["slug"] not in existing_slugs
    )
    snapshot["charts"] = chart_snapshot

    cube_catalog = snapshot.get("cubeCatalog")
    if isinstance(cube_catalog, dict):
        cube_catalog = dict(cube_catalog)
    else:
        cube_catalog = {}
    next_version = bind.execute(
        sa.text(
            "SELECT COALESCE(MAX(catalog_version), 0) + 1 "
            "FROM analytics_model_versions"
        )
    ).scalar_one()
    cube_catalog["catalogVersion"] = next_version
    snapshot["cubeCatalog"] = cube_catalog
    definition_hash = hashlib.sha256(
        json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()

    bind.execute(
        sa.text(
            "UPDATE analytics_model_versions "
            "SET is_active = false, status = 'superseded', archived_at = :now "
            "WHERE is_active = true"
        ),
        {"now": now},
    )
    version_table = sa.table(
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
    result = bind.execute(
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
    )
    version_id = result.scalar_one()
    bind.execute(
        sa.text(
            "SELECT setval('analytics_catalog_version_seq', :version, true)"
        ),
        {"version": next_version},
    )
    bind.execute(
        sa.text(
            "UPDATE analytics_charts SET published_model_version_id = :version_id "
            "WHERE status = 'published' AND archived_at IS NULL"
        ),
        {"version_id": version_id},
    )


def downgrade() -> None:
    bind = op.get_bind()
    slugs = [chart["slug"] for chart in _DEFAULT_CHARTS]
    bind.execute(
        sa.text(
            "DELETE FROM analytics_charts WHERE slug IN "
            + "(" + ", ".join(f":slug_{index}" for index in range(len(slugs))) + ")"
        ),
        {f"slug_{index}": slug for index, slug in enumerate(slugs)},
    )
