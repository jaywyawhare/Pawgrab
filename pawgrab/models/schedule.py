"""Models for the schedule API."""

from pydantic import BaseModel, Field

from .crawl import CrawlParamsBase


class CreateScheduleRequest(CrawlParamsBase):
    cron: str = Field(..., min_length=1, max_length=100, description="Cron expression (e.g. '*/30 * * * *' for every 30 minutes)")


class ScheduleInfo(BaseModel):
    schedule_id: str
    url: str
    cron: str
    max_pages: int = 10
    max_depth: int = 3
    formats: list[str] = ["markdown"]
    webhook_url: str | None = None
    strategy: str = "bfs"
    created_at: int = 0
    last_run: int = 0
    next_run: int = 0
    run_count: int = 0
    enabled: bool = True


class ScheduleListResponse(BaseModel):
    schedules: list[ScheduleInfo] = []
    total: int = 0
