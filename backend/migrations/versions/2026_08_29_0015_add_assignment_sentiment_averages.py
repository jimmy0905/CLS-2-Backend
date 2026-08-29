"""add numeric sentiment scores to single-family assignment reporting views

Revision ID: 0015_assignment_sentiment_averages
Revises: 0014_assignment_matrix_view
Create Date: 2026-08-29 15:00:00.000000

The three assignment grains each retain a categorical assignment sentiment for
breakdowns.  This revision also exposes its numeric score for governed average
measures: POSITIVE=1, NEGATIVE=0, and NEUTRAL=-1.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0015_assignment_sentiment_averages"
down_revision: str | Sequence[str] | None = "0014_assignment_matrix_view"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_ASSIGNMENT_VIEWS = (
    "analytics_survey_topics",
    "analytics_survey_departments",
    "analytics_survey_keywords",
)
_VIEW_SECURITY_SNAPSHOT = "_analytics_assignment_view_security"


def _score_expression() -> str:
    return """
            CASE assignment.sentiment::text
                WHEN 'POSITIVE' THEN 1
                WHEN 'NEGATIVE' THEN 0
                WHEN 'NEUTRAL' THEN -1
            END::smallint AS assignment_sentiment_score
    """


def _create_scored_assignment_views() -> None:
    score = _score_expression()
    op.execute(
        f"""
        CREATE OR REPLACE VIEW analytics_survey_topics AS
        SELECT
            assignment.id AS assignment_id,
            facts.*,
            assignment.topic_id,
            topic.topic,
            assignment.sentiment::text AS assignment_sentiment,
            1::bigint AS assignment_count,
            assignment.survey_id AS distinct_survey_id,
            {score}
        FROM survey_topics assignment
        JOIN analytics_survey_facts facts ON facts.id = assignment.survey_id
        JOIN topics topic ON topic.id = assignment.topic_id
        """
    )
    op.execute(
        f"""
        CREATE OR REPLACE VIEW analytics_survey_departments AS
        SELECT
            assignment.id AS assignment_id,
            facts.*,
            assignment.department_id,
            department.name AS department_name,
            assignment.sentiment::text AS assignment_sentiment,
            1::bigint AS assignment_count,
            assignment.survey_id AS distinct_survey_id,
            {score}
        FROM survey_departments assignment
        JOIN analytics_survey_facts facts ON facts.id = assignment.survey_id
        JOIN departments department ON department.id = assignment.department_id
        """
    )
    op.execute(
        f"""
        CREATE OR REPLACE VIEW analytics_survey_keywords AS
        SELECT
            assignment.id AS assignment_id,
            facts.*,
            assignment.keyword_id,
            keyword.keyword,
            assignment.sentiment::text AS assignment_sentiment,
            1::bigint AS assignment_count,
            assignment.survey_id AS distinct_survey_id,
            {score}
        FROM survey_keywords assignment
        JOIN analytics_survey_facts facts ON facts.id = assignment.survey_id
        JOIN keywords keyword ON keyword.id = assignment.keyword_id
        """
    )


def _capture_assignment_view_security() -> None:
    """Preserve owners and explicit grants before replacing a view by DROP/CREATE."""

    view_names = ", ".join(f"'{view}'" for view in _ASSIGNMENT_VIEWS)
    op.execute(
        f"""
        CREATE TEMPORARY TABLE {_VIEW_SECURITY_SNAPSHOT} ON COMMIT DROP AS
        SELECT
            relation.relname,
            relation.relowner AS owner_oid,
            acl.grantee,
            acl.privilege_type,
            acl.is_grantable
        FROM pg_class relation
        LEFT JOIN LATERAL aclexplode(relation.relacl) acl ON true
        WHERE relation.relnamespace = 'public'::regnamespace
          AND relation.relkind = 'v'
          AND relation.relname IN ({view_names})
        """
    )


def _create_unscored_assignment_views() -> None:
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


def _restore_assignment_view_security() -> None:
    op.execute(
        f"""
        DO $restore_assignment_view_security$
        DECLARE
            grant_record record;
        BEGIN
            FOR grant_record IN
                SELECT DISTINCT relname, grantee, privilege_type, is_grantable
                FROM {_VIEW_SECURITY_SNAPSHOT}
                WHERE grantee IS NOT NULL
            LOOP
                EXECUTE format(
                    'GRANT %s ON TABLE public.%I TO %s%s',
                    grant_record.privilege_type,
                    grant_record.relname,
                    CASE
                        WHEN grant_record.grantee = 0 THEN 'PUBLIC'
                        ELSE quote_ident(pg_get_userbyid(grant_record.grantee))
                    END,
                    CASE
                        WHEN grant_record.is_grantable THEN ' WITH GRANT OPTION'
                        ELSE ''
                    END
                );
            END LOOP;

            FOR grant_record IN
                SELECT DISTINCT relname, owner_oid
                FROM {_VIEW_SECURITY_SNAPSHOT}
            LOOP
                EXECUTE format(
                    'ALTER VIEW public.%I OWNER TO %I',
                    grant_record.relname,
                    pg_get_userbyid(grant_record.owner_oid)
                );
            END LOOP;
        END
        $restore_assignment_view_security$
        """
    )


def upgrade() -> None:
    _create_scored_assignment_views()


def downgrade() -> None:
    _capture_assignment_view_security()
    for view in _ASSIGNMENT_VIEWS:
        op.execute(f"DROP VIEW {view}")
    _create_unscored_assignment_views()
    _restore_assignment_view_security()
