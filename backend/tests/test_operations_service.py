"""Tests for operational service behavior kept outside the FastAPI boundary."""

from __future__ import annotations

import sys

# ruff: noqa: E402
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from core.config import DEPLOYMENT_PROFILE
from features.operations.service import HealthService


class FakeSession:
    def __init__(self) -> None:
        self.statements: list[str] = []

    def execute(self, statement: object) -> None:
        self.statements.append(str(statement))


def test_health_service_preserves_the_existing_readiness_payload() -> None:
    session = FakeSession()

    assert HealthService(session).check() == {
        "status": "healthy",
        "profile": DEPLOYMENT_PROFILE,
    }
    assert session.statements == ["SELECT 1"]
