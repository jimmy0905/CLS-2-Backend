"""Compatibility exports for frontend-issued bearer actor authentication."""

from core.security import (
    ActorContext,
    get_current_actor,
    require_admin,
)

__all__ = ["ActorContext", "get_current_actor", "require_admin"]
