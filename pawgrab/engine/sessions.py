"""Session persistence: cookies and state across requests."""

from __future__ import annotations

import time
import uuid

import orjson
import structlog

logger = structlog.get_logger()

_SESSION_TTL = 3600  # 1 hour default
_SESSION_PREFIX = "pawgrab:session:"


async def _get_redis():
    from pawgrab.queue.manager import get_redis
    return await get_redis()


async def create_session(*, ttl: int = _SESSION_TTL) -> str:
    """Create a new session and return its ID."""
    session_id = uuid.uuid4().hex[:16]
    redis = await _get_redis()
    data = {
        "session_id": session_id,
        "cookies": "{}",
        "local_storage": "{}",
        "headers": "{}",
        "created_at": str(int(time.time())),
        "last_used": str(int(time.time())),
    }
    key = f"{_SESSION_PREFIX}{session_id}"
    await redis.hset(key, mapping=data)
    await redis.expire(key, ttl)
    logger.info("session_created", session_id=session_id, ttl=ttl)
    return session_id


async def get_session(session_id: str) -> dict | None:
    """Get session data or None if not found."""
    redis = await _get_redis()
    key = f"{_SESSION_PREFIX}{session_id}"
    data = await redis.hgetall(key)
    if not data:
        return None
    await redis.hset(key, "last_used", str(int(time.time())))
    return {
        "session_id": data["session_id"],
        "cookies": orjson.loads(data.get("cookies", "{}")),
        "local_storage": orjson.loads(data.get("local_storage", "{}")),
        "headers": orjson.loads(data.get("headers", "{}")),
        "created_at": int(data.get("created_at", 0)),
        "last_used": int(time.time()),
    }


_UPDATE_SESSION_SCRIPT = """
local key = KEYS[1]
if redis.call('EXISTS', key) == 0 then return 0 end
local i = 1
while i <= #ARGV do
    redis.call('HSET', key, ARGV[i], ARGV[i+1])
    i = i + 2
end
return 1
"""


async def update_session(session_id: str, *, cookies: dict | None = None, local_storage: dict | None = None, headers: dict | None = None) -> bool:
    """Update session data atomically. Returns False if session not found."""
    redis = await _get_redis()
    key = f"{_SESSION_PREFIX}{session_id}"
    updates = {"last_used": str(int(time.time()))}
    if cookies is not None:
        updates["cookies"] = orjson.dumps(cookies).decode()
    if local_storage is not None:
        updates["local_storage"] = orjson.dumps(local_storage).decode()
    if headers is not None:
        updates["headers"] = orjson.dumps(headers).decode()
    argv = [item for pair in updates.items() for item in pair]
    result = await redis.eval(_UPDATE_SESSION_SCRIPT, 1, key, *argv)
    return bool(result)


async def delete_session(session_id: str) -> bool:
    """Delete a session. Returns True if it existed."""
    redis = await _get_redis()
    key = f"{_SESSION_PREFIX}{session_id}"
    return bool(await redis.delete(key))


async def merge_cookies_for_session(session_id: str, new_cookies: dict) -> None:
    """Merge new cookies into the session's cookie jar atomically via WATCH/MULTI/EXEC."""
    from redis.exceptions import WatchError

    redis = await _get_redis()
    key = f"{_SESSION_PREFIX}{session_id}"
    async with redis.pipeline(transaction=True) as pipe:
        while True:
            try:
                await pipe.watch(key)
                raw = await pipe.hget(key, "cookies")
                existing = orjson.loads(raw) if raw else {}
                existing.update(new_cookies)
                pipe.multi()
                pipe.hset(key, "cookies", orjson.dumps(existing).decode())
                await pipe.execute()
                break
            except WatchError:
                continue
