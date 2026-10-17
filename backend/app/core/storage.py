"""Media object storage. Keys look like `media/2026/10/<uuid>.jpg`; `url(key)` is what readers fetch."""

import asyncio
from functools import lru_cache
from pathlib import Path
from typing import Protocol

from app.core.config import get_settings

MAX_UPLOAD_BYTES = 10 * 1024 * 1024


class Storage(Protocol):
    async def put(self, key: str, data: bytes, content_type: str) -> None: ...

    async def get(self, key: str) -> bytes:
        """The stored bytes; raises FileNotFoundError when the key does not exist."""
        ...

    async def delete(self, key: str) -> None:
        """Remove the object; a missing key is not an error."""
        ...

    def url(self, key: str) -> str: ...


def _join_url(base_url: str, key: str) -> str:
    return f"{base_url.rstrip('/')}/{key}"


class LocalStorage:
    def __init__(self, root_dir: str | Path, base_url: str = "") -> None:
        self.root = Path(root_dir)
        self.base_url = base_url

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if not path.is_relative_to(self.root.resolve()):
            raise ValueError("storage key escapes the storage root")
        return path

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        def write() -> None:
            path = self._path(key)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)

        await asyncio.to_thread(write)

    async def get(self, key: str) -> bytes:
        return await asyncio.to_thread(self._path(key).read_bytes)

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(self._path(key).unlink, True)

    def url(self, key: str) -> str:
        return _join_url(self.base_url, key)


class S3Storage:
    """Cloudflare R2 (S3 API). boto3 is synchronous, so every call runs in a worker thread."""

    def __init__(self, *, endpoint: str, bucket: str, access_key: str, secret_key: str, base_url: str) -> None:
        import boto3

        self.bucket = bucket
        self.base_url = base_url
        self._client = boto3.client(
            "s3", endpoint_url=endpoint, aws_access_key_id=access_key,
            aws_secret_access_key=secret_key, region_name="auto",
        )

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        await asyncio.to_thread(
            self._client.put_object, Bucket=self.bucket, Key=key, Body=data, ContentType=content_type,
            CacheControl="public, max-age=31536000, immutable",
        )

    async def get(self, key: str) -> bytes:
        def read() -> bytes:
            try:
                return self._client.get_object(Bucket=self.bucket, Key=key)["Body"].read()
            except self._client.exceptions.NoSuchKey as exc:
                raise FileNotFoundError(key) from exc

        return await asyncio.to_thread(read)

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(self._client.delete_object, Bucket=self.bucket, Key=key)

    def url(self, key: str) -> str:
        return _join_url(self.base_url, key)


@lru_cache
def get_storage() -> Storage:
    s = get_settings()
    if s.storage == "s3":  # Settings has already refused to load without every s3 value
        return S3Storage(
            endpoint=s.s3_endpoint, bucket=s.s3_bucket, access_key=s.s3_access_key,
            secret_key=s.s3_secret_key, base_url=s.media_base_url,
        )
    return LocalStorage(s.media_local_dir, s.media_base_url)
