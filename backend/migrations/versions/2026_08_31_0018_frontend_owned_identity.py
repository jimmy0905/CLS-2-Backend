"""move identity authority to the frontend and snapshot analytics actors

Revision ID: 0018_frontend_identity
Revises: 0017_assignment_view_grants
Create Date: 2026-08-31 10:00:00.000000

This is an intentionally one-way maintenance-window migration. Rollback must
restore the pre-cutover database backup because password credentials are
removed after their verified import into the frontend auth database.
"""

from __future__ import annotations

import hashlib
import unicodedata
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from core.config import DEPLOYMENT_PROFILE

revision: str = "0018_frontend_identity"
down_revision: str | Sequence[str] | None = "0017_assignment_view_grants"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_ACTOR_TABLES = (
    ("analytics_audit_logs", "actor", "actor_id", True),
    ("analytics_charts", "created_by", "created_by_id", False),
    ("analytics_export_jobs", "requested_by", "requested_by_id", False),
    ("analytics_fields", "created_by", "created_by_id", True),
    ("analytics_metrics", "created_by", "created_by_id", False),
    ("analytics_model_versions", "created_by", "created_by_id", False),
    ("analytics_query_logs", "requested_by", "requested_by_id", True),
)


def _admin_checksum(rows: list[sa.Row]) -> str:
    digest = hashlib.sha256()
    for row in rows:
        normalized_username = unicodedata.normalize(
            "NFKC", str(row.username).strip()
        ).lower()
        digest.update(
            f"{row.id}\0{normalized_username}\0{row.password or ''}\n".encode()
        )
    return digest.hexdigest()


def _verify_frontend_import() -> None:
    connection = op.get_bind()
    admins = list(
        connection.execute(
            sa.text(
                """
                SELECT id, username, password
                FROM users
                WHERE role = 'admin'
                  AND oauth_provider IS NULL
                  AND oauth_id IS NULL
                  AND COALESCE(is_deleted, false) = false
                ORDER BY id
                """
            )
        )
    )
    if not admins:
        return
    receipt_table = connection.scalar(
        sa.text("SELECT to_regclass('public.frontend_auth_migration_receipts')")
    )
    if receipt_table is None:
        raise RuntimeError(
            "Active backend administrators have not been imported into the "
            "frontend auth database"
        )
    receipt = (
        connection.execute(
            sa.text(
                """
            SELECT admin_count, admin_checksum
            FROM frontend_auth_migration_receipts
            WHERE migration_key = 'frontend_auth_v1' AND profile = :profile
            """
            ),
            {"profile": DEPLOYMENT_PROFILE},
        )
        .mappings()
        .one_or_none()
    )
    if receipt is None or receipt["admin_count"] != len(admins):
        raise RuntimeError("Frontend administrator import receipt count mismatch")
    if receipt["admin_checksum"] != _admin_checksum(admins):
        raise RuntimeError("Frontend administrator import receipt checksum mismatch")


def upgrade() -> None:
    _verify_frontend_import()

    for table, prefix, old_column, nullable in _ACTOR_TABLES:
        op.add_column(table, sa.Column(f"{prefix}_subject", sa.String(255)))
        op.add_column(table, sa.Column(f"{prefix}_label", sa.String(255)))
        op.add_column(table, sa.Column(f"{prefix}_role", sa.String(16)))
        op.execute(
            sa.text(
                f"""
                UPDATE {table} AS target
                SET {prefix}_subject = CASE
                        WHEN source.oauth_provider = 'azure'
                             AND source.oauth_id IS NOT NULL
                            THEN 'entra:' || source.oauth_id
                        WHEN source.role = 'admin' AND source.oauth_provider IS NULL
                            THEN 'admin:' || source.id
                        ELSE 'legacy:' || source.id
                    END,
                    {prefix}_label = source.username,
                    {prefix}_role = CASE
                        WHEN source.role = 'admin' THEN 'admin' ELSE 'viewer'
                    END
                FROM users AS source
                WHERE target.{old_column} = source.id
                """
            )
        )
        if not nullable:
            op.alter_column(table, f"{prefix}_subject", nullable=False)
            op.alter_column(table, f"{prefix}_label", nullable=False)
            op.alter_column(table, f"{prefix}_role", nullable=False)
        op.execute(
            f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {table}_{old_column}_fkey"
        )
        op.drop_column(table, old_column)

    op.create_index(
        "idx_analytics_export_jobs_requester_status",
        "analytics_export_jobs",
        ["requested_by_subject", "status"],
    )
    op.create_index(
        "idx_analytics_query_logs_requester_created",
        "analytics_query_logs",
        ["requested_by_subject", "created_at"],
    )
    op.drop_table("login_records")
    op.drop_table("users")


def downgrade() -> None:
    raise RuntimeError(
        "Frontend-owned identity migration is irreversible; restore the "
        "documented pre-cutover database backup"
    )
