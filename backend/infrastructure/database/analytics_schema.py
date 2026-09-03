"""Install SQL-only analytics objects omitted by SQLAlchemy ``create_all``.

The canonical table schema lives in SQLAlchemy metadata, while Cube's helper
functions and reporting views are Alembic-managed SQL objects. A fresh database
therefore needs both pieces before it can safely be stamped at the current
revision. The same repair is exposed to Alembic so databases created by the old
fresh-install path can heal without being dropped.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlalchemy.engine import Connection


MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations" / "versions"

_REQUIRED_OBJECTS_SQL = """
SELECT
    to_regclass('public.analytics_survey_facts') IS NOT NULL
    AND to_regclass('public.analytics_survey_topics') IS NOT NULL
    AND to_regclass('public.analytics_survey_departments') IS NOT NULL
    AND to_regclass('public.analytics_survey_keywords') IS NOT NULL
    AND to_regclass('public.analytics_survey_assignments') IS NOT NULL
    AND to_regprocedure('public.analytics_normalize_raw_row(json)') IS NOT NULL
    AND to_regprocedure('public.analytics_raw_value(json,text)') IS NOT NULL
    AND to_regprocedure('public.analytics_raw_number(json,text)') IS NOT NULL
    AND to_regprocedure('public.analytics_raw_number_invalid(json,text)') IS NOT NULL
    AND to_regprocedure('public.analytics_raw_boolean(json,text)') IS NOT NULL
    AND to_regprocedure('public.analytics_raw_date(json,text)') IS NOT NULL
    AND to_regprocedure('public.analytics_raw_time(json,text)') IS NOT NULL
    AND to_regprocedure('public.analytics_raw_timestamp(json,text)') IS NOT NULL
"""

_VIEW_NAMES = (
    "analytics_survey_assignments",
    "analytics_survey_topics",
    "analytics_survey_departments",
    "analytics_survey_keywords",
    "analytics_survey_facts",
)

_FUNCTION_SIGNATURES = (
    "analytics_raw_timestamp(json, text)",
    "analytics_raw_time(json, text)",
    "analytics_raw_date(json, text)",
    "analytics_raw_boolean(json, text)",
    "analytics_raw_number_invalid(json, text)",
    "analytics_raw_number(json, text)",
    "analytics_raw_value(json, text)",
    "analytics_normalize_raw_row(json)",
)


def _load_revision(filename: str, module_name: str) -> ModuleType:
    path = MIGRATIONS_DIR / filename
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load analytics migration helper: {path.name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def repair_analytics_schema(
    connection: Connection,
    *,
    operations: Any | None = None,
) -> bool:
    """Create the current analytics functions/views when any are absent.

    Returns ``True`` when a repair was applied. The operation is transactional
    on PostgreSQL and intentionally leaves a complete existing schema alone so
    its grants and active readers are not disturbed.
    """

    if bool(connection.execute(text(_REQUIRED_OBJECTS_SQL)).scalar()):
        return False

    ops = operations or Operations(MigrationContext.configure(connection))
    for view_name in _VIEW_NAMES:
        ops.execute(f"DROP VIEW IF EXISTS {view_name}")
    for signature in _FUNCTION_SIGNATURES:
        ops.execute(f"DROP FUNCTION IF EXISTS {signature}")

    semantic_catalog = _load_revision(
        "2026_08_25_0008_0009_add_cube_semantic_catalog.py",
        "analytics_semantic_catalog_revision",
    )
    assignment_matrix = _load_revision(
        "2026_08_28_0014_add_assignment_matrix_view.py",
        "analytics_assignment_matrix_revision",
    )
    assignment_scores = _load_revision(
        "2026_08_29_0015_add_assignment_sentiment_averages.py",
        "analytics_assignment_scores_revision",
    )

    # These migration helpers use their module-local ``op`` binding. Point it
    # at the caller's Operations object so the same reviewed DDL remains the
    # single source for upgraded and fresh databases.
    semantic_catalog.op = ops
    assignment_matrix.op = ops
    assignment_scores.op = ops
    semantic_catalog._create_raw_json_helpers()
    semantic_catalog._create_reporting_views()
    assignment_matrix.upgrade()
    assignment_scores._create_scored_assignment_views()
    return True
