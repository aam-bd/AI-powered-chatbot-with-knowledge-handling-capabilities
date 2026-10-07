"""Authentication API endpoints: /register, /login, /refresh, /me, /logout, /change-password."""
from datetime import datetime, timezone
import uuid
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import get_db
from app.models.sql_models import User
from app.models.schemas import (
    UserRegisterRequest,
    UserLoginRequest,
    TokenResponse,
    RefreshTokenRequest,
    UserResponse,
    ErrorResponse,
    ChangePasswordRequest,
    MessageResponse,
)
from app.core.security import (
    hash_password,
    verify_password,
    create_access_token,
    create_refresh_token,
    decode_token,
    require_user,
    require_admin,
)
from app.core.rate_limit import RateLimiter
from app.core.config import settings
from app.core.logger import logger

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        409: {"model": ErrorResponse, "description": "Email already exists"},
        422: {"model": ErrorResponse, "description": "Validation Error"},
    },
)
async def register(
    req: UserRegisterRequest,
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    """Register a new user account. Role is ALWAYS hardcoded to 'user'."""
    # Check if email is already registered
    existing = await db.execute(select(User).where(User.email == req.email.lower()))
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A user with this email address already exists",
            headers={"code": "EMAIL_ALREADY_REGISTERED"},
        )

    # Server-side password policy validation per §9.1 and §12
    if len(req.password) < settings.PASSWORD_MIN_LENGTH:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Password must be at least {settings.PASSWORD_MIN_LENGTH} characters long",
            headers={"code": "PASSWORD_TOO_SHORT"},
        )

    # Security requirement: Role is ALWAYS 'user', never accepted from client payload
    new_user = User(
        email=req.email.lower(),
        password_hash=hash_password(req.password),
        role="user",
        is_active=True,
    )
    db.add(new_user)
    await db.flush()
    await db.refresh(new_user)

    logger.info(f"Registered new user: {new_user.email} (ID: {new_user.id}, Role: {new_user.role})")
    return new_user


@router.post(
    "/login",
    response_model=TokenResponse,
    dependencies=[Depends(RateLimiter(times=5, seconds=60, route_name="/auth/login"))],
    responses={
        401: {"model": ErrorResponse, "description": "Invalid credentials"},
        429: {"model": ErrorResponse, "description": "Rate limit exceeded"},
    },
)
async def login(
    req: UserLoginRequest,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    """Authenticate with email and password to receive access and refresh tokens.
    
    Protected by stricter Redis rate limiting (5 attempts per minute per IP).
    """
    res = await db.execute(select(User).where(User.email == req.email.lower()))
    user = res.scalar_one_or_none()

    if not user or not verify_password(req.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"code": "INVALID_CREDENTIALS"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is inactive",
            headers={"code": "USER_INACTIVE"},
        )

    access_token = create_access_token(user_id=str(user.id), role=user.role)
    refresh_token = create_refresh_token(user_id=str(user.id))

    logger.info(f"User login successful: {user.email} (Role: {user.role})")
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        expires_in=settings.ACCESS_TOKEN_MINUTES * 60,
    )


@router.post(
    "/refresh",
    response_model=TokenResponse,
    responses={
        401: {"model": ErrorResponse, "description": "Invalid or expired refresh token"},
    },
)
async def refresh_token_endpoint(
    req: RefreshTokenRequest,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    """Exchange a valid refresh token for a newly issued access token."""
    payload = decode_token(req.refresh_token)
    if payload.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Provided token is not a valid refresh token",
            headers={"code": "INVALID_TOKEN_TYPE"},
        )

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Malformed token",
            headers={"code": "INVALID_TOKEN"},
        )

    # Check if the refresh token has been revoked per §9.1
    token_id = payload.get("jti")
    if token_id:
        from app.db.redis import redis_client
        try:
            is_revoked = await redis_client.get(f"revoked:{token_id}")
            if is_revoked:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Refresh token has been revoked",
                    headers={"code": "TOKEN_REVOKED"},
                )
        except HTTPException:
            raise
        except Exception as exc:
            logger.warning(f"Failed to check token revocation in Redis: {exc}")

    res = await db.execute(select(User).where(User.id == uuid.UUID(user_id)))
    user = res.scalar_one_or_none()

    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User associated with refresh token is not found or inactive",
            headers={"code": "USER_NOT_FOUND"},
        )

    new_access_token = create_access_token(user_id=str(user.id), role=user.role)
    # Refresh token can be reused until its expiry or re-issued
    return TokenResponse(
        access_token=new_access_token,
        refresh_token=req.refresh_token,
        token_type="bearer",
        expires_in=settings.ACCESS_TOKEN_MINUTES * 60,
    )


@router.post(
    "/logout",
    response_model=MessageResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid token"},
    },
)
async def logout(
    req: RefreshTokenRequest,
) -> MessageResponse:
    """Revoke a refresh token by registering a revocation marker in Redis."""
    try:
        payload = decode_token(req.refresh_token)
    except HTTPException:
        # If token is expired or malformed, it cannot be used anyway
        return MessageResponse(detail="Logged out successfully.")

    if payload.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provided token is not a valid refresh token",
            headers={"code": "INVALID_TOKEN_TYPE"},
        )

    token_id = payload.get("jti")
    exp = payload.get("exp")
    if token_id and exp:
        now_ts = datetime.now(timezone.utc).timestamp()
        remaining_ttl = max(1, int(exp - now_ts))
        from app.db.redis import redis_client
        try:
            await redis_client.setex(f"revoked:{token_id}", remaining_ttl, "true")
            logger.info(f"Revoked refresh token {token_id} for {remaining_ttl}s")
        except Exception as exc:
            logger.warning(f"Failed to register token revocation in Redis: {exc}")

    return MessageResponse(detail="Logged out successfully.")


@router.post(
    "/change-password",
    response_model=MessageResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid current password"},
        401: {"model": ErrorResponse, "description": "Unauthorized"},
        422: {"model": ErrorResponse, "description": "Password too short"},
    },
)
async def change_password(
    req: ChangePasswordRequest,
    current_user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    """Change the authenticated user's password."""
    if not verify_password(req.current_password, current_user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect",
            headers={"code": "INVALID_CURRENT_PASSWORD"},
        )

    if len(req.new_password) < settings.PASSWORD_MIN_LENGTH:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"New password must be at least {settings.PASSWORD_MIN_LENGTH} characters long",
            headers={"code": "PASSWORD_TOO_SHORT"},
        )

    current_user.password_hash = hash_password(req.new_password)
    await db.commit()
    logger.info(f"Password changed successfully for user: {current_user.email}")
    return MessageResponse(detail="Password changed successfully.")


@router.get(
    "/me",
    response_model=UserResponse,
    responses={
        401: {"model": ErrorResponse, "description": "Unauthorized"},
        403: {"model": ErrorResponse, "description": "Inactive or forbidden"},
    },
)
async def get_me(current_user: User = Depends(require_user)) -> UserResponse:
    """Retrieve the authenticated user's profile and assigned role."""
    return current_user


@router.get(
    "/admin-only",
    response_model=UserResponse,
    responses={
        401: {"model": ErrorResponse, "description": "Unauthorized"},
        403: {"model": ErrorResponse, "description": "Admin privileges required"},
    },
)
async def admin_only_check(current_admin: User = Depends(require_admin)) -> UserResponse:
    """Admin-only protected endpoint to verify role-based access control."""
    return current_admin
