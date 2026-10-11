"""User management endpoints for administrators: GET /users, PATCH /users/{id}."""
import uuid
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import get_db
from app.models.sql_models import User
from app.models.schemas import UserResponse, UserAdminUpdateRequest, ErrorResponse
from app.core.security import require_admin
from app.core.logger import logger
from app.db.redis import redis_client

router = APIRouter(prefix="/users", tags=["users"])


@router.get(
    "",
    response_model=List[UserResponse],
    responses={
        401: {"model": ErrorResponse, "description": "Unauthorized"},
        403: {"model": ErrorResponse, "description": "Forbidden - Admin required"},
    },
)
async def list_users(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
) -> List[UserResponse]:
    """List registered users ordered newest first. Admin only."""
    stmt = select(User).order_by(User.created_at.desc()).offset(skip).limit(limit)
    res = await db.execute(stmt)
    users = res.scalars().all()
    return list(users)


@router.patch(
    "/{user_id}",
    response_model=UserResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid operation (self-demotion or last admin)"},
        401: {"model": ErrorResponse, "description": "Unauthorized"},
        403: {"model": ErrorResponse, "description": "Forbidden - Admin required"},
        404: {"model": ErrorResponse, "description": "User not found"},
        422: {"model": ErrorResponse, "description": "Validation error"},
    },
)
async def update_user(
    user_id: uuid.UUID,
    req: UserAdminUpdateRequest,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
) -> UserResponse:
    """Modify user role or active status. Admin only.
    
    Rules:
    - An admin cannot demote or deactivate themselves.
    - The last active admin cannot be demoted or deactivated (race-safe via row locks).
    - Deactivation revokes user refresh tokens immediately.
    - Every change is logged without secrets.
    """
    res = await db.execute(select(User).where(User.id == user_id))
    target_user = res.scalar_one_or_none()
    if not target_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
            headers={"code": "USER_NOT_FOUND"},
        )

    # 1. Rule: An admin cannot demote or deactivate themselves
    if target_user.id == admin.id:
        if req.role is not None and req.role != "admin":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Administrators cannot demote themselves.",
                headers={"code": "SELF_DEMOTION_FORBIDDEN"},
            )
        if req.is_active is False:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Administrators cannot deactivate themselves.",
                headers={"code": "SELF_DEACTIVATION_FORBIDDEN"},
            )

    # 2. Rule: The last active admin cannot be demoted or deactivated
    # Must be race-safe: row-level lock on active admins using with_for_update()
    is_target_active_admin = target_user.role == "admin" and target_user.is_active
    will_demote_or_deactivate = (
        (req.role is not None and req.role != "admin")
        or req.is_active is False
    )

    if is_target_active_admin and will_demote_or_deactivate:
        admin_lock_stmt = (
            select(User)
            .where(User.role == "admin", User.is_active == True)
            .with_for_update()
        )
        active_admins = (await db.execute(admin_lock_stmt)).scalars().all()
        if len(active_admins) <= 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot demote or deactivate the last active administrator.",
                headers={"code": "LAST_ADMIN_PROTECTED"},
            )

    # 3. Apply changes
    if req.role is not None:
        target_user.role = req.role

    if req.is_active is not None:
        target_user.is_active = req.is_active
        if req.is_active is False:
            # Revoke refresh tokens in Redis per §9.1
            try:
                await redis_client.setex(f"user_revoked:{target_user.id}", 7 * 86400, "1")
            except Exception as exc:
                logger.warning(f"Failed to record user revocation in Redis: {exc}")

    await db.commit()
    await db.refresh(target_user)

    # 4. Audit logging without secrets
    logger.info(
        f"Admin {admin.id} ({admin.email}) modified user {target_user.id} ({target_user.email}): "
        f"role={target_user.role}, is_active={target_user.is_active}"
    )

    return target_user
