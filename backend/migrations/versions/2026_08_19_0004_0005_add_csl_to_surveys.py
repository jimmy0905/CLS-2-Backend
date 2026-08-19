"""add nullable CSL score to surveys

Revision ID: 0004_add_csl
Revises: 0003_restore_timezone_offsets
Create Date: 2026-08-19 00:04:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0004_add_csl"
down_revision: Union[str, Sequence[str], None] = "0003_restore_timezone_offsets"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("surveys", sa.Column("csl", sa.Float(), nullable=True))
    op.create_index("idx_survey_csl", "surveys", ["csl"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_survey_csl", table_name="surveys")
    op.drop_column("surveys", "csl")
