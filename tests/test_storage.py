from pathlib import Path
from unittest.mock import patch

import pytest

from pawgrab.engine.storage import FilesystemStorage


@pytest.fixture
def tmp_storage(tmp_path):
    return FilesystemStorage(base_dir=str(tmp_path))


class TestFilesystemStorage:
    @pytest.mark.asyncio
    async def test_store_creates_file(self, tmp_storage):
        location = await tmp_storage.store("test_key", {"data": "value"})
        assert Path(location).exists()

    @pytest.mark.asyncio
    async def test_store_and_retrieve(self, tmp_storage):
        await tmp_storage.store("mykey", {"foo": "bar", "count": 42})
        assert await tmp_storage.retrieve("mykey") == {"foo": "bar", "count": 42}

    @pytest.mark.asyncio
    async def test_retrieve_nonexistent_returns_none(self, tmp_storage):
        assert await tmp_storage.retrieve("nonexistent") is None

    @pytest.mark.asyncio
    async def test_prefix_isolation(self, tmp_storage, tmp_path):
        await tmp_storage.store("key1", {"x": 1}, prefix="scrape")
        assert await tmp_storage.retrieve("key1", prefix="scrape") == {"x": 1}
        assert await tmp_storage.retrieve("key1", prefix="extract") is None
        assert (tmp_path / "scrape").is_dir()

    @pytest.mark.asyncio
    async def test_list_keys_empty(self, tmp_storage):
        assert await tmp_storage.list_keys() == []

    @pytest.mark.asyncio
    async def test_list_keys(self, tmp_storage):
        await tmp_storage.store("key_a", {"a": 1})
        await tmp_storage.store("key_b", {"b": 2})
        keys = await tmp_storage.list_keys()
        assert "key_a" in keys
        assert "key_b" in keys

    @pytest.mark.asyncio
    async def test_list_keys_with_prefix(self, tmp_storage):
        await tmp_storage.store("k1", {"x": 1}, prefix="crawl")
        await tmp_storage.store("k2", {"y": 2})
        crawl_keys = await tmp_storage.list_keys(prefix="crawl")
        root_keys = await tmp_storage.list_keys()
        assert "k1" in crawl_keys
        assert "k1" not in root_keys
        assert "k2" in root_keys

    @pytest.mark.asyncio
    async def test_delete_existing(self, tmp_storage):
        await tmp_storage.store("del_key", {"data": "remove"})
        assert await tmp_storage.delete("del_key") is True
        assert await tmp_storage.retrieve("del_key") is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self, tmp_storage):
        assert await tmp_storage.delete("ghost_key") is False

    @pytest.mark.asyncio
    async def test_overwrite(self, tmp_storage):
        await tmp_storage.store("key", {"v": 1})
        await tmp_storage.store("key", {"v": 2})
        assert (await tmp_storage.retrieve("key"))["v"] == 2

    @pytest.mark.asyncio
    async def test_store_returns_json_path(self, tmp_storage):
        location = await tmp_storage.store("pathtest", {"x": 1})
        assert isinstance(location, str)
        assert location.endswith(".json")


class TestPersistResult:
    @pytest.mark.asyncio
    async def test_disabled_when_no_backend(self):
        from pawgrab.engine.storage import persist_result

        with patch("pawgrab.engine.storage.settings") as mock_settings:
            mock_settings.storage_backend = ""
            assert await persist_result("scrape", "job123", {"data": "x"}) is None

    @pytest.mark.asyncio
    async def test_uses_filesystem_backend(self, tmp_path):
        import pawgrab.engine.storage as storage_mod
        from pawgrab.engine.storage import persist_result

        storage_mod._storage = None
        with patch("pawgrab.engine.storage.settings") as mock_settings:
            mock_settings.storage_backend = "filesystem"
            mock_settings.storage_path = str(tmp_path)
            result = await persist_result("scrape", "job456", {"result": "ok"})
        assert result is not None
        storage_mod._storage = None

    @pytest.mark.asyncio
    async def test_handles_exception_gracefully(self):
        import pawgrab.engine.storage as storage_mod
        from pawgrab.engine.storage import persist_result

        storage_mod._storage = None
        with patch("pawgrab.engine.storage.settings") as mock_settings:
            mock_settings.storage_backend = "filesystem"
            mock_settings.storage_path = "/nonexistent/readonly/path/that/fails"
            await persist_result("scrape", "job789", {"data": "x"})
        storage_mod._storage = None
