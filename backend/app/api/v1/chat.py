"""API v1 Chat and Session endpoints.

Implements Architecture §8 and Prompt 4 (First Half):
- GET /api/v1/chat/sessions: Retrieve the caller's active sessions.
- DELETE /api/v1/chat/sessions/{session_id}: Clear a session (strictly owner only).
"""
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status

from app.core.security import require_user
from app.models.schemas import (
    ErrorResponse,
    SessionSummaryResponse,
    SessionDeleteResponse,
)
from app.models.sql_models import User
from app.services.session_manager import get_session_manager, SessionManager

router = APIRouter(prefix="/chat", tags=["chat"])


@router.get(
    "/sessions",
    response_model=List[SessionSummaryResponse],
    summary="List active user sessions",
    responses={
        401: {"model": ErrorResponse, "description": "Unauthorized"},
    },
)
async def list_chat_sessions(
    current_user: User = Depends(require_user),
    session_manager: SessionManager = Depends(get_session_manager),
) -> List[SessionSummaryResponse]:
    """Retrieve all active conversation sessions belonging to the authenticated caller."""
    return await session_manager.list_sessions(user_id=str(current_user.id))


@router.delete(
    "/sessions/{session_id}",
    response_model=SessionDeleteResponse,
    summary="Clear a chat session",
    responses={
        401: {"model": ErrorResponse, "description": "Unauthorized"},
        404: {"model": ErrorResponse, "description": "Session not found"},
    },
)
async def delete_chat_session(
    session_id: str,
    current_user: User = Depends(require_user),
    session_manager: SessionManager = Depends(get_session_manager),
) -> SessionDeleteResponse:
    """Clear a conversation session. Enforces strict owner isolation."""
    cleared = await session_manager.clear_session(
        user_id=str(current_user.id),
        session_id=session_id,
    )
    if not cleared:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found.",
            headers={"code": "SESSION_NOT_FOUND"},
        )
    return SessionDeleteResponse(
        detail="Session deleted successfully.",
        session_id=session_id,
    )
