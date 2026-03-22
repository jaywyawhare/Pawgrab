"""Webhook delivery for async job completions."""

from __future__ import annotations

import asyncio
import ipaddress
from urllib.parse import urlparse

import structlog
from curl_cffi.requests import AsyncSession

from pawgrab.config import settings

logger = structlog.get_logger()

_PRIVATE_NETWORKS = (
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("100.64.0.0/10"),  # CGNAT
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),  # link-local / cloud metadata
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
)

_BLOCKED_HOSTNAMES = frozenset({"localhost", "metadata.google.internal"})
_BLOCKED_SUFFIXES = (".internal", ".local", ".corp", ".home.arpa")


def _is_safe_url(url: str) -> bool:
    """Reject webhook URLs pointing to private/internal networks or non-HTTP schemes."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return False
    hostname = parsed.hostname
    if not hostname:
        return False

    try:
        addr = ipaddress.ip_address(hostname)
        return not any(addr in net for net in _PRIVATE_NETWORKS)
    except ValueError:
        lower = hostname.lower()
        if lower in _BLOCKED_HOSTNAMES:
            return False
        if any(lower.endswith(s) for s in _BLOCKED_SUFFIXES):
            return False
        return True


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
    """POST a JSON payload to the webhook URL with retry. Returns True on success."""
    if not _is_safe_url(webhook_url):
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

    max_attempts = settings.webhook_retries + 1
    for attempt in range(1, max_attempts + 1):
        try:
            async with AsyncSession() as session:
                resp = await session.post(
                    webhook_url,
                    json=payload,
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
            await asyncio.sleep(2 ** attempt)

    return False
