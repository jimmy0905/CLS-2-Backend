"""Static bearer authentication for protected API routes."""

from __future__ import annotations

import hmac
from dataclasses import dataclass
from typing import Annotated, Literal

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from core.config import (
    API_BEARER_TOKEN,
    DEPLOYMENT_PROFILE,
)

ActorRole = Literal["viewer", "admin"]
bearer_scheme = HTTPBearer(auto_error=False, scheme_name="StaticBearer")


@dataclass(frozen=True, slots=True)
class ActorContext:
    """Fixed system attribution retained for legacy audit/export consumers.

    This is never populated from request headers or a user session. Every
    caller with the profile's static bearer receives this same context.
    """

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


async def get_current_actor(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> ActorContext:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise _unauthorized()
    if not API_BEARER_TOKEN or not hmac.compare_digest(
        credentials.credentials.encode(), API_BEARER_TOKEN.encode()
    ):
        raise _unauthorized()

    return ActorContext(
        subject=f"api-bearer:{DEPLOYMENT_PROFILE}",
        label="Static API bearer",
        # Analytics currently uses role-shaped catalog and export fields. This
        # fixed compatibility value makes those paths bearer-only rather than
        # deriving permissions from a user-supplied role.
        role="admin",
        profile=DEPLOYMENT_PROFILE,
        auth_method="static_bearer",
    )


async def require_admin(
    actor: Annotated[ActorContext, Depends(get_current_actor)],
) -> ActorContext:
    """Compatibility dependency: admin routes now require only the bearer."""

    return actor
