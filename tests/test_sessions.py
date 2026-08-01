from unittest.mock import AsyncMock, MagicMock, patch


def _make_redis(hgetall_return=None, hset_return=None, expire_return=None, delete_return=0, eval_return=1):
    redis = AsyncMock()
    redis.hset = AsyncMock(return_value=hset_return)
    redis.hgetall = AsyncMock(return_value=hgetall_return or {})
    redis.expire = AsyncMock(return_value=expire_return)
    redis.delete = AsyncMock(return_value=delete_return)
    redis.eval = AsyncMock(return_value=eval_return)
    return redis


async def test_create_session_returns_16_char_id():
    mock_redis = _make_redis()
    with patch("pawgrab.queue.manager.get_redis", new_callable=AsyncMock, return_value=mock_redis):
        from pawgrab.engine.sessions import create_session

        session_id = await create_session()

    assert isinstance(session_id, str)
    assert len(session_id) == 16
    mock_redis.hset.assert_called_once()
    mock_redis.expire.assert_called_once()


async def test_create_session_custom_ttl():
    mock_redis = _make_redis()
    with patch("pawgrab.queue.manager.get_redis", new_callable=AsyncMock, return_value=mock_redis):
        from pawgrab.engine.sessions import create_session

        await create_session(ttl=7200)

    call_args = mock_redis.expire.call_args
    assert 7200 in (call_args[0][1], call_args.args[1] if call_args.args else None) or 7200 in call_args.args


async def test_get_session_found():
    import time

    session_data = {
        "session_id": "abc1234567890123",
        "cookies": '{"session": "tok123"}',
        "local_storage": "{}",
        "headers": '{"User-Agent": "test"}',
        "created_at": str(int(time.time())),
        "last_used": str(int(time.time())),
    }
    with patch("pawgrab.queue.manager.get_redis", new_callable=AsyncMock, return_value=_make_redis(hgetall_return=session_data)):
        from pawgrab.engine.sessions import get_session

        result = await get_session("abc1234567890123")

    assert result is not None
    assert result["session_id"] == "abc1234567890123"
    assert result["cookies"] == {"session": "tok123"}
    assert result["headers"] == {"User-Agent": "test"}


async def test_get_session_not_found():
    with patch("pawgrab.queue.manager.get_redis", new_callable=AsyncMock, return_value=_make_redis(hgetall_return={})):
        from pawgrab.engine.sessions import get_session

        assert await get_session("nonexistent") is None


async def test_update_session_success():
    mock_redis = _make_redis(eval_return=1)
    with patch("pawgrab.queue.manager.get_redis", new_callable=AsyncMock, return_value=mock_redis):
        from pawgrab.engine.sessions import update_session

        assert await update_session("sid123", cookies={"token": "abc"}, headers={"X-Auth": "key"}) is True
    mock_redis.eval.assert_called_once()


async def test_update_session_not_found():
    with patch("pawgrab.queue.manager.get_redis", new_callable=AsyncMock, return_value=_make_redis(eval_return=0)):
        from pawgrab.engine.sessions import update_session

        assert await update_session("nonexistent", cookies={"x": "y"}) is False


async def test_delete_session():
    with patch("pawgrab.queue.manager.get_redis", new_callable=AsyncMock, return_value=_make_redis(delete_return=1)):
        from pawgrab.engine.sessions import delete_session

        assert await delete_session("sid123") is True

    with patch("pawgrab.queue.manager.get_redis", new_callable=AsyncMock, return_value=_make_redis(delete_return=0)):
        from pawgrab.engine.sessions import delete_session

        assert await delete_session("nonexistent") is False


async def test_merge_cookies_for_session():
    import orjson

    existing_cookies = orjson.dumps({"old": "value"}).decode()

    pipe = AsyncMock()
    pipe.__aenter__ = AsyncMock(return_value=pipe)
    pipe.__aexit__ = AsyncMock(return_value=False)
    pipe.watch = AsyncMock()
    pipe.hget = AsyncMock(return_value=existing_cookies)
    pipe.multi = AsyncMock()
    pipe.hset = AsyncMock()
    pipe.execute = AsyncMock()

    mock_redis = AsyncMock()
    mock_redis.pipeline = MagicMock(return_value=pipe)

    with patch("pawgrab.queue.manager.get_redis", new_callable=AsyncMock, return_value=mock_redis):
        from pawgrab.engine.sessions import merge_cookies_for_session

        await merge_cookies_for_session("sid123", {"new": "cookie"})

    pipe.hset.assert_called_once()
    call_args = pipe.hset.call_args
    merged_raw = call_args[0][2] if len(call_args[0]) > 2 else call_args.args[2] if len(call_args.args) > 2 else call_args.kwargs.get("value", "")
    if merged_raw:
        merged = orjson.loads(merged_raw)
        assert "old" in merged
        assert "new" in merged
