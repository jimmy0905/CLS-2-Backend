from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.responses import RedirectResponse
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from models.User import User
from utils.database import get_db
from utils.security import (
    create_access_token,
    get_current_user,
    verify_azure_token,
    extract_user_claims,
    create_or_update_user_from_azure,
)
from pydantic import BaseModel
import os
from utils.security import oauth

router = APIRouter(prefix="/auth", tags=["auth"])
AZURE_REDIRECT_URI = os.getenv("AZURE_REDIRECT_URI")
FRONTEND_URL = os.getenv("FRONTEND_URL")

@router.get("/azure/login")
async def azure_login(request: Request):
    return await oauth.azure.authorize_redirect(request, AZURE_REDIRECT_URI)


@router.get("/azure/callback")
async def azure_callback(request: Request, db: Session = Depends(get_db)):
    try:
        # Get token from Azure AD
        token_response = await oauth.azure.authorize_access_token(request)
        access_token = token_response.get("access_token")
        id_token = token_response.get("id_token")
        if not access_token:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No access token received",
            )

        # Method 1: Verify the ID token (contains user claims)
        user_data = {}
        print(id_token)
        if id_token:
            try:
                user_claims = await verify_azure_token(id_token)
                user_data = extract_user_claims(user_claims)
            except Exception as e:
                print(f"ID token verification failed: {e}")
        print(user_data)
        # Create or update user in your database
        user = await create_or_update_user_from_azure(user_data, db)

        # Create your application's JWT token
        app_access_token = create_access_token(
            data={
                "sub": user.id,
                "oauth_provider": user.oauth_provider,
                "oauth_id": user.oauth_id,
                "role": user.role,
            }
        )
        print(f"{FRONTEND_URL}/auth/azure/callback?access_token={app_access_token}")
        return RedirectResponse(
            url=f"{FRONTEND_URL}/auth/azure/callback?access_token={app_access_token}"
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Authentication failed: {str(e)}",
        )


@router.post("/token")
async def token(
    form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)
):
    user = (
        db.query(User)
        .filter(User.username == form_data.username)
        .filter(User.oauth_provider == None)
        .filter(User.oauth_id == None)
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
            "sub": user.id,
            "role": user.role,
            "oauth_provider": user.oauth_provider,
            "oauth_id": user.oauth_id,
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
            "sub": user.id,
            "oauth_provider": user.oauth_provider,
            "oauth_id": user.oauth_id,
            "role": user.role,
        },
    )
    return {"access_token": access_token, "token_type": "bearer"}
