from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from models.User import User
from utils.database import get_db
from utils.security import create_access_token, get_current_user
from pydantic import BaseModel

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/token")
async def token(
    form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)
):
    user = (
        db.query(User)
        .filter(User.username == form_data.username)
        .filter(User.is_deleted == False)
        .first()
    )
    # Check if user exists and password is correct
    if not user or not user.check_password(form_data.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
        )

    # Generate access token after successful login
    access_token = create_access_token(
        data={
            "sub": user.username,
            "user_id": user.id,
            "role": user.role,
        },
    )

    return {"access_token": access_token, "token_type": "bearer"}


class RegisterRequest(BaseModel):
    username: str
    password: str
    role: str


@router.post("/register")
async def register(request: RegisterRequest, db: Session = Depends(get_db)):
    # Check if user already exists
    if db.query(User).filter(User.username == request.username).first():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User already exists",
        )

    user = User(username=request.username, role=request.role)
    user.set_password(request.password)
    db.add(user)
    db.commit()
    return {"message": "User registered successfully"}


@router.post("/renew-token")
async def renew_token(
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
):
    user = db.query(User).filter(User.username == current_user.username).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )
    access_token = create_access_token(
        data={
            "sub": user.username,
            "user_id": user.id,
            "role": user.role,
        },
    )
    return {"access_token": access_token, "token_type": "bearer"}
