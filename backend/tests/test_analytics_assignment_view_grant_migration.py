from __future__ import annotations

import importlib.util
from pathlib import Path

MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "migrations"
    / "versions"
    / "2026_08_30_0017_grant_assignment_view_access.py"
)


def _migration():
    spec = importlib.util.spec_from_file_location(
        "migration_0017_assignment_view_grants", MIGRATION_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _RecordingOp:
    def __init__(self) -> None:
        self.statements: list[str] = []

    def execute(self, statement: str) -> None:
        self.statements.append(statement)


def test_assignment_view_grant_migration_follows_current_head() -> None:
    migration = _migration()

    assert migration.revision == "0017_assignment_view_grants"
    assert len(migration.revision) <= 32
    assert migration.down_revision == "0016_remove_analytics_rendering"


def test_upgrade_copies_only_explicit_select_grants_from_governed_facts(
    monkeypatch,
) -> None:
    migration = _migration()
    recording_op = _RecordingOp()
    monkeypatch.setattr(migration, "op", recording_op)

    migration.upgrade()

    assert len(recording_op.statements) == 1
    statement = recording_op.statements[0]
    assert "relation.relname = 'analytics_survey_facts'" in statement
    assert "acl.privilege_type = 'SELECT'" in statement
    assert "NOT acl.is_grantable" in statement
    assert "acl.grantee <> relation.relowner" in statement
    assert "reader.rolcanlogin" in statement
    assert "NOT reader.rolsuper" in statement
    assert "'default_transaction_read_only=on' = ANY(reader.rolconfig)" in statement
    assert (
        "GRANT SELECT ON TABLE public.analytics_survey_assignments TO %I"
        in statement
    )
    assert "PUBLIC" not in statement
    assert "WITH GRANT OPTION" not in statement


def test_downgrade_revokes_only_grantees_shared_with_governed_facts(
    monkeypatch,
) -> None:
    migration = _migration()
    recording_op = _RecordingOp()
    monkeypatch.setattr(migration, "op", recording_op)

    migration.downgrade()

    assert len(recording_op.statements) == 1
    statement = recording_op.statements[0]
    assert "facts.relname = 'analytics_survey_facts'" in statement
    assert "assignment_view.relname = 'analytics_survey_assignments'" in statement
    assert "facts_acl.grantee = assignment_acl.grantee" in statement
    assert "NOT facts_acl.is_grantable" in statement
    assert "reader.rolcanlogin" in statement
    assert "REVOKE SELECT ON TABLE public.analytics_survey_assignments" in statement
    assert "|| 'FROM %I'" in statement
