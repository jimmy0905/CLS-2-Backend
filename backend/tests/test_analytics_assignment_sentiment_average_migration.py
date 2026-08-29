from __future__ import annotations

import importlib.util
from pathlib import Path

MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "migrations"
    / "versions"
    / "2026_08_29_0015_add_assignment_sentiment_averages.py"
)


def _migration():
    spec = importlib.util.spec_from_file_location(
        "migration_0015_assignment_sentiment_avg", MIGRATION_PATH
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


def test_assignment_sentiment_average_migration_follows_assignment_matrix() -> None:
    migration = _migration()

    assert migration.revision == "0015_assignment_sentiment_avg"
    assert len(migration.revision) <= 32
    assert migration.down_revision == "0014_assignment_matrix_view"


def test_upgrade_adds_the_exact_assignment_score_mapping(monkeypatch) -> None:
    migration = _migration()
    recording_op = _RecordingOp()
    monkeypatch.setattr(migration, "op", recording_op)

    migration.upgrade()

    assert len(recording_op.statements) == 3
    for statement in recording_op.statements:
        assert "CREATE OR REPLACE VIEW analytics_survey_" in statement
        assert "WHEN 'POSITIVE' THEN 1" in statement
        assert "WHEN 'NEGATIVE' THEN 0" in statement
        assert "WHEN 'NEUTRAL' THEN -1" in statement
        assert "END::smallint AS assignment_sentiment_score" in statement


def test_score_average_formula_matches_the_published_mapping() -> None:
    score = {"POSITIVE": 1, "NEGATIVE": 0, "NEUTRAL": -1}
    values = ["POSITIVE", "POSITIVE", "NEGATIVE", "NEUTRAL"]

    assert sum(score[item] for item in values) / len(values) == 0.25


def test_downgrade_recreates_unscored_views_and_restores_security(monkeypatch) -> None:
    migration = _migration()
    recording_op = _RecordingOp()
    monkeypatch.setattr(migration, "op", recording_op)

    migration.downgrade()

    statements = "\n".join(recording_op.statements)
    assert "CREATE TEMPORARY TABLE _analytics_assignment_view_security" in statements
    for view in migration._ASSIGNMENT_VIEWS:
        assert f"DROP VIEW {view}" in statements
    assert "CREATE VIEW analytics_survey_topics" in statements
    assert "CREATE VIEW analytics_survey_departments" in statements
    assert "CREATE VIEW analytics_survey_keywords" in statements
    assert "GRANT %s ON TABLE public.%I TO %s%s" in statements
    assert "ALTER VIEW public.%I OWNER TO %I" in statements
