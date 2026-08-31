"""Strict frontend-issued bearer-token authentication tests."""

from __future__ import annotations

import asyncio
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from jose import jwt

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import core.security as security


@pytest.fixture
def key_pair(monkeypatch):
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    public_pem = (
        private_key.public_key()
        .public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
    monkeypatch.setattr(security, "API_JWT_PUBLIC_KEY", public_pem)
    monkeypatch.setattr(security, "API_JWT_ISSUER", "clsense-frontend:wtchk_cls")
    monkeypatch.setattr(security, "API_JWT_AUDIENCE", "clsense-api:wtchk_cls")
    monkeypatch.setattr(security, "DEPLOYMENT_PROFILE", "wtchk_cls")
    monkeypatch.setattr(security, "API_JWT_CLOCK_SKEW_SECONDS", 30)
    return private_pem


def claims(**overrides):
    now = datetime.now(UTC)
    base = {
        "iss": "clsense-frontend:wtchk_cls",
        "aud": "clsense-api:wtchk_cls",
        "sub": "entra:00000000-0000-0000-0000-000000000001",
        "role": "viewer",
        "profile": "wtchk_cls",
        "auth_method": "entra",
        "label": "Viewer",
        "iat": now,
        "exp": now + timedelta(seconds=60),
        "jti": str(uuid.uuid4()),
    }
    base.update(overrides)
    return base


def authenticate(token: str):
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    return asyncio.run(security.get_current_actor(credentials))


def test_valid_token_creates_an_immutable_actor_without_a_database(key_pair) -> None:
    actor = authenticate(jwt.encode(claims(), key_pair, algorithm="RS256"))

    assert actor.subject.startswith("entra:")
    assert actor.role == "viewer"
    assert actor.profile == "wtchk_cls"
    with pytest.raises(AttributeError):
        actor.role = "admin"  # type: ignore[misc]


def test_valid_credentials_token_creates_an_admin_actor(key_pair) -> None:
    actor = authenticate(
        jwt.encode(
            claims(
                sub="admin:00000000-0000-0000-0000-000000000002",
                role="admin",
                auth_method="credentials",
            ),
            key_pair,
            algorithm="RS256",
        )
    )

    assert actor.role == "admin"
    assert actor.subject.startswith("admin:")


@pytest.mark.parametrize(
    "override",
    [
        {"iss": "clsense-frontend:other"},
        {"aud": "clsense-api:other"},
        {"profile": "other"},
        {"role": "superuser"},
        {"auth_method": "password"},
        {"sub": "legacy:00000000-0000-0000-0000-000000000001"},
        {"role": "admin", "auth_method": "entra"},
        {"jti": ""},
        {"jti": "not-a-uuid"},
        {
            "iat": datetime.now(UTC),
            "exp": datetime.now(UTC) + timedelta(seconds=61),
        },
        {
            "iat": datetime.now(UTC) + timedelta(seconds=60),
            "exp": datetime.now(UTC) + timedelta(seconds=120),
        },
        {"exp": datetime.now(UTC) - timedelta(seconds=31)},
    ],
)
def test_invalid_claims_are_rejected_with_a_bearer_challenge(
    key_pair, override
) -> None:
    token = jwt.encode(claims(**override), key_pair, algorithm="RS256")

    with pytest.raises(HTTPException) as error:
        authenticate(token)

    assert error.value.status_code == 401
    assert error.value.headers == {"WWW-Authenticate": "Bearer"}


@pytest.mark.parametrize(
    "claim_name",
    ["iss", "aud", "sub", "role", "profile", "auth_method", "iat", "exp", "jti"],
)
def test_missing_required_claims_are_rejected(key_pair, claim_name) -> None:
    payload = claims()
    payload.pop(claim_name)
    token = jwt.encode(payload, key_pair, algorithm="RS256")

    with pytest.raises(HTTPException) as error:
        authenticate(token)

    assert error.value.status_code == 401
    assert error.value.headers == {"WWW-Authenticate": "Bearer"}


def test_clock_skew_accepts_a_token_expired_less_than_thirty_seconds_ago(
    key_pair,
) -> None:
    token = jwt.encode(
        claims(
            iat=datetime.now(UTC) - timedelta(seconds=70),
            exp=datetime.now(UTC) - timedelta(seconds=10),
        ),
        key_pair,
        algorithm="RS256",
    )

    assert authenticate(token).role == "viewer"


def test_wrong_algorithm_and_missing_bearer_are_rejected(key_pair) -> None:
    wrong_algorithm = jwt.encode(claims(), "shared-secret", algorithm="HS256")
    with pytest.raises(HTTPException):
        authenticate(wrong_algorithm)
    wrong_private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    wrong_private_pem = wrong_private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    wrong_signature = jwt.encode(claims(), wrong_private_pem, algorithm="RS256")
    with pytest.raises(HTTPException):
        authenticate(wrong_signature)
    with pytest.raises(HTTPException) as error:
        asyncio.run(security.get_current_actor(None))
    assert error.value.status_code == 401
