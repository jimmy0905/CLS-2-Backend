from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from models.User import User
from utils.database import get_db
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
import os
import logging
from dotenv import load_dotenv
from authlib.integrations.starlette_client import OAuth
from authlib.jose import jwt as authlib_jwt
import httpx
from config import DEPLOYMENT_PROFILE

logger = logging.getLogger(__name__)


load_dotenv()

# JWT settings
JWT_SECRET_KEY = os.environ["JWT_SECRET_KEY"]
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
JWT_ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", 30))

oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl=os.getenv("FASTAPI_ROOT_PATH", "/") + "/auth/token"
)

# Configure OAuth with proxy support using environment variables
def setup_proxy_environment():
    """Set up proxy environment variables if ASW_PROXY_URL is configured"""
    proxy_url = os.getenv("ASW_PROXY_URL")
    if proxy_url:
        # Set environment variables for proxy configuration
        # These will be used by underlying HTTP libraries
        os.environ["HTTP_PROXY"] = proxy_url
        os.environ["HTTPS_PROXY"] = proxy_url
        os.environ["http_proxy"] = proxy_url
        os.environ["https_proxy"] = proxy_url
        logger.info("Proxy configured")

# Set up proxy environment variables
setup_proxy_environment()

# Create OAuth client
oauth = OAuth()

oauth.register(
    name="azure",
    client_id=os.getenv("AZURE_CLIENT_ID"),
    client_secret=os.getenv("AZURE_CLIENT_SECRET"),
    authorize_url=f'https://login.microsoftonline.com/{os.getenv("AZURE_TENANT_ID")}/oauth2/v2.0/authorize',
    access_token_url=f'https://login.microsoftonline.com/{os.getenv("AZURE_TENANT_ID")}/oauth2/v2.0/token',
    jwks_uri=f'https://login.microsoftonline.com/{os.getenv("AZURE_TENANT_ID")}/discovery/v2.0/keys',
    client_kwargs={
        "scope": "openid email profile https://graph.microsoft.com/User.Read",
    },
)


def _jwt_audience(profile: str) -> str:
    return f"clsense-api:{profile}"


def _jwt_issuer(profile: str) -> str:
    return f"clsense-auth:{profile}"


async def get_current_user(
    token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)
) -> User:
    credentials_exception = HTTPException(
        status_code=401,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(
            token,
            JWT_SECRET_KEY,
            algorithms=[JWT_ALGORITHM],
            audience=_jwt_audience(DEPLOYMENT_PROFILE),
            issuer=_jwt_issuer(DEPLOYMENT_PROFILE),
        )
        user_id = payload.get("sub")
        if user_id is None or payload.get("profile") != DEPLOYMENT_PROFILE:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    user = (
        db.query(User)
        .filter(User.id == user_id, User.is_deleted.is_not(True))
        .first()
    )
    if user is None:
        raise credentials_exception
    return user


async def require_admin(current_user: User = Depends(get_current_user)) -> User:
    """Require the existing administrator role for governed catalog changes."""
    if bool(getattr(current_user, "is_deleted", False)) or current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator access is required",
        )
    if bool(getattr(current_user, "oauth_provider", None)):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator access requires a username/password account",
        )
    return current_user


def create_access_token(
    data: dict,
    expires_delta: Optional[timedelta] = timedelta(
        minutes=JWT_ACCESS_TOKEN_EXPIRE_MINUTES
    ),
):
    to_encode = data.copy()
    expire = datetime.utcnow() + (
        expires_delta or timedelta(minutes=JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode.update(
        {
            "exp": expire,
            "profile": DEPLOYMENT_PROFILE,
            "aud": _jwt_audience(DEPLOYMENT_PROFILE),
            "iss": _jwt_issuer(DEPLOYMENT_PROFILE),
        }
    )
    encoded_jwt = jwt.encode(to_encode, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)
    return encoded_jwt


async def verify_azure_token(token: str) -> Dict[str, Any]:
    """
    Verify Azure AD access token and return decoded claims
    """
    try:
        # Get Azure AD public keys for token verification
        tenant_id = os.getenv("AZURE_TENANT_ID")
        jwks_url = f"https://login.microsoftonline.com/{tenant_id}/discovery/v2.0/keys"

        # Fetch the JWKS using async httpx
        async with httpx.AsyncClient() as client:
            response = await client.get(jwks_url)
        response.raise_for_status()
        jwks = response.json()

        # Verify and decode the token
        claims = authlib_jwt.decode(token, jwks)

        # Validate temporal claims (exp, nbf, iat)
        claims.validate()

        # Verify the token is for our application
        client_id = os.getenv("AZURE_CLIENT_ID")
        if claims.get("aud") != client_id:
            raise HTTPException(status_code=401, detail="Invalid token")

        # Verify the issuer
        expected_issuer = f"https://login.microsoftonline.com/{tenant_id}/v2.0"
        if claims.get("iss") != expected_issuer:
            raise HTTPException(status_code=401, detail="Invalid token")

        return claims

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Token verification failed: %s", e)
        raise HTTPException(
            status_code=401, detail="Token verification failed"
        )


def extract_user_claims(token_data: Dict[str, Any]) -> Dict[str, str]:
    """
    Extract relevant user information from Azure AD token claims
    """
    return {
        "user_id": token_data.get("oid", ""),  # Object ID
        "email": token_data.get("email", token_data.get("preferred_username", "")),
        "name": token_data.get("name", ""),
        "given_name": token_data.get("given_name", ""),
        "family_name": token_data.get("family_name", ""),
        "tenant_id": token_data.get("tid", ""),
        "app_id": token_data.get("appid", token_data.get("aud", "")),
    }


async def create_or_update_user_from_azure(
    azure_user_data: Dict[str, Any], db: Session
) -> User:
    """
    Create or update a user in the database based on Azure AD data
    """
    email = azure_user_data.get("email") or azure_user_data.get("userPrincipalName", "")
    azure_id = azure_user_data.get("user_id") or azure_user_data.get("oid", "")

    if not email or not azure_id:
        raise HTTPException(
            status_code=400,
            detail="Missing required user data from identity provider"
        )

    logger.debug("Looking for user with azure_id: %s", azure_id)
    
    # Check if user already exists by oauth_provider and oauth_id
    user = (
        db.query(User)
        .filter(User.oauth_provider == "azure", User.oauth_id == azure_id)
        .first()
    )

    if not user:
        logger.info("Creating new Azure user")
        user = User(
            oauth_provider="azure",
            oauth_id=azure_id,
            username=email,
        )
        db.add(user)
        db.commit()
        db.refresh(user)

    # A migrate-before-first-user installation cannot seed user-owned analytics
    # defaults inside Alembic.  Complete that tightly scoped empty-catalog path
    # as soon as SSO has provided the first usable owner (and retry safely on
    # later logins if an earlier attempt was interrupted).
    from utils.database_migrations import bootstrap_single_metric_analytics_defaults

    bootstrap_single_metric_analytics_defaults()

    return user
