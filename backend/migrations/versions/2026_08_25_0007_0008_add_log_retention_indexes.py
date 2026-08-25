"""add indexes for audit-log retention

Revision ID: 0008_log_retention_indexes
Revises: 0007_governed_analytics
Create Date: 2026-08-25 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0008_log_retention_indexes"
down_revision: Union[str, Sequence[str], None] = "0007_governed_analytics"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "idx_login_records_login_time", "login_records", ["login_time"], unique=False
    )
    op.create_index(
        "idx_analytics_audit_logs_created_at",
        "analytics_audit_logs",
        ["created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_analytics_audit_logs_created_at", table_name="analytics_audit_logs")
    op.drop_index("idx_login_records_login_time", table_name="login_records")
