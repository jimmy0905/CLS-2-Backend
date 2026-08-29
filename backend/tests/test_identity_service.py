"""Golden mappings and transaction behavior for the identity feature layer."""

# ruff: noqa: E402

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from core.errors import ConflictError
from features.identity.mapper import user_to_dict
from features.identity.service.users import UserService
from infrastructure.database.dbo.User import User


class FakeSession:
    def __init__(self) -> None:
        self.commit_count = 0

    def commit(self) -> None:
        self.commit_count += 1


class FakeUserRepository:
    def __init__(self, user: User, active_admins: int = 2) -> None:
        self.user = user
        self.active_admins = active_admins
        self.refreshed: list[User] = []

    def get(self, user_id: str) -> User | None:
        return self.user if user_id == self.user.id else None

    def get_active(self, user_id: str) -> User | None:
        return self.get(user_id) if not self.user.is_deleted else None

    def active_admin_count(self) -> int:
        return self.active_admins

    def refresh(self, user: User) -> None:
        self.refreshed.append(user)


def make_user() -> User:
    user = User(username="admin", role="admin")
    user.id = "user-1"
    user.created_at = datetime(2025, 1, 2, 3, 4, 5, tzinfo=UTC)
    user.updated_at = datetime(2025, 1, 3, 4, 5, 6, tzinfo=UTC)
    user.is_deleted = False
    return user


def test_user_mapper_preserves_the_former_dbo_serialization_contract() -> None:
    user = make_user()

    assert user_to_dict(user) == {
        "id": "user-1",
        "username": "admin",
        "role": "admin",
        "oauth_provider": None,
        "created_at": "2025-01-02T03:04:05+00:00",
        "updated_at": "2025-01-03T04:05:06+00:00",
        "is_deleted": False,
    }


def test_user_service_updates_with_the_existing_transaction_timing() -> None:
    session = FakeSession()
    service = UserService(session)  # type: ignore[arg-type]
    repository = FakeUserRepository(make_user())
    service._repository = repository  # type: ignore[assignment]

    message = service.update(
        "user-1", username="updated-admin", role=None, is_deleted=None
    )

    assert message == "User updated-admin updated successfully"
    assert repository.user.username == "updated-admin"
    assert session.commit_count == 1
    assert repository.refreshed == [repository.user]


def test_user_service_rejects_removing_the_last_administrator_before_commit() -> None:
    session = FakeSession()
    service = UserService(session)  # type: ignore[arg-type]
    service._repository = FakeUserRepository(make_user(), active_admins=1)  # type: ignore[assignment]

    with pytest.raises(ConflictError, match="Cannot remove the last administrator"):
        service.update("user-1", username=None, role="user", is_deleted=None)

    assert session.commit_count == 0
