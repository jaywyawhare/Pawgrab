"""Shared test fixtures."""

import pytest
from httpx import ASGITransport, AsyncClient

from pawgrab.main import app


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
