"""Session management API endpoints."""

import structlog
from fastapi import APIRouter

from pawgrab.engine.sessions import create_session, delete_session, get_session, update_session
from pawgrab.exceptions import ErrorCode, PawgrabError
from pawgrab.models.common import ErrorResponse
from pawgrab.models.session import (
    CreateSessionRequest,
    CreateSessionResponse,
    SessionInfo,
    UpdateSessionRequest,
)

logger = structlog.get_logger()
router = APIRouter(tags=["Sessions"])


@router.post(
    "/session",
    response_model=CreateSessionResponse,
    responses={503: {"model": ErrorResponse, "description": "Redis unavailable"}},
)
async def create_new_session(req: CreateSessionRequest):
    """Create a new persistent session for cookie/state management across requests."""
    try:
        session_id = await create_session(ttl=req.ttl)
        if req.cookies or req.headers:
            await update_session(session_id, cookies=req.cookies, headers=req.headers)
        return CreateSessionResponse(session_id=session_id)
    except Exception as exc:
        logger.error("session_create_failed", error=str(exc))
        raise PawgrabError(status_code=503, code=ErrorCode.QUEUE_UNAVAILABLE, message="Failed to create session — is Redis running?")


@router.get(
    "/session/{session_id}",
    response_model=SessionInfo,
    responses={404: {"model": ErrorResponse, "description": "Session not found"}},
)
async def get_session_info(session_id: str):
    """Get session details including cookies and stored state."""
    data = await get_session(session_id)
    if data is None:
        raise PawgrabError(status_code=404, code=ErrorCode.RESOURCE_NOT_FOUND, message=f"Session not found: {session_id}")
    return SessionInfo(**data)


@router.put(
    "/session/{session_id}",
    response_model=SessionInfo,
    responses={404: {"model": ErrorResponse, "description": "Session not found"}},
)
async def update_session_data(session_id: str, req: UpdateSessionRequest):
    """Update session cookies, headers, or local storage."""
    ok = await update_session(session_id, cookies=req.cookies, local_storage=req.local_storage, headers=req.headers)
    if not ok:
        raise PawgrabError(status_code=404, code=ErrorCode.RESOURCE_NOT_FOUND, message=f"Session not found: {session_id}")
    data = await get_session(session_id)
    return SessionInfo(**data)


@router.delete(
    "/session/{session_id}",
    responses={404: {"model": ErrorResponse, "description": "Session not found"}},
)
async def delete_session_endpoint(session_id: str):
    """Delete a session and all its stored state."""
    deleted = await delete_session(session_id)
    if not deleted:
        raise PawgrabError(status_code=404, code=ErrorCode.RESOURCE_NOT_FOUND, message=f"Session not found: {session_id}")
    return {"success": True, "message": f"Session {session_id} deleted"}
