"""add Cube semantic catalog and reporting grains

Revision ID: 0009_cube_semantic_catalog
Revises: 0008_log_retention_indexes
Create Date: 2026-08-25 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0009_cube_semantic_catalog"
down_revision: Union[str, Sequence[str], None] = "0008_log_retention_indexes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _create_raw_json_helpers() -> None:
    # raw_row_data historically contains a JSON string whose decoded value is
    # {"index": ..., "row": {...}}. New uploads store the row object directly.
    # These helpers accept both shapes and return NULL for malformed/type-invalid
    # values. Keys are function arguments, never interpolated into executable SQL.
    op.execute(
        r"""
        CREATE FUNCTION analytics_normalize_raw_row(payload json)
        RETURNS jsonb
        LANGUAGE plpgsql
        IMMUTABLE
        PARALLEL SAFE
        SECURITY INVOKER
        SET search_path = pg_catalog, public
        AS $function$
        DECLARE
            parsed jsonb;
            legacy_text text;
        BEGIN
            IF payload IS NULL THEN
                RETURN '{}'::jsonb;
            END IF;

            parsed := payload::jsonb;
            IF jsonb_typeof(parsed) = 'string' THEN
                BEGIN
                    legacy_text := parsed #>> '{}';
                    -- Historical ingestion used Python's permissive JSON
                    -- encoder, which could place bare NaN/Infinity tokens
                    -- inside the string envelope. Convert only value-position
                    -- tokens to quoted DQ sentinels before the jsonb cast.
                    legacy_text := regexp_replace(
                        legacy_text,
                        '([:\[,]([[:space:]]*))(NaN|[-+]?Infinity)(?=[[:space:]]*[,}\]])',
                        E'\\1"\\3"',
                        'gi'
                    );
                    parsed := legacy_text::jsonb;
                EXCEPTION WHEN OTHERS THEN
                    RETURN '{}'::jsonb;
                END;
            END IF;

            IF jsonb_typeof(parsed) <> 'object' THEN
                RETURN '{}'::jsonb;
            END IF;
            IF jsonb_typeof(parsed -> 'row') = 'object' THEN
                RETURN parsed -> 'row';
            END IF;
            RETURN parsed;
        EXCEPTION WHEN OTHERS THEN
            RETURN '{}'::jsonb;
        END;
        $function$
        """
    )
    op.execute(
        r"""
        CREATE FUNCTION analytics_raw_value(payload json, field_key text)
        RETURNS text
        LANGUAGE sql
        IMMUTABLE
        PARALLEL SAFE
        SECURITY INVOKER
        SET search_path = pg_catalog, public
        AS $function$
        SELECT analytics_normalize_raw_row(payload) ->> field_key;
        $function$
        """
    )
    op.execute(
        r"""
        CREATE FUNCTION analytics_raw_number(payload json, field_key text)
        RETURNS double precision
        LANGUAGE plpgsql
        IMMUTABLE
        PARALLEL SAFE
        SECURITY INVOKER
        SET search_path = pg_catalog, public
        AS $function$
        DECLARE candidate text;
        DECLARE parsed double precision;
        BEGIN
            candidate := analytics_raw_value(payload, field_key);
            IF candidate IS NULL OR candidate !~
                '^\s*[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?\s*$'
            THEN
                RETURN NULL;
            END IF;
            parsed := candidate::double precision;
            IF parsed = 'Infinity'::double precision
               OR parsed = '-Infinity'::double precision
            THEN
                RETURN NULL;
            END IF;
            RETURN parsed;
        EXCEPTION WHEN OTHERS THEN
            RETURN NULL;
        END;
        $function$
        """
    )
    op.execute(
        r"""
        CREATE FUNCTION analytics_raw_boolean(payload json, field_key text)
        RETURNS boolean
        LANGUAGE plpgsql
        IMMUTABLE
        PARALLEL SAFE
        SECURITY INVOKER
        SET search_path = pg_catalog, public
        AS $function$
        DECLARE candidate text;
        BEGIN
            candidate := lower(btrim(analytics_raw_value(payload, field_key)));
            IF candidate = ANY (ARRAY['true', 't', 'yes', 'y', '1']) THEN
                RETURN true;
            END IF;
            IF candidate = ANY (ARRAY['false', 'f', 'no', 'n', '0']) THEN
                RETURN false;
            END IF;
            RETURN NULL;
        EXCEPTION WHEN OTHERS THEN
            RETURN NULL;
        END;
        $function$
        """
    )
    op.execute(
        r"""
        CREATE FUNCTION analytics_raw_number_invalid(payload json, field_key text)
        RETURNS boolean
        LANGUAGE sql
        IMMUTABLE
        PARALLEL SAFE
        SECURITY INVOKER
        SET search_path = pg_catalog, public
        AS $function$
        SELECT lower(btrim(COALESCE(analytics_raw_value(payload, field_key), '')))
               = ANY (ARRAY[
                   'nan', 'inf', '+inf', '-inf',
                   'infinity', '+infinity', '-infinity'
               ]);
        $function$
        """
    )
    op.execute(
        r"""
        CREATE FUNCTION analytics_raw_date(payload json, field_key text)
        RETURNS date
        LANGUAGE plpgsql
        STABLE
        PARALLEL SAFE
        SECURITY INVOKER
        SET search_path = pg_catalog, public
        AS $function$
        BEGIN
            RETURN analytics_raw_value(payload, field_key)::date;
        EXCEPTION WHEN OTHERS THEN
            RETURN NULL;
        END;
        $function$
        """
    )
    op.execute(
        r"""
        CREATE FUNCTION analytics_raw_time(payload json, field_key text)
        RETURNS time without time zone
        LANGUAGE plpgsql
        STABLE
        PARALLEL SAFE
        SECURITY INVOKER
        SET search_path = pg_catalog, public
        AS $function$
        BEGIN
            RETURN analytics_raw_value(payload, field_key)::time;
        EXCEPTION WHEN OTHERS THEN
            RETURN NULL;
        END;
        $function$
        """
    )
    op.execute(
        r"""
        CREATE FUNCTION analytics_raw_timestamp(payload json, field_key text)
        RETURNS timestamp with time zone
        LANGUAGE plpgsql
        STABLE
        PARALLEL SAFE
        SECURITY INVOKER
        SET search_path = pg_catalog, public
        AS $function$
        BEGIN
            RETURN analytics_raw_value(payload, field_key)::timestamptz;
        EXCEPTION WHEN OTHERS THEN
            RETURN NULL;
        END;
        $function$
        """
    )


def _create_reporting_views() -> None:
    op.execute("DROP VIEW IF EXISTS analytics_survey_facts")
    op.execute(
        """
        CREATE VIEW analytics_survey_facts AS
        SELECT
            s.id,
            s.survey_id,
            s.respondent_id,
            s.reported_at,
            s.created_at,
            s.updated_at,
            s.sentiment::text AS sentiment,
            s.topic_sentiment::text AS topic_sentiment,
            s.topic_sentiment_score,
            s.cls,
            s.comment,
            s.raw_row_data,
            analytics_normalize_raw_row(s.raw_row_data) AS raw_row_object,
            s.store_key,
            s.channel_id,
            c.name AS channel_name,
            s.delivery_service_id,
            ds.name AS delivery_service_name,
            COALESCE(st.store_name_english, st.store_name_local) AS store_name,
            st.store_name_english,
            st.store_name_local,
            st.bu_key,
            st.area_manager,
            st.store_format,
            st.store_type,
            st.operations_controller,
            st.regional_manager,
            st.px,
            st.csr,
            st.dr,
            st.mag_type,
            st.cf_grouping,
            st.store_brand,
            st.competitor,
            st.region,
            st.area,
            st.province,
            st.territory,
            st.toh,
            st.district,
            st.city,
            st.operations_manager,
            st.district_manager,
            st.sic,
            st.soc,
            st.tech_life_type,
            st.operation_manager_tl,
            st.region_manager_tl,
            st.relocation,
            st.latitude,
            st.longitude,
            st.store_open_date,
            st.store_close_date,
            st.is_closed
        FROM surveys s
        JOIN stores st ON st.store_key = s.store_key
        LEFT JOIN channels c ON c.id = s.channel_id
        LEFT JOIN delivery_services ds ON ds.id = s.delivery_service_id
        WHERE COALESCE(s.is_deleted, false) = false
        """
    )
    op.execute(
        """
        CREATE VIEW analytics_survey_topics AS
        SELECT
            assignment.id AS assignment_id,
            facts.*,
            assignment.topic_id,
            topic.topic,
            assignment.sentiment::text AS assignment_sentiment,
            1::bigint AS assignment_count,
            assignment.survey_id AS distinct_survey_id
        FROM survey_topics assignment
        JOIN analytics_survey_facts facts ON facts.id = assignment.survey_id
        JOIN topics topic ON topic.id = assignment.topic_id
        """
    )
    op.execute(
        """
        CREATE VIEW analytics_survey_departments AS
        SELECT
            assignment.id AS assignment_id,
            facts.*,
            assignment.department_id,
            department.name AS department_name,
            assignment.sentiment::text AS assignment_sentiment,
            1::bigint AS assignment_count,
            assignment.survey_id AS distinct_survey_id
        FROM survey_departments assignment
        JOIN analytics_survey_facts facts ON facts.id = assignment.survey_id
        JOIN departments department ON department.id = assignment.department_id
        """
    )
    op.execute(
        """
        CREATE VIEW analytics_survey_keywords AS
        SELECT
            assignment.id AS assignment_id,
            facts.*,
            assignment.keyword_id,
            keyword.keyword,
            assignment.sentiment::text AS assignment_sentiment,
            1::bigint AS assignment_count,
            assignment.survey_id AS distinct_survey_id
        FROM survey_keywords assignment
        JOIN analytics_survey_facts facts ON facts.id = assignment.survey_id
        JOIN keywords keyword ON keyword.id = assignment.keyword_id
        """
    )


def upgrade() -> None:
    op.alter_column("analytics_fields", "created_by_id", nullable=True)
    op.add_column(
        "analytics_fields",
        sa.Column(
            "semantic_view",
            sa.String(length=32),
            nullable=False,
            server_default="survey_responses",
        ),
    )
    op.add_column(
        "analytics_fields",
        sa.Column("inferred_data_type", sa.String(length=16), nullable=True),
    )
    op.add_column(
        "analytics_fields",
        sa.Column(
            "type_conflicts",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'::json"),
        ),
    )
    op.add_column(
        "analytics_fields",
        sa.Column(
            "sample_values",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'::json"),
        ),
    )
    op.add_column(
        "analytics_fields",
        sa.Column(
            "visibility", sa.String(length=16), nullable=False, server_default="viewer"
        ),
    )
    op.add_column(
        "analytics_fields",
        sa.Column(
            "occurrence_count", sa.BigInteger(), nullable=False, server_default="0"
        ),
    )
    op.add_column(
        "analytics_fields",
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "analytics_fields",
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "analytics_fields",
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "idx_analytics_fields_source",
        "analytics_fields",
        ["source_kind", "source_key"],
        unique=False,
    )
    op.create_index(
        "idx_analytics_fields_view_visibility_status",
        "analytics_fields",
        ["semantic_view", "visibility", "status"],
        unique=False,
    )

    op.execute("CREATE SEQUENCE analytics_catalog_version_seq START WITH 1")
    op.create_table(
        "analytics_model_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "catalog_version",
            sa.BigInteger(),
            nullable=False,
            server_default=sa.text("nextval('analytics_catalog_version_seq')"),
        ),
        sa.Column(
            "status", sa.String(length=16), nullable=False, server_default="draft"
        ),
        sa.Column("definition_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "catalog_snapshot",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'::json"),
        ),
        sa.Column(
            "validation_errors",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'::json"),
        ),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column(
            "created_by_id", sa.CHAR(length=36), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "catalog_version", name="uq_analytics_model_versions_catalog_version"
        ),
    )
    op.create_index(
        "ix_analytics_model_versions_status",
        "analytics_model_versions",
        ["status"],
        unique=False,
    )
    op.create_index(
        "uq_analytics_model_versions_one_active",
        "analytics_model_versions",
        ["is_active"],
        unique=True,
        postgresql_where=sa.text("is_active"),
    )

    op.create_table(
        "analytics_metrics",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "semantic_view",
            sa.String(length=32),
            nullable=False,
            server_default="survey_responses",
        ),
        sa.Column(
            "field_id", sa.Integer(), sa.ForeignKey("analytics_fields.id"), nullable=True
        ),
        sa.Column("source_member", sa.String(length=64), nullable=True),
        sa.Column("operation", sa.String(length=32), nullable=False),
        sa.Column(
            "weight_field_id",
            sa.Integer(),
            sa.ForeignKey("analytics_fields.id"),
            nullable=True,
        ),
        sa.Column("weight_member", sa.String(length=64), nullable=True),
        sa.Column("confidence_level", sa.Float(), nullable=True),
        sa.Column(
            "definition", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")
        ),
        sa.Column(
            "visibility", sa.String(length=16), nullable=False, server_default="viewer"
        ),
        sa.Column(
            "status", sa.String(length=16), nullable=False, server_default="draft"
        ),
        sa.Column(
            "created_by_id", sa.CHAR(length=36), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column(
            "published_model_version_id",
            sa.Integer(),
            sa.ForeignKey("analytics_model_versions.id"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("slug", name="uq_analytics_metrics_slug"),
    )
    op.create_index(
        "ix_analytics_metrics_status", "analytics_metrics", ["status"], unique=False
    )
    op.create_index(
        "idx_analytics_metrics_view_visibility_status",
        "analytics_metrics",
        ["semantic_view", "visibility", "status"],
        unique=False,
    )

    op.add_column("analytics_charts", sa.Column("slug", sa.String(length=64), nullable=True))
    op.add_column(
        "analytics_charts", sa.Column("semantic_view", sa.String(length=32), nullable=True)
    )
    op.add_column(
        "analytics_charts",
        sa.Column(
            "visibility", sa.String(length=16), nullable=False, server_default="viewer"
        ),
    )
    op.add_column(
        "analytics_charts",
        sa.Column(
            "validation_errors",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'::json"),
        ),
    )
    op.add_column(
        "analytics_charts",
        sa.Column("published_model_version_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "analytics_charts",
        sa.Column("validated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "analytics_charts",
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_analytics_charts_published_model_version",
        "analytics_charts",
        "analytics_model_versions",
        ["published_model_version_id"],
        ["id"],
    )
    op.create_index(
        "uq_analytics_charts_slug", "analytics_charts", ["slug"], unique=True
    )
    op.create_index(
        "idx_analytics_charts_visibility_status",
        "analytics_charts",
        ["visibility", "status"],
        unique=False,
    )

    op.create_table(
        "analytics_query_logs",
        sa.Column("id", sa.CHAR(length=36), primary_key=True),
        sa.Column(
            "requested_by_id", sa.CHAR(length=36), sa.ForeignKey("users.id"), nullable=True
        ),
        sa.Column(
            "model_version_id",
            sa.Integer(),
            sa.ForeignKey("analytics_model_versions.id"),
            nullable=True,
        ),
        sa.Column("semantic_view", sa.String(length=32), nullable=False),
        sa.Column("request", sa.JSON(), nullable=False),
        sa.Column("cube_query", sa.JSON(), nullable=True),
        sa.Column(
            "status", sa.String(length=16), nullable=False, server_default="pending"
        ),
        sa.Column("row_count", sa.Integer(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("freshness_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "idx_analytics_query_logs_created_at",
        "analytics_query_logs",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        "idx_analytics_query_logs_status_created",
        "analytics_query_logs",
        ["status", "created_at"],
        unique=False,
    )

    op.create_table(
        "analytics_export_jobs",
        sa.Column("id", sa.CHAR(length=36), primary_key=True),
        sa.Column(
            "requested_by_id", sa.CHAR(length=36), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column(
            "query_log_id",
            sa.CHAR(length=36),
            sa.ForeignKey("analytics_query_logs.id"),
            nullable=True,
        ),
        sa.Column(
            "model_version_id",
            sa.Integer(),
            sa.ForeignKey("analytics_model_versions.id"),
            nullable=True,
        ),
        sa.Column("request", sa.JSON(), nullable=False),
        sa.Column("export_format", sa.String(length=8), nullable=False),
        sa.Column(
            "status", sa.String(length=16), nullable=False, server_default="queued"
        ),
        sa.Column("row_count", sa.BigInteger(), nullable=True),
        sa.Column("storage_path", sa.String(length=500), nullable=True),
        sa.Column("content_type", sa.String(length=120), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("downloaded_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "idx_analytics_export_jobs_status_created",
        "analytics_export_jobs",
        ["status", "created_at"],
        unique=False,
    )
    op.create_index(
        "idx_analytics_export_jobs_expires_at",
        "analytics_export_jobs",
        ["expires_at"],
        unique=False,
    )

    op.add_column(
        "upload_tasks", sa.Column("analytics_affected_months", sa.JSON(), nullable=True)
    )
    op.add_column(
        "upload_tasks",
        sa.Column("analytics_refresh_status", sa.String(length=32), nullable=True),
    )

    _create_raw_json_helpers()
    _create_reporting_views()


def _restore_original_reporting_view() -> None:
    op.execute(
        """
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
        """
    )


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS analytics_survey_keywords")
    op.execute("DROP VIEW IF EXISTS analytics_survey_departments")
    op.execute("DROP VIEW IF EXISTS analytics_survey_topics")
    op.execute("DROP VIEW IF EXISTS analytics_survey_facts")
    _restore_original_reporting_view()

    op.execute("DROP FUNCTION IF EXISTS analytics_raw_timestamp(json, text)")
    op.execute("DROP FUNCTION IF EXISTS analytics_raw_time(json, text)")
    op.execute("DROP FUNCTION IF EXISTS analytics_raw_date(json, text)")
    op.execute("DROP FUNCTION IF EXISTS analytics_raw_boolean(json, text)")
    op.execute("DROP FUNCTION IF EXISTS analytics_raw_number_invalid(json, text)")
    op.execute("DROP FUNCTION IF EXISTS analytics_raw_number(json, text)")
    op.execute("DROP FUNCTION IF EXISTS analytics_raw_value(json, text)")
    op.execute("DROP FUNCTION IF EXISTS analytics_normalize_raw_row(json)")

    op.drop_column("upload_tasks", "analytics_refresh_status")
    op.drop_column("upload_tasks", "analytics_affected_months")

    op.drop_index("idx_analytics_export_jobs_expires_at", table_name="analytics_export_jobs")
    op.drop_index(
        "idx_analytics_export_jobs_status_created", table_name="analytics_export_jobs"
    )
    op.drop_table("analytics_export_jobs")
    op.drop_index(
        "idx_analytics_query_logs_status_created", table_name="analytics_query_logs"
    )
    op.drop_index("idx_analytics_query_logs_created_at", table_name="analytics_query_logs")
    op.drop_table("analytics_query_logs")

    op.drop_index("idx_analytics_charts_visibility_status", table_name="analytics_charts")
    op.drop_index("uq_analytics_charts_slug", table_name="analytics_charts")
    op.drop_constraint(
        "fk_analytics_charts_published_model_version",
        "analytics_charts",
        type_="foreignkey",
    )
    op.drop_column("analytics_charts", "archived_at")
    op.drop_column("analytics_charts", "validated_at")
    op.drop_column("analytics_charts", "published_model_version_id")
    op.drop_column("analytics_charts", "validation_errors")
    op.drop_column("analytics_charts", "visibility")
    op.drop_column("analytics_charts", "semantic_view")
    op.drop_column("analytics_charts", "slug")

    op.drop_index(
        "idx_analytics_metrics_view_visibility_status", table_name="analytics_metrics"
    )
    op.drop_index("ix_analytics_metrics_status", table_name="analytics_metrics")
    op.drop_table("analytics_metrics")
    op.drop_index(
        "uq_analytics_model_versions_one_active", table_name="analytics_model_versions"
    )
    op.drop_index(
        "ix_analytics_model_versions_status", table_name="analytics_model_versions"
    )
    op.drop_table("analytics_model_versions")
    op.execute("DROP SEQUENCE analytics_catalog_version_seq")

    op.drop_index(
        "idx_analytics_fields_view_visibility_status", table_name="analytics_fields"
    )
    op.drop_index("idx_analytics_fields_source", table_name="analytics_fields")
    op.drop_column("analytics_fields", "archived_at")
    op.drop_column("analytics_fields", "published_at")
    op.drop_column("analytics_fields", "last_seen_at")
    op.drop_column("analytics_fields", "occurrence_count")
    op.drop_column("analytics_fields", "visibility")
    op.drop_column("analytics_fields", "sample_values")
    op.drop_column("analytics_fields", "type_conflicts")
    op.drop_column("analytics_fields", "inferred_data_type")
    op.drop_column("analytics_fields", "semantic_view")
    # Discovered candidates are actor-less. Restore 0007's NOT NULL contract
    # without deleting promoted catalog data by assigning the oldest local user.
    op.execute(
        """
        UPDATE analytics_fields
        SET created_by_id = (SELECT id FROM users ORDER BY created_at, id LIMIT 1)
        WHERE created_by_id IS NULL
        """
    )
    op.alter_column("analytics_fields", "created_by_id", nullable=False)

    # analytics_field_values is intentionally retained: 0009 deprecates the EAV
    # path, but dropping it would make rollback destructive for older deployments.
