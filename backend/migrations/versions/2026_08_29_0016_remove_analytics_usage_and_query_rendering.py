"""remove deprecated analytics field usage metadata

Revision ID: 0016_remove_analytics_rendering
Revises: 0015_assignment_sentiment_avg
Create Date: 2026-08-29 17:00:00.000000

``usage`` was once stored in both local field definitions and immutable catalog
snapshots to distinguish chartable dimensions from table-only dimensions. The
analytics query contract is now renderer-neutral, so this data is deliberately
removed from every historical catalog snapshot. Snapshot hashes are recomputed
because the stored document changes; catalog versions, lifecycle state, charts,
and query audit records are preserved.

The data removal is intentionally irreversible. Older application releases
already treat a missing usage value as ``table_only``.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from copy import deepcopy
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "0016_remove_analytics_rendering"
down_revision: str | Sequence[str] | None = "0015_assignment_sentiment_avg"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _field_table() -> sa.TableClause:
    return sa.table(
        "analytics_fields",
        sa.column("id", sa.Integer()),
        sa.column("definition", sa.JSON()),
    )


def _version_table() -> sa.TableClause:
    return sa.table(
        "analytics_model_versions",
        sa.column("id", sa.Integer()),
        sa.column("definition_hash", sa.String(length=64)),
        sa.column("catalog_snapshot", sa.JSON()),
    )


def _snapshot_hash(snapshot: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _without_usage(value: Any) -> tuple[Any, bool]:
    """Copy a JSON object and remove its top-level legacy usage key."""

    if not isinstance(value, dict) or "usage" not in value:
        return value, False
    result = deepcopy(value)
    result.pop("usage", None)
    return result, True


def _without_snapshot_usage(snapshot: Any) -> tuple[Any, bool]:
    """Strip usage from cubeCatalog.fields and the legacy top-level fields shape."""

    if not isinstance(snapshot, dict):
        return snapshot, False
    result = deepcopy(snapshot)
    changed = False
    catalogs = [result]
    cube_catalog = result.get("cubeCatalog")
    if isinstance(cube_catalog, dict):
        catalogs.append(cube_catalog)

    for catalog in catalogs:
        fields = catalog.get("fields")
        if not isinstance(fields, list):
            continue
        for field in fields:
            if isinstance(field, dict) and "usage" in field:
                field.pop("usage", None)
                changed = True
    return result, changed


def upgrade() -> None:
    bind = op.get_bind()
    fields = _field_table()
    for row in bind.execute(sa.select(fields.c.id, fields.c.definition)).mappings():
        definition, changed = _without_usage(row["definition"])
        if changed:
            bind.execute(
                fields.update()
                .where(fields.c.id == row["id"])
                .values(definition=definition)
            )

    versions = _version_table()
    for row in bind.execute(
        sa.select(versions.c.id, versions.c.catalog_snapshot)
    ).mappings():
        snapshot, changed = _without_snapshot_usage(row["catalog_snapshot"])
        if changed:
            assert isinstance(snapshot, dict)
            bind.execute(
                versions.update()
                .where(versions.c.id == row["id"])
                .values(
                    catalog_snapshot=snapshot,
                    definition_hash=_snapshot_hash(snapshot),
                )
            )


def downgrade() -> None:
    # Deliberately irreversible data cleanup. Earlier code accepts missing usage
    # and falls back to table_only, so a code rollback remains operational.
    return None
