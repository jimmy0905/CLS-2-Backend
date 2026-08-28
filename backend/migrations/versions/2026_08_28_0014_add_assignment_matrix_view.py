"""add the survey_assignments reporting grain for cross-assignment queries

Revision ID: 0014_assignment_matrix_view
Revises: 0013_goal_first_analytics
Create Date: 2026-08-28 12:00:00.000000

The four existing grains each expose one assignment family, so a keyword can
never be crossed with a department.  This grain is the combination of all three
assignment families for one response, which makes those cross tabulations
expressible without joining cubes.

Every row is one (response, keyword, department, topic) combination, so a
response contributes the product of its assignment counts.  Only measures that
deduplicate on ``distinct_survey_id`` are meaningful here; response-level
averages such as CLS would be weighted by that product and are deliberately
absent from this grain's catalog.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op


revision: str = "0014_assignment_matrix_view"
down_revision: Union[str, Sequence[str], None] = "0013_goal_first_analytics"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("DROP VIEW IF EXISTS analytics_survey_assignments")
    op.execute(
        """
        CREATE VIEW analytics_survey_assignments AS
        SELECT
            facts.id::text
                || ':' || COALESCE(keyword_assignment.id, 0)::text
                || ':' || COALESCE(department_assignment.id, 0)::text
                || ':' || COALESCE(topic_assignment.id, 0)::text
                AS combination_id,
            facts.*,
            keyword_assignment.keyword_id,
            keyword.keyword,
            keyword_assignment.sentiment::text AS keyword_sentiment,
            department_assignment.department_id,
            department.name AS department_name,
            department_assignment.sentiment::text AS department_sentiment,
            topic_assignment.topic_id,
            topic.topic,
            topic_assignment.sentiment::text AS topic_assignment_sentiment,
            1::bigint AS combination_count,
            facts.id AS distinct_survey_id
        FROM analytics_survey_facts facts
        LEFT JOIN survey_keywords keyword_assignment
            ON keyword_assignment.survey_id = facts.id
        LEFT JOIN keywords keyword
            ON keyword.id = keyword_assignment.keyword_id
        LEFT JOIN survey_departments department_assignment
            ON department_assignment.survey_id = facts.id
        LEFT JOIN departments department
            ON department.id = department_assignment.department_id
        LEFT JOIN survey_topics topic_assignment
            ON topic_assignment.survey_id = facts.id
        LEFT JOIN topics topic
            ON topic.id = topic_assignment.topic_id
        """
    )


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS analytics_survey_assignments")
