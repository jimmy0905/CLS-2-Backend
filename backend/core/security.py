"""Bearer-only authentication for frontend-issued actor tokens."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Annotated, Literal

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from core.config import (
    API_JWT_AUDIENCE,
    API_JWT_CLOCK_SKEW_SECONDS,
    API_JWT_ISSUER,
    API_JWT_PUBLIC_KEY,
    DEPLOYMENT_PROFILE,
)

ActorRole = Literal["viewer", "admin"]
bearer_scheme = HTTPBearer(auto_error=False, scheme_name="FrontendBearer")


@dataclass(frozen=True, slots=True)
class ActorContext:
    """Immutable identity snapshot derived exclusively from a signed JWT."""

    subject: str
    label: str
    role: ActorRole
    profile: str
    auth_method: str

    @property
    def id(self) -> str:
        """Compatibility alias while endpoint internals move to subject naming."""

        return self.subject


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )


def _valid_actor_claims(subject: str, role: str, auth_method: str) -> bool:
    expected_prefix = "admin:" if role == "admin" else "entra:"
    expected_method = "credentials" if role == "admin" else "entra"
    if auth_method != expected_method or not subject.startswith(expected_prefix):
        return False
    try:
        uuid.UUID(subject.removeprefix(expected_prefix))
    except (ValueError, AttributeError):
        return False
    return True


async def get_current_actor(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> ActorContext:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise _unauthorized()
    if not API_JWT_PUBLIC_KEY:
        raise _unauthorized()

    try:
        unverified_header = jwt.get_unverified_header(credentials.credentials)
        if unverified_header.get("alg") != "RS256":
            raise _unauthorized()
        claims = jwt.decode(
            credentials.credentials,
            API_JWT_PUBLIC_KEY,
            algorithms=["RS256"],
            audience=API_JWT_AUDIENCE,
            issuer=API_JWT_ISSUER,
            options={
                "require_aud": True,
                "require_exp": True,
                "require_iat": True,
                "require_iss": True,
                "require_sub": True,
                "verify_aud": True,
                "verify_exp": True,
                "verify_iat": True,
                "verify_iss": True,
                "leeway": API_JWT_CLOCK_SKEW_SECONDS,
            },
        )
        subject = claims.get("sub")
        profile = claims.get("profile")
        role = claims.get("role")
        auth_method = claims.get("auth_method")
        jti = claims.get("jti")
        issued_at = claims.get("iat")
        expires_at = claims.get("exp")
        if (
            not isinstance(subject, str)
            or not subject
            or profile != DEPLOYMENT_PROFILE
            or role not in {"viewer", "admin"}
            or not isinstance(auth_method, str)
            or not _valid_actor_claims(subject, role, auth_method)
            or not isinstance(jti, str)
            or not jti
            or not isinstance(issued_at, (int, float))
            or isinstance(issued_at, bool)
            or not isinstance(expires_at, (int, float))
            or isinstance(expires_at, bool)
            or expires_at <= issued_at
            or expires_at - issued_at > 60
            or issued_at > time.time() + API_JWT_CLOCK_SKEW_SECONDS
        ):
            raise _unauthorized()
        try:
            uuid.UUID(jti)
        except ValueError as error:
            raise _unauthorized() from error
        label = claims.get("label")
        if not isinstance(label, str) or not label.strip():
            label = subject
    except HTTPException:
        raise
    except (JWTError, KeyError, TypeError, ValueError) as error:
        raise _unauthorized() from error

    return ActorContext(
        subject=subject,
        label=label[:255],
        role=role,
        profile=profile,
        auth_method=auth_method[:32],
    )


async def require_admin(
    actor: Annotated[ActorContext, Depends(get_current_actor)],
) -> ActorContext:
    if actor.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator access is required",
        )
    return actor
