"""Live interactive session endpoints (F3).

- POST /scrape/live               open a keep-alive page, get a scrape_id
- POST /scrape/{scrape_id}/interact   drive it with code actions or an AI prompt
- GET  /scrape/{scrape_id}/live.png   live screenshot (the liveViewUrl bytes)
- DELETE /scrape/{scrape_id}          close the session
"""

import structlog
from fastapi import APIRouter, Response

from pawgrab.dependencies import try_browser_pool
from pawgrab.engine import live_session
from pawgrab.exceptions import ErrorCode, PawgrabError
from pawgrab.models.common import ErrorResponse
from pawgrab.models.interact import (
    InteractMode,
    InteractRequest,
    InteractResponse,
    StartLiveRequest,
    StartLiveResponse,
)

logger = structlog.get_logger()
router = APIRouter(tags=["Interact"])


def _live_url(scrape_id: str) -> str:
    return f"/scrape/{scrape_id}/live.png"


@router.post(
    "/scrape/live",
    response_model=StartLiveResponse,
    responses={503: {"model": ErrorResponse, "description": "Browser pool unavailable or at capacity"}},
)
async def start_live(req: StartLiveRequest):
    """Open a URL in a live browser page and keep it alive for interaction."""
    pool = await try_browser_pool()
    if pool is None:
        raise PawgrabError(status_code=503, code=ErrorCode.BROWSER_UNAVAILABLE, message="Live sessions require a running browser pool")
    try:
        scrape_id, rendered = await live_session.start(pool, req.url, req.timeout, [f.value for f in req.formats])
    except RuntimeError as exc:
        raise PawgrabError(status_code=503, code=ErrorCode.BROWSER_UNAVAILABLE, message=str(exc)) from exc
    except Exception as exc:
        logger.error("live_start_failed", url=req.url, error=str(exc))
        raise PawgrabError.fetch_failed(exc) from exc
    return StartLiveResponse(scrape_id=scrape_id, url=req.url, live_view_url=_live_url(scrape_id), **rendered)


@router.post(
    "/scrape/{scrape_id}/interact",
    response_model=InteractResponse,
    responses={404: {"model": ErrorResponse, "description": "Session not found or expired"}},
)
async def interact(scrape_id: str, req: InteractRequest):
    """Drive a live page with code actions or an AI prompt, then return refreshed content."""
    formats = [f.value for f in req.formats]
    try:
        if req.mode == InteractMode.AI:
            if not req.prompt:
                raise PawgrabError(status_code=422, code=ErrorCode.VALIDATION_ERROR, message="mode=ai requires a 'prompt'")
            rendered = await live_session.interact_ai(scrape_id, req.prompt, req.timeout, formats)
        else:
            rendered = await live_session.interact_code(scrape_id, req.actions, req.timeout, formats)
    except KeyError:
        raise PawgrabError(status_code=404, code=ErrorCode.SESSION_EXPIRED, message=f"Live session not found or expired: {scrape_id}") from None
    return InteractResponse(scrape_id=scrape_id, live_view_url=_live_url(scrape_id), **rendered)


@router.get(
    "/scrape/{scrape_id}/live.png",
    responses={404: {"model": ErrorResponse, "description": "Session not found or expired"}},
)
async def live_view(scrape_id: str):
    """Return a PNG screenshot of the current live page state."""
    try:
        png = await live_session.screenshot(scrape_id)
    except KeyError:
        raise PawgrabError(status_code=404, code=ErrorCode.SESSION_EXPIRED, message=f"Live session not found or expired: {scrape_id}") from None
    return Response(content=png, media_type="image/png")


@router.delete(
    "/scrape/{scrape_id}",
    responses={404: {"model": ErrorResponse, "description": "Session not found"}},
)
async def close_live(scrape_id: str):
    """Close a live session and free its browser page."""
    if not await live_session.close(scrape_id):
        raise PawgrabError(status_code=404, code=ErrorCode.SESSION_EXPIRED, message=f"Live session not found: {scrape_id}")
    return {"success": True, "scrape_id": scrape_id}
