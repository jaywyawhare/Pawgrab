"""Result persistence to filesystem or S3-compatible storage."""

from __future__ import annotations

import os
import time
from pathlib import Path

import orjson
import structlog

from pawgrab.config import settings

logger = structlog.get_logger()


class StorageBackend:
    """Base storage backend."""

    async def store(self, key: str, data: dict, *, prefix: str = "") -> str:
        raise NotImplementedError

    async def retrieve(self, key: str, *, prefix: str = "") -> dict | None:
        raise NotImplementedError

    async def list_keys(self, prefix: str = "") -> list[str]:
        raise NotImplementedError

    async def delete(self, key: str, *, prefix: str = "") -> bool:
        raise NotImplementedError


class FilesystemStorage(StorageBackend):
    """Store results on the local filesystem as JSON files."""

    def __init__(self, base_dir: str | None = None):
        self._base_dir = Path(base_dir or settings.storage_path)
        self._base_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str, prefix: str = "") -> Path:
        if prefix:
            d = self._base_dir / prefix
            d.mkdir(parents=True, exist_ok=True)
            return d / f"{key}.json"
        return self._base_dir / f"{key}.json"

    async def store(self, key: str, data: dict, *, prefix: str = "") -> str:
        import asyncio
        path = self._path(key, prefix)
        body = orjson.dumps(data, option=orjson.OPT_INDENT_2)
        await asyncio.to_thread(path.write_bytes, body)
        logger.debug("file_stored", path=str(path))
        return str(path)

    async def retrieve(self, key: str, *, prefix: str = "") -> dict | None:
        import asyncio
        path = self._path(key, prefix)
        if not path.exists():
            return None
        try:
            raw = await asyncio.to_thread(path.read_bytes)
            return orjson.loads(raw)
        except Exception as exc:
            logger.warning("file_read_failed", path=str(path), error=str(exc))
            return None

    async def list_keys(self, prefix: str = "") -> list[str]:
        import asyncio
        d = self._base_dir / prefix if prefix else self._base_dir
        if not d.exists():
            return []
        def _glob():
            return [f.stem for f in sorted(d.glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True)]
        return await asyncio.to_thread(_glob)

    async def delete(self, key: str, *, prefix: str = "") -> bool:
        import asyncio
        path = self._path(key, prefix)
        def _delete():
            if path.exists():
                path.unlink()
                return True
            return False
        return await asyncio.to_thread(_delete)


class S3Storage(StorageBackend):
    """Store results in S3-compatible storage (AWS S3, MinIO, etc.)."""

    def __init__(self):
        self._bucket = settings.s3_bucket
        self._prefix = settings.s3_prefix
        self._client = None

    def _get_client(self):
        if self._client is None:
            import boto3
            kwargs = {}
            if settings.s3_endpoint_url:
                kwargs["endpoint_url"] = settings.s3_endpoint_url
            if settings.s3_access_key:
                kwargs["aws_access_key_id"] = settings.s3_access_key
                kwargs["aws_secret_access_key"] = settings.s3_secret_key
            self._client = boto3.client("s3", region_name=settings.s3_region, **kwargs)
        return self._client

    def _s3_key(self, key: str, prefix: str = "") -> str:
        parts = [self._prefix, prefix, f"{key}.json"]
        return "/".join(p for p in parts if p)

    async def store(self, key: str, data: dict, *, prefix: str = "") -> str:
        import asyncio
        s3_key = self._s3_key(key, prefix)
        body = orjson.dumps(data, option=orjson.OPT_INDENT_2)
        await asyncio.to_thread(
            self._get_client().put_object,
            Bucket=self._bucket,
            Key=s3_key,
            Body=body,
            ContentType="application/json",
        )
        logger.debug("s3_stored", bucket=self._bucket, key=s3_key)
        return f"s3://{self._bucket}/{s3_key}"

    async def retrieve(self, key: str, *, prefix: str = "") -> dict | None:
        import asyncio
        s3_key = self._s3_key(key, prefix)
        try:
            resp = await asyncio.to_thread(
                self._get_client().get_object,
                Bucket=self._bucket,
                Key=s3_key,
            )
            return orjson.loads(resp["Body"].read())
        except Exception:
            return None

    async def list_keys(self, prefix: str = "") -> list[str]:
        import asyncio
        full_prefix = "/".join(p for p in [self._prefix, prefix] if p)
        try:
            resp = await asyncio.to_thread(
                self._get_client().list_objects_v2,
                Bucket=self._bucket,
                Prefix=full_prefix,
                MaxKeys=1000,
            )
            keys = []
            for obj in resp.get("Contents", []):
                name = obj["Key"].rsplit("/", 1)[-1]
                if name.endswith(".json"):
                    keys.append(name[:-5])
            return keys
        except Exception:
            return []

    async def delete(self, key: str, *, prefix: str = "") -> bool:
        import asyncio
        s3_key = self._s3_key(key, prefix)
        try:
            await asyncio.to_thread(
                self._get_client().delete_object,
                Bucket=self._bucket,
                Key=s3_key,
            )
            return True
        except Exception:
            return False


_storage: StorageBackend | None = None


def get_storage() -> StorageBackend:
    """Get the configured storage backend."""
    global _storage
    if _storage is None:
        backend = settings.storage_backend
        if backend == "s3":
            _storage = S3Storage()
        else:
            _storage = FilesystemStorage()
    return _storage


async def persist_result(job_type: str, job_id: str, result: dict) -> str | None:
    """Persist a job result if storage is enabled."""
    if not settings.storage_backend:
        return None
    try:
        storage = get_storage()
        return await storage.store(f"{job_id}_{int(time.time())}", result, prefix=job_type)
    except Exception as exc:
        logger.warning("persist_failed", job_type=job_type, job_id=job_id, error=str(exc))
        return None
