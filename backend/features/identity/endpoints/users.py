from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from features.identity.dto import (
    UpdateUserPasswordRequest,
    UpdateUserRequest,
    UserResponse,
)
from features.identity.mapper import user_to_dict
from features.identity.service.security import get_current_user, require_admin
from features.identity.service.users import user_service
from infrastructure.database.dbo.User import User
from infrastructure.database.session import get_db

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/")
async def get_users(
    db: Session = Depends(get_db), current_user: User = Depends(require_admin)
) -> List[UserResponse]:
    users = user_service(db).list()
    return [UserResponse.model_validate(user_to_dict(user)) for user in users]


@router.put("/{user_id}")
async def update_user(
    user_id: str,
    update_user_request: UpdateUserRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    return {
        "message": user_service(db).update(
            user_id,
            username=update_user_request.username,
            role=update_user_request.role,
            is_deleted=update_user_request.is_deleted,
        )
    }


@router.put("/{user_id}/password")
async def update_user_password(
    user_id: str,
    update_user_password_request: UpdateUserPasswordRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role != "admin" and current_user.id != user_id:
        raise HTTPException(status_code=403, detail="Users may change only their own password")
    return {
        "message": user_service(db).change_password(
            user_id, update_user_password_request.password
        )
    }


@router.delete("/{user_id}")
async def delete_user(
    user_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    return {"message": user_service(db).delete(user_id)}
