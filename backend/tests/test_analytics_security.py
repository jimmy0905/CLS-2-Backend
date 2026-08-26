import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utils import security
from utils.security import create_access_token, get_current_user, require_admin
from routers import users
from routers.users import UpdateUserPasswordRequest, UpdateUserRequest, update_user_password
from utils.database import get_db


def test_require_admin_returns_an_admin_user() -> None:
    user = SimpleNamespace(role="admin", is_deleted=False, oauth_provider=None)

    assert asyncio.run(require_admin(user)) is user


def test_require_admin_rejects_a_viewer() -> None:
    with pytest.raises(HTTPException) as error:
        asyncio.run(require_admin(SimpleNamespace(role="user")))

    assert error.value.status_code == 403
    assert error.value.detail == "Administrator access is required"


def test_require_admin_rejects_an_sso_admin() -> None:
    with pytest.raises(HTTPException, match="username/password"):
        asyncio.run(
            require_admin(
                SimpleNamespace(
                    role="admin", is_deleted=False, oauth_provider="microsoft"
                )
            )
        )

def test_require_admin_rejects_a_soft_deleted_admin() -> None:
    with pytest.raises(HTTPException) as error:
        asyncio.run(require_admin(SimpleNamespace(role="admin", is_deleted=True)))

    assert error.value.status_code == 403


def test_user_roles_are_a_closed_governance_enum() -> None:
    with pytest.raises(ValidationError):
        UpdateUserRequest(role="superuser")


def test_viewer_cannot_reset_another_users_password() -> None:
    with pytest.raises(HTTPException) as error:
        asyncio.run(
            update_user_password(
                "other-user",
                UpdateUserPasswordRequest(password="replacement"),
                db=None,
                current_user=SimpleNamespace(id="viewer", role="user"),
            )
        )

    assert error.value.status_code == 403


def test_human_access_tokens_are_rejected_by_another_bu_profile(monkeypatch) -> None:
    monkeypatch.setattr(security, "DEPLOYMENT_PROFILE", "wtchk_cls")
    token = create_access_token({"sub": "shared-user-id"})
    monkeypatch.setattr(security, "DEPLOYMENT_PROFILE", "wtchk_ecls")

    with pytest.raises(HTTPException) as error:
        asyncio.run(get_current_user(token=token, db=None))

    assert error.value.status_code == 401


def test_viewer_cannot_self_promote_through_user_admin_api() -> None:
    app = FastAPI()
    app.include_router(users.router)
    viewer = SimpleNamespace(id="viewer", role="user", is_deleted=False)
    app.dependency_overrides[get_current_user] = lambda: viewer
    app.dependency_overrides[get_db] = lambda: None

    response = TestClient(app).put("/users/viewer", json={"role": "admin"})

    assert response.status_code == 403
