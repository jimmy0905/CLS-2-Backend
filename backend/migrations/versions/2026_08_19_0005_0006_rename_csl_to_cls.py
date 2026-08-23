"""rename the CLS score column from the legacy CSL spelling

Revision ID: 0005_rename_csl_to_cls
Revises: 0004_add_csl
Create Date: 2026-08-19 00:05:00.000000
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0005_rename_csl_to_cls"
down_revision: Union[str, Sequence[str], None] = "0004_add_csl"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index("idx_survey_csl", table_name="surveys")
    op.alter_column("surveys", "csl", new_column_name="cls")
    op.create_index("idx_survey_cls", "surveys", ["cls"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_survey_cls", table_name="surveys")
    op.alter_column("surveys", "cls", new_column_name="csl")
    op.create_index("idx_survey_csl", "surveys", ["csl"], unique=False)
