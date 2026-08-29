"""Public request and response contracts for identity endpoints."""

from typing import Literal

from pydantic import BaseModel


class UserResponse(BaseModel):
    id: str
    username: str
    role: str
    created_at: str
    updated_at: str
    is_deleted: bool


class UpdateUserRequest(BaseModel):
    username: str | None = None
    role: Literal["user", "admin"] | None = None
    is_deleted: bool | None = None


class UpdateUserPasswordRequest(BaseModel):
    password: str
