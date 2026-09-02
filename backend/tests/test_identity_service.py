"""Static bearer authentication tests."""

from __future__ import annotations

import asyncio
import base64
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import core.security as security
from core.config import parse_base64_32_byte_token_env


@pytest.fixture
def shared_token(monkeypatch):
    token = base64.b64encode(b"0123456789abcdef0123456789abcdef").decode()
    monkeypatch.setattr(security, "API_BEARER_TOKEN", token)
    monkeypatch.setattr(security, "DEPLOYMENT_PROFILE", "wtchk_cls")
    return token


def authenticate(token: str):
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    return asyncio.run(security.get_current_actor(credentials))


def test_valid_bearer_creates_a_fixed_immutable_context(shared_token) -> None:
    actor = authenticate(shared_token)

    assert actor.subject == "api-bearer:wtchk_cls"
    assert actor.label == "Static API bearer"
    assert actor.role == "admin"
    assert actor.profile == "wtchk_cls"
    assert actor.auth_method == "static_bearer"
    with pytest.raises(AttributeError):
        actor.role = "viewer"  # type: ignore[misc]


def test_wrong_bearer_and_missing_bearer_are_rejected(shared_token) -> None:
    with pytest.raises(HTTPException) as error:
        authenticate("not-the-shared-token")
    assert error.value.status_code == 401
    assert error.value.headers == {"WWW-Authenticate": "Bearer"}

    with pytest.raises(HTTPException) as error:
        asyncio.run(security.get_current_actor(None))
    assert error.value.status_code == 401
    assert error.value.headers == {"WWW-Authenticate": "Bearer"}


def test_token_parser_retains_a_valid_base64url_value(monkeypatch) -> None:
    token = base64.urlsafe_b64encode(b"0123456789abcdef0123456789abcdef").decode().rstrip("=")
    monkeypatch.setenv("TEST_API_BEARER_TOKEN", token)

    assert parse_base64_32_byte_token_env("TEST_API_BEARER_TOKEN") == token


@pytest.mark.parametrize("token", ["not-base64!", base64.b64encode(b"x" * 31).decode()])
def test_token_parser_rejects_invalid_token_values(monkeypatch, token) -> None:
    monkeypatch.setenv("TEST_API_BEARER_TOKEN", token)

    with pytest.raises(ValueError, match="TEST_API_BEARER_TOKEN"):
        parse_base64_32_byte_token_env("TEST_API_BEARER_TOKEN")
