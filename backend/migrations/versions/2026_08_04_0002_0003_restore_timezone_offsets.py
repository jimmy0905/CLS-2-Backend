"""restore timezone offsets to timestamps

Revision ID: 0003_restore_timezone_offsets
Revises: 0002_remove_timezone_offsets
Create Date: 2026-08-04 00:02:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0003_restore_timezone_offsets"
down_revision: Union[str, Sequence[str], None] = "0002_remove_timezone_offsets"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


UTC_TIMESTAMP_COLUMNS = (
    ("actions", ("created_at", "updated_at")),
    ("email_records", ("created_at", "updated_at")),
    ("generated_emails", ("created_at", "updated_at")),
    ("login_records", ("login_time",)),
    ("surveys", ("reported_at", "created_at", "updated_at")),
    ("upload_task_errors", ("created_at", "updated_at")),
    ("upload_tasks", ("created_at", "updated_at")),
    ("users", ("created_at", "updated_at")),
)


def upgrade() -> None:
    op.execute("SET timezone TO 'UTC'")
    op.execute("SET LOCAL lock_timeout TO '5s'")
    op.execute("SET LOCAL statement_timeout TO '5min'")
    _alter_timestamp_columns("TIMESTAMP WITH TIME ZONE", "AT TIME ZONE 'UTC'")


def downgrade() -> None:
    op.execute("SET timezone TO 'UTC'")
    op.execute("SET LOCAL lock_timeout TO '5s'")
    op.execute("SET LOCAL statement_timeout TO '5min'")
    _alter_timestamp_columns("TIMESTAMP WITHOUT TIME ZONE", "AT TIME ZONE 'UTC'")


def _alter_timestamp_columns(column_type: str, conversion: str) -> None:
    for table_name, columns in UTC_TIMESTAMP_COLUMNS:
        for column_name in columns:
            if not _column_exists(table_name, column_name):
                continue
            op.execute(
                f'ALTER TABLE "{table_name}" '
                f'ALTER COLUMN "{column_name}" '
                f'TYPE {column_type} '
                f'USING "{column_name}" {conversion}'
            )


def _column_exists(table_name: str, column_name: str) -> bool:
    connection = op.get_bind()
    return bool(
        connection.execute(
            sa.text(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_schema = current_schema()
                    AND table_name = :table_name
                    AND column_name = :column_name
                )
                """
            ),
            {"table_name": table_name, "column_name": column_name},
        ).scalar()
    )