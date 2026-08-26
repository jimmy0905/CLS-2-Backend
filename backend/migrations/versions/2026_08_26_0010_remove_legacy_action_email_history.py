"""remove retired action and email history tables

Revision ID: 0010_remove_legacy_action_email_history
Revises: 0009_cube_semantic_catalog
Create Date: 2026-08-26 00:00:00.000000

The retired tables contain operational history that is intentionally not
archived. Downgrade restores empty compatible schemas only; deleted rows cannot
be recovered.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0010_remove_legacy_action_email_history"
down_revision: Union[str, Sequence[str], None] = "0009_cube_semantic_catalog"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_table("email_records")
    op.drop_table("generated_emails")
    op.drop_table("actions")


def downgrade() -> None:
    op.create_table(
        "actions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.CHAR(length=36), sa.ForeignKey("users.id")),
        sa.Column("summary", sa.Text()),
        sa.Column("actions_items", sa.JSON()),
        sa.Column("survey_data", sa.JSON()),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "generated_emails",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.CHAR(length=36), sa.ForeignKey("users.id")),
        sa.Column("input_data", sa.JSON()),
        sa.Column("subject_line", sa.Text()),
        sa.Column("email_body", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "email_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.CHAR(length=36), sa.ForeignKey("users.id")),
        sa.Column("subject_line", sa.Text()),
        sa.Column("email_body", sa.Text()),
        sa.Column("to", sa.JSON()),
        sa.Column("cc", sa.JSON()),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
    )
