"""grant Cube readers access to the assignment combination view

Revision ID: 0017_assignment_view_grants
Revises: 0016_remove_analytics_rendering
Create Date: 2026-08-30 11:30:00.000000

The assignment combination view was added after the dedicated per-profile Cube
roles had already been provisioned. PostgreSQL does not copy grants from a
source view to a newly created view, so those roles could query the four older
analytics grains but received ``permission denied`` for this one.

Copying only the direct, non-grantable SELECT grants held by locked-down login
roles on ``analytics_survey_facts`` keeps the repair profile-agnostic. PUBLIC,
group roles, owners, and privileged roles are deliberately excluded.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0017_assignment_view_grants"
down_revision: str | Sequence[str] | None = "0016_remove_analytics_rendering"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        DO $grant_assignment_view_access$
        DECLARE
            grant_record record;
        BEGIN
            FOR grant_record IN
                SELECT DISTINCT reader.rolname
                FROM pg_class relation
                CROSS JOIN LATERAL aclexplode(relation.relacl) acl
                JOIN pg_roles reader ON reader.oid = acl.grantee
                WHERE relation.relnamespace = 'public'::regnamespace
                  AND relation.relkind IN ('r', 'p', 'v', 'm')
                  AND relation.relname = 'analytics_survey_facts'
                  AND acl.privilege_type = 'SELECT'
                  AND NOT acl.is_grantable
                  AND acl.grantee <> relation.relowner
                  AND reader.rolcanlogin
                  AND NOT reader.rolsuper
                  AND NOT reader.rolcreatedb
                  AND NOT reader.rolcreaterole
                  AND NOT reader.rolreplication
                  AND NOT reader.rolbypassrls
                  AND 'default_transaction_read_only=on' = ANY(reader.rolconfig)
            LOOP
                EXECUTE format(
                    'GRANT SELECT ON TABLE public.analytics_survey_assignments TO %I',
                    grant_record.rolname
                );
            END LOOP;
        END
        $grant_assignment_view_access$
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $revoke_assignment_view_access$
        DECLARE
            grant_record record;
        BEGIN
            FOR grant_record IN
                SELECT DISTINCT reader.rolname
                FROM pg_class facts
                CROSS JOIN LATERAL aclexplode(facts.relacl) facts_acl
                JOIN pg_roles reader ON reader.oid = facts_acl.grantee
                JOIN pg_class assignment_view
                  ON assignment_view.relnamespace = facts.relnamespace
                 AND assignment_view.relname = 'analytics_survey_assignments'
                CROSS JOIN LATERAL aclexplode(assignment_view.relacl) assignment_acl
                WHERE facts.relnamespace = 'public'::regnamespace
                  AND facts.relname = 'analytics_survey_facts'
                  AND facts_acl.privilege_type = 'SELECT'
                  AND assignment_acl.privilege_type = 'SELECT'
                  AND facts_acl.grantee = assignment_acl.grantee
                  AND assignment_acl.grantee <> assignment_view.relowner
                  AND NOT facts_acl.is_grantable
                  AND reader.rolcanlogin
                  AND NOT reader.rolsuper
                  AND NOT reader.rolcreatedb
                  AND NOT reader.rolcreaterole
                  AND NOT reader.rolreplication
                  AND NOT reader.rolbypassrls
                  AND 'default_transaction_read_only=on' = ANY(reader.rolconfig)
            LOOP
                EXECUTE format(
                    'REVOKE SELECT ON TABLE public.analytics_survey_assignments '
                    || 'FROM %I',
                    grant_record.rolname
                );
            END LOOP;
        END
        $revoke_assignment_view_access$
        """
    )
