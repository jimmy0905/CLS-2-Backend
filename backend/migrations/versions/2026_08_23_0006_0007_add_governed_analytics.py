"""add governed analytics metadata and reporting projection

Revision ID: 0007_governed_analytics
Revises: 0005_rename_csl_to_cls
Create Date: 2026-08-23 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0007_governed_analytics"
down_revision: Union[str, Sequence[str], None] = "0005_rename_csl_to_cls"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "analytics_fields",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("data_type", sa.String(length=16), nullable=False),
        sa.Column("source_kind", sa.String(length=16), nullable=False),
        sa.Column("source_key", sa.String(length=128), nullable=True),
        sa.Column("definition", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="draft"),
        sa.Column("is_promoted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_by_id", sa.CHAR(length=36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("promoted_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("slug"),
    )
    op.create_index("ix_analytics_fields_slug", "analytics_fields", ["slug"], unique=True)
    op.create_index("ix_analytics_fields_status", "analytics_fields", ["status"], unique=False)
    op.create_index("idx_analytics_fields_status_updated", "analytics_fields", ["status", "updated_at"], unique=False)
    op.create_table(
        "analytics_charts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.String(length=160), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("chart_type", sa.String(length=16), nullable=False),
        sa.Column("definition", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="draft"),
        sa.Column("created_by_id", sa.CHAR(length=36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_analytics_charts_status", "analytics_charts", ["status"], unique=False)
    op.create_index("idx_analytics_charts_status_updated", "analytics_charts", ["status", "updated_at"], unique=False)
    op.create_table(
        "analytics_field_values",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("field_id", sa.Integer(), sa.ForeignKey("analytics_fields.id", ondelete="CASCADE"), nullable=False),
        sa.Column("survey_id", sa.Integer(), sa.ForeignKey("surveys.id", ondelete="CASCADE"), nullable=False),
        sa.Column("value_text", sa.String(length=500), nullable=True),
        sa.Column("value_number", sa.Float(), nullable=True),
        sa.Column("value_date", sa.Date(), nullable=True),
        sa.Column("refreshed_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("field_id", "survey_id", name="uq_analytics_field_value"),
    )
    op.create_index("idx_analytics_field_values_text", "analytics_field_values", ["field_id", "value_text"], unique=False)
    op.create_index("idx_analytics_field_values_number", "analytics_field_values", ["field_id", "value_number"], unique=False)
    op.create_index("idx_analytics_field_values_date", "analytics_field_values", ["field_id", "value_date"], unique=False)
    op.create_table(
        "analytics_audit_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("actor_id", sa.CHAR(length=36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("resource_type", sa.String(length=32), nullable=False),
        sa.Column("resource_id", sa.String(length=64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_analytics_audit_logs_action", "analytics_audit_logs", ["action"], unique=False)
    op.execute("""
        CREATE VIEW analytics_survey_facts AS
        SELECT s.id, s.reported_at, s.sentiment, s.topic_sentiment,
               s.topic_sentiment_score, s.cls, s.comment, s.raw_row_data,
               s.store_key, COALESCE(st.store_name_english, st.store_name_local) AS store_name,
               st.region, st.area, st.district, st.city, st.store_format, st.store_brand,
               c.name AS channel_name, ds.name AS delivery_service_name
        FROM surveys s
        JOIN stores st ON st.store_key = s.store_key
        LEFT JOIN channels c ON c.id = s.channel_id
        LEFT JOIN delivery_services ds ON ds.id = s.delivery_service_id
        WHERE COALESCE(s.is_deleted, false) = false
    """)


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS analytics_survey_facts")
    op.drop_index("ix_analytics_audit_logs_action", table_name="analytics_audit_logs")
    op.drop_table("analytics_audit_logs")
    op.drop_index("idx_analytics_field_values_date", table_name="analytics_field_values")
    op.drop_index("idx_analytics_field_values_number", table_name="analytics_field_values")
    op.drop_index("idx_analytics_field_values_text", table_name="analytics_field_values")
    op.drop_table("analytics_field_values")
    op.drop_index("idx_analytics_charts_status_updated", table_name="analytics_charts")
    op.drop_index("ix_analytics_charts_status", table_name="analytics_charts")
    op.drop_table("analytics_charts")
    op.drop_index("idx_analytics_fields_status_updated", table_name="analytics_fields")
    op.drop_index("ix_analytics_fields_status", table_name="analytics_fields")
    op.drop_index("ix_analytics_fields_slug", table_name="analytics_fields")
    op.drop_table("analytics_fields")
