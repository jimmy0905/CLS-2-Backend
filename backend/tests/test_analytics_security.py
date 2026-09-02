from __future__ import annotations

import asyncio
from dataclasses import FrozenInstanceError

import pytest

from core.security import ActorContext, require_admin


def actor(role: str) -> ActorContext:
    return ActorContext(
        subject="admin:00000000-0000-0000-0000-000000000001",
        label="operator",
        role=role,  # type: ignore[arg-type]
        profile="wtchk_cls",
        auth_method="credentials",
    )


def test_legacy_admin_dependency_accepts_the_static_context() -> None:
    administrator = actor("admin")
    assert asyncio.run(require_admin(administrator)) is administrator


def test_legacy_admin_dependency_has_no_role_gate() -> None:
    assert asyncio.run(require_admin(actor("viewer"))) is not None


def test_actor_context_cannot_be_mutated_after_verification() -> None:
    viewer = actor("viewer")
    with pytest.raises(FrozenInstanceError):
        viewer.role = "admin"  # type: ignore[misc]
