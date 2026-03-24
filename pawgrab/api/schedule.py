"""Scheduled crawl API endpoints."""

import structlog
from fastapi import APIRouter

from pawgrab.engine.scheduler import create_schedule, delete_schedule, get_schedule, list_schedules
from pawgrab.exceptions import ErrorCode, PawgrabError
from pawgrab.models.common import ErrorResponse
from pawgrab.models.schedule import CreateScheduleRequest, ScheduleInfo, ScheduleListResponse

logger = structlog.get_logger()
router = APIRouter(tags=["Schedule"])


@router.post(
    "/schedule",
    response_model=ScheduleInfo,
    responses={503: {"model": ErrorResponse, "description": "Redis unavailable"}},
)
async def create_scheduled_crawl(req: CreateScheduleRequest):
    """Create a scheduled recurring crawl."""
    try:
        schedule_id = await create_schedule(
            url=str(req.url),
            cron=req.cron,
            max_pages=req.max_pages,
            max_depth=req.max_depth,
            formats=[f.value for f in req.formats],
            webhook_url=str(req.webhook_url) if req.webhook_url else None,
            strategy=req.strategy.value,
        )
        data = await get_schedule(schedule_id)
        return ScheduleInfo(**data)
    except Exception as exc:
        logger.error("schedule_create_failed", error=str(exc))
        raise PawgrabError(status_code=503, code=ErrorCode.QUEUE_UNAVAILABLE, message="Failed to create schedule") from exc


@router.get("/schedules", response_model=ScheduleListResponse)
async def list_all_schedules():
    """List all scheduled crawls."""
    schedules = await list_schedules()
    return ScheduleListResponse(schedules=[ScheduleInfo(**s) for s in schedules], total=len(schedules))


@router.get(
    "/schedule/{schedule_id}",
    response_model=ScheduleInfo,
    responses={404: {"model": ErrorResponse}},
)
async def get_schedule_info(schedule_id: str):
    """Get schedule details."""
    data = await get_schedule(schedule_id)
    if data is None:
        raise PawgrabError(status_code=404, code=ErrorCode.RESOURCE_NOT_FOUND, message=f"Schedule not found: {schedule_id}")
    return ScheduleInfo(**data)


@router.delete(
    "/schedule/{schedule_id}",
    responses={404: {"model": ErrorResponse}},
)
async def delete_scheduled_crawl(schedule_id: str):
    """Delete a scheduled crawl."""
    deleted = await delete_schedule(schedule_id)
    if not deleted:
        raise PawgrabError(status_code=404, code=ErrorCode.RESOURCE_NOT_FOUND, message=f"Schedule not found: {schedule_id}")
    return {"success": True, "message": f"Schedule {schedule_id} deleted"}
