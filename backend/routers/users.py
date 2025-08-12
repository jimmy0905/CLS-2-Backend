from fastapi import APIRouter, Depends
from models.User import User
from models.db_config import get_db
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime
from fastapi import HTTPException
from utils.security import get_current_user

router = APIRouter(prefix="/users", tags=["users"])


class UserResponse(BaseModel):
    id: str
    username: str
    role: str
    created_at: datetime
    updated_at: datetime
    is_deleted: bool


@router.get("/")
async def get_users(
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
) -> List[UserResponse]:
    users = db.query(User).all()
    return users


class UpdateUserRequest(BaseModel):
    username: Optional[str] = None
    role: Optional[str] = None
    is_deleted: Optional[bool] = None


@router.put("/{user_id}")
async def update_user(
    user_id: str,
    update_user_request: UpdateUserRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
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
    current_user: User = Depends(get_current_user),
):
    user = (
        db.query(User)
        .filter(User.id == user_id)
        .filter(User.is_deleted == False)
        .first()
    )
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.is_deleted = True
    db.commit()
    db.refresh(user)
    return {"message": f"User {user.username} deleted successfully"}
