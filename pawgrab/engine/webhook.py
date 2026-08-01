"""Webhook delivery for async job completions."""

from __future__ import annotations

import asyncio

import structlog
from curl_cffi.requests import AsyncSession

from pawgrab.config import settings
from pawgrab.utils.url_safety import SSRFError, assert_public_url

logger = structlog.get_logger()


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
    """POST a JSON payload to the webhook URL with retry. Returns True on success.

    The URL is SSRF-validated (including DNS resolution) before any request is
    sent, and a signature header is attached when a signing secret is configured.
    """
    try:
        await assert_public_url(webhook_url)
    except SSRFError:
        logger.warning("webhook_blocked_ssrf", url=webhook_url, job_id=job_id)
        return False

    payload = {
        "job_id": job_id,
        "job_type": job_type,
        "status": status,
        "pages_scraped": pages_scraped,
        "total_pages": total_pages,
        "error": error,
    }

    import orjson

    body = orjson.dumps(payload)
    headers = {"Content-Type": "application/json"}
    if settings.webhook_secret:
        import hashlib
        import hmac

        sig = hmac.new(settings.webhook_secret.encode(), body, hashlib.sha256).hexdigest()
        headers["X-Pawgrab-Signature"] = f"sha256={sig}"

    max_attempts = settings.webhook_retries + 1
    for attempt in range(1, max_attempts + 1):
        try:
            async with AsyncSession() as session:
                resp = await session.post(
                    webhook_url,
                    data=body,
                    headers=headers,
                    timeout=settings.webhook_timeout,
                )
            if 200 <= resp.status_code < 300:
                logger.info(
                    "webhook_sent",
                    url=webhook_url,
                    job_id=job_id,
                    status_code=resp.status_code,
                    attempt=attempt,
                )
                return True
            logger.warning(
                "webhook_bad_status",
                url=webhook_url,
                job_id=job_id,
                status_code=resp.status_code,
                attempt=attempt,
            )
        except Exception as exc:
            logger.warning(
                "webhook_failed",
                url=webhook_url,
                job_id=job_id,
                error=str(exc),
                attempt=attempt,
            )

        if attempt < max_attempts:
            await asyncio.sleep(2**attempt)

    return False
