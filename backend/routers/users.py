from fastapi import APIRouter, Depends
from models.User import User
from utils.database import get_db
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List, Literal, Optional
from fastapi import HTTPException
from utils.security import get_current_user, require_admin

router = APIRouter(prefix="/users", tags=["users"])


class UserResponse(BaseModel):
    id: str
    username: str
    role: str
    created_at: str
    updated_at: str
    is_deleted: bool


@router.get("/")
async def get_users(
    db: Session = Depends(get_db), current_user: User = Depends(require_admin)
) -> List[UserResponse]:
    users = db.query(User).all()
    return [UserResponse.model_validate(user.to_dict()) for user in users]


class UpdateUserRequest(BaseModel):
    username: Optional[str] = None
    role: Optional[Literal["user", "admin"]] = None
    is_deleted: Optional[bool] = None


@router.put("/{user_id}")
async def update_user(
    user_id: str,
    update_user_request: UpdateUserRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    removing_admin = user.role == "admin" and (
        update_user_request.role == "user"
        or update_user_request.is_deleted is True
    )
    if removing_admin:
        active_admins = (
            db.query(User)
            .filter(User.role == "admin", User.is_deleted.is_not(True))
            .count()
        )
        if active_admins <= 1:
            raise HTTPException(status_code=409, detail="Cannot remove the last administrator")
    if update_user_request.username:
        user.username = update_user_request.username
    if update_user_request.role:
        user.role = update_user_request.role
    if update_user_request.is_deleted is not None:
        user.is_deleted = update_user_request.is_deleted
    db.commit()
    db.refresh(user)
    return {"message": f"User {user.username} updated successfully"}


class UpdateUserPasswordRequest(BaseModel):
    password: str


@router.put("/{user_id}/password")
async def update_user_password(
    user_id: str,
    update_user_password_request: UpdateUserPasswordRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role != "admin" and current_user.id != user_id:
        raise HTTPException(status_code=403, detail="Users may change only their own password")
    user = (
        db.query(User)
        .filter(User.id == user_id)
        .filter(User.is_deleted == False)
        .first()
    )
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.set_password(update_user_password_request.password)
    db.commit()
    db.refresh(user)
    return {"message": f"User {user.username} password updated successfully"}


@router.delete("/{user_id}")
async def delete_user(
    user_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    user = (
        db.query(User)
        .filter(User.id == user_id)
        .filter(User.is_deleted == False)
        .first()
    )
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.role == "admin":
        active_admins = (
            db.query(User)
            .filter(User.role == "admin", User.is_deleted.is_not(True))
            .count()
        )
        if active_admins <= 1:
            raise HTTPException(status_code=409, detail="Cannot delete the last administrator")
    user.is_deleted = True
    db.commit()
    db.refresh(user)
    return {"message": f"User {user.username} deleted successfully"}
