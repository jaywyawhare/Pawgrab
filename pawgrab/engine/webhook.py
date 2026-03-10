"""Webhook delivery for async job completions."""

from __future__ import annotations

import structlog
from curl_cffi.requests import AsyncSession

logger = structlog.get_logger()

_WEBHOOK_TIMEOUT = 15


async def send_webhook(
    webhook_url: str,
    *,
    job_id: str,
    job_type: str,
    status: str,
    pages_scraped: int = 0,
    total_pages: int | None = None,
    error: str | None = None,
) -> bool:
    """POST a JSON payload to the webhook URL. Returns True on success."""
    payload = {
        "job_id": job_id,
        "job_type": job_type,
        "status": status,
        "pages_scraped": pages_scraped,
        "total_pages": total_pages,
        "error": error,
    }

    try:
        async with AsyncSession() as session:
            resp = await session.post(
                webhook_url,
                json=payload,
                timeout=_WEBHOOK_TIMEOUT,
            )
        logger.info(
            "webhook_sent",
            url=webhook_url,
            job_id=job_id,
            status_code=resp.status_code,
        )
        return 200 <= resp.status_code < 300
    except Exception as exc:
        logger.warning(
            "webhook_failed",
            url=webhook_url,
            job_id=job_id,
            error=str(exc),
        )
        return False
