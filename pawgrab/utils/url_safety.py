"""Shared SSRF protection for every outbound request.

The service fetches user-supplied URLs (scrape/crawl/map/extract) and posts to
user-supplied webhooks. Both are SSRF vectors: without a guard, a caller can
point the fetcher at ``http://169.254.169.254/latest/meta-data/`` (cloud
credential theft) or internal services. This module centralises the check so the
fetch path and the webhook path share one implementation.

Two layers:
  - ``is_safe_url`` — synchronous, no DNS. Rejects non-HTTP schemes, literal
    private/reserved IPs, and internal hostnames. Cheap; safe to call anywhere.
  - ``assert_public_url`` — async. Runs ``is_safe_url`` then resolves the
    hostname and rejects if *any* resolved address is private/reserved. This is
    what defeats a public name that resolves to an internal IP (DNS rebinding).

Resolution errors fail *open* (the literal check has already run, and curl will
itself fail to connect) so a transient DNS blip doesn't spuriously kill a scrape.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import urlparse

import structlog

from pawgrab.config import settings

logger = structlog.get_logger()
_BLOCKED_HOSTNAMES = frozenset(
    {
        "localhost",
        "metadata.google.internal",
        "metadata.goog",
    }
)
_BLOCKED_SUFFIXES = (".internal", ".local", ".corp", ".home.arpa", ".localhost")


class SSRFError(PermissionError):
    """Raised when a URL targets a private/internal/blocked address."""


def redact_url_creds(url: str) -> str:
    """Strip ``user:pass@`` credentials from a URL for safe logging."""
    try:
        parsed = urlparse(url)
    except Exception:
        return "<url>"
    if parsed.username or parsed.password:
        host = parsed.hostname or ""
        if parsed.port:
            host = f"{host}:{parsed.port}"
        return f"{parsed.scheme}://{host}{parsed.path}"
    return url


def host_matches(url: str, *domains: str) -> bool:
    """True when the URL's host equals, or is a subdomain of, any given domain."""
    host = (urlparse(url).hostname or "").lower().rstrip(".")
    return any(host == d or host.endswith("." + d) for d in domains)


def _ip_blocked(addr: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Whether an IP is in any non-public range we must never connect to."""
    return addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved or addr.is_multicast or addr.is_unspecified


def is_safe_url(url: str, *, allow_private: bool | None = None) -> bool:
    """Synchronous literal-only safety check (no DNS).

    Rejects non-HTTP(S) schemes, literal private/reserved IPs, and known-internal
    hostnames/suffixes. ``allow_private`` overrides the global setting (used for
    local development where 127.0.0.1 targets are legitimate).
    """
    if allow_private is None:
        allow_private = settings.allow_private_urls
    if allow_private:
        return True
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return False
    hostname = parsed.hostname
    if not hostname:
        return False
    try:
        addr = ipaddress.ip_address(hostname)
        return not _ip_blocked(addr)
    except ValueError:
        lower = hostname.lower().rstrip(".")
        if lower in _BLOCKED_HOSTNAMES:
            return False
        if any(lower.endswith(s) for s in _BLOCKED_SUFFIXES):
            return False
        return True


async def _resolve(hostname: str) -> list[str]:
    """Resolve a hostname to its IP strings off the event loop."""
    infos = await asyncio.to_thread(socket.getaddrinfo, hostname, None, proto=socket.IPPROTO_TCP)
    return [info[4][0] for info in infos]


async def assert_public_url(url: str, *, allow_private: bool | None = None) -> None:
    """Raise :class:`SSRFError` if *url* is unsafe, resolving DNS to catch rebinds.

    No-op when ``settings.ssrf_protection`` is disabled. Resolution failures fail
    open (literal check already ran; the connection will fail anyway).
    """
    if allow_private is None:
        allow_private = settings.allow_private_urls
    if not settings.ssrf_protection or allow_private:
        return
    if not is_safe_url(url, allow_private=False):
        raise SSRFError(f"URL blocked (private/internal/non-HTTP target): {url}")
    hostname = urlparse(url).hostname
    if not hostname:
        raise SSRFError(f"URL has no hostname: {url}")

    try:
        ipaddress.ip_address(hostname)
        return
    except ValueError:
        pass
    try:
        addresses = await _resolve(hostname)
    except Exception as exc:
        logger.debug("ssrf_dns_resolve_failed", host=hostname, error=str(exc))
        return
    for raw in addresses:
        try:
            addr = ipaddress.ip_address(raw.split("%")[0])
        except ValueError:
            continue
        if _ip_blocked(addr):
            raise SSRFError(f"URL resolves to a private/internal address ({raw}): {url}")
