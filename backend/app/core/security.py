"""Authentication, Argon2 password hashing, JWT management, and security dependencies."""
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional
import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError, InvalidHashError
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.config import settings
from app.db.session import get_db
from app.models.sql_models import User

# Argon2 Password Hasher singleton
_password_hasher = PasswordHasher()

# Bearer token extractor
http_bearer = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    """Hash a plaintext password using Argon2."""
    return _password_hasher.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify plaintext password against an Argon2 hash."""
    try:
        return _password_hasher.verify(hashed_password, plain_password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def create_access_token(user_id: str, role: str, expires_delta: Optional[timedelta] = None) -> str:
    """Generate a signed short-lived JWT access token."""
    now = datetime.now(timezone.utc)
    exp = now + (expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_MINUTES))
    payload = {
        "sub": str(user_id),
        "role": role,
        "type": "access",
        "iat": now,
        "exp": exp,
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY.get_secret_value(), algorithm="HS256")


def create_refresh_token(user_id: str, expires_delta: Optional[timedelta] = None) -> str:
    """Generate a signed long-lived JWT refresh token (default 7 days) with unique jti ID."""
    now = datetime.now(timezone.utc)
    exp = now + (expires_delta or timedelta(days=7))
    token_id = str(uuid.uuid4())
    payload = {
        "sub": str(user_id),
        "jti": token_id,
        "type": "refresh",
        "iat": now,
        "exp": exp,
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY.get_secret_value(), algorithm="HS256")


def decode_token(token: str) -> dict:
    """Decode and validate a JWT token, raising standardized HTTP exceptions on error."""
    try:
        return jwt.decode(
            token,
            settings.JWT_SECRET_KEY.get_secret_value(),
            algorithms=["HS256"],
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
            headers={"code": "TOKEN_EXPIRED"},
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token",
            headers={"code": "INVALID_TOKEN"},
        )


async def get_current_user(
    auth: Optional[HTTPAuthorizationCredentials] = Depends(http_bearer),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Dependency that extracts the Bearer token, validates it, and returns the User."""
    if not auth:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication credentials were not provided",
            headers={"code": "UNAUTHORIZED"},
        )

    payload = decode_token(auth.credentials)
    if payload.get("type") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type for authentication",
            headers={"code": "INVALID_TOKEN_TYPE"},
        )

    user_id_str = payload.get("sub")
    if not user_id_str:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token subject missing",
            headers={"code": "INVALID_TOKEN"},
        )

    try:
        user_uuid = uuid.UUID(user_id_str)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Malformed user ID in token",
            headers={"code": "INVALID_TOKEN"},
        )

    result = await db.execute(select(User).where(User.id == user_uuid))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"code": "USER_NOT_FOUND"},
        )

    return user


async def require_user(current_user: User = Depends(get_current_user)) -> User:
    """Dependency ensuring the authenticated user is active."""
    if not current_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is inactive",
            headers={"code": "USER_INACTIVE"},
        )
    return current_user


async def require_admin(current_user: User = Depends(require_user)) -> User:
    """Dependency ensuring the authenticated user has the 'admin' role."""
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required to access this resource",
            headers={"code": "FORBIDDEN"},
        )
    return current_user
