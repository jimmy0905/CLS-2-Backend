"""repair SQL-only analytics objects on fresh installations

Revision ID: 0019_repair_fresh_analytics
Revises: 0018_frontend_identity
Create Date: 2026-09-03 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

from infrastructure.database.analytics_schema import repair_analytics_schema


revision: str = "0019_repair_fresh_analytics"
down_revision: str | Sequence[str] | None = "0018_frontend_identity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    repair_analytics_schema(op.get_bind(), operations=op)


def downgrade() -> None:
    # This is a repair revision. Removing healthy analytics objects would make
    # rollback destructive and would not restore the former broken state.
    pass
