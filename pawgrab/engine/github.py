"""Native GitHub repository reader via the public REST API — no token (unauthenticated rate limit)."""

from __future__ import annotations

from urllib.parse import urlparse

import structlog

from pawgrab.engine.reader_http import reader_get

logger = structlog.get_logger()
_API_HEADERS = {"Accept": "application/vnd.github+json"}
_RESERVED_OWNERS = frozenset(
    {"features", "about", "pricing", "settings", "orgs", "marketplace", "explore", "topics", "sponsors", "notifications", "login", "join", "new", "search", "apps", "collections"}
)


def parse_repo(url: str) -> tuple[str, str] | None:
    """Return ``(owner, repo)`` for a github.com repo URL, else ``None``.

    The first path segment is rejected when it is a GitHub feature path
    (``/settings``, ``/features``, …) rather than a repo owner.
    """
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower().rstrip(".")
    if host not in ("github.com", "www.github.com"):
        return None
    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) < 2 or parts[0].lower() in _RESERVED_OWNERS:
        return None
    return parts[0], parts[1].removesuffix(".git")


async def fetch_repo(url: str) -> dict:
    """Fetch GitHub repository metadata. Raises ``ValueError`` on a non-repo URL or API error."""
    parsed = parse_repo(url)
    if parsed is None:
        raise ValueError("not a GitHub repository URL")
    owner, repo = parsed
    resp = await reader_get(f"https://api.github.com/repos/{owner}/{repo}", headers=_API_HEADERS)
    if resp.status_code == 404:
        raise ValueError(f"repository {owner}/{repo} not found")
    if resp.status_code == 403:
        raise ValueError("GitHub API rate limit exceeded (unauthenticated)")
    if resp.status_code != 200:
        raise ValueError(f"GitHub API returned HTTP {resp.status_code}")
    d = resp.json()
    return {
        "full_name": d.get("full_name"),
        "description": d.get("description"),
        "owner": (d.get("owner") or {}).get("login"),
        "owner_type": (d.get("owner") or {}).get("type"),
        "url": d.get("html_url"),
        "homepage": d.get("homepage") or None,
        "language": d.get("language"),
        "topics": d.get("topics") or [],
        "stars": d.get("stargazers_count"),
        "forks": d.get("forks_count"),
        "watchers": d.get("subscribers_count"),
        "open_issues": d.get("open_issues_count"),
        "license": (d.get("license") or {}).get("spdx_id"),
        "default_branch": d.get("default_branch"),
        "archived": d.get("archived"),
        "created_at": d.get("created_at"),
        "updated_at": d.get("updated_at"),
        "pushed_at": d.get("pushed_at"),
    }
