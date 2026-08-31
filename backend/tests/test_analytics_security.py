from __future__ import annotations

import asyncio
from dataclasses import FrozenInstanceError

import pytest
from fastapi import HTTPException

from core.security import ActorContext, require_admin


def actor(role: str) -> ActorContext:
    return ActorContext(
        subject="admin:00000000-0000-0000-0000-000000000001",
        label="operator",
        role=role,  # type: ignore[arg-type]
        profile="wtchk_cls",
        auth_method="credentials",
    )


def test_signed_admin_role_is_authoritative() -> None:
    administrator = actor("admin")
    assert asyncio.run(require_admin(administrator)) is administrator


def test_viewer_role_cannot_use_admin_endpoints() -> None:
    with pytest.raises(HTTPException) as error:
        asyncio.run(require_admin(actor("viewer")))
    assert error.value.status_code == 403


def test_actor_context_cannot_be_mutated_after_verification() -> None:
    viewer = actor("viewer")
    with pytest.raises(FrozenInstanceError):
        viewer.role = "admin"  # type: ignore[misc]
