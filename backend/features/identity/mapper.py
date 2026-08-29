"""Mappings between identity persistence objects and public DTO inputs."""

from typing import Any

from core.time import utc_isoformat
from infrastructure.database.dbo.User import User


def user_to_dict(user: User) -> dict[str, Any]:
    """Preserve the historical ``User.to_dict`` representation."""

    return {
        "id": user.id,
        "username": user.username,
        "role": user.role,
        "oauth_provider": user.oauth_provider,
        "created_at": utc_isoformat(user.created_at),
        "updated_at": utc_isoformat(user.updated_at),
        "is_deleted": user.is_deleted,
    }
