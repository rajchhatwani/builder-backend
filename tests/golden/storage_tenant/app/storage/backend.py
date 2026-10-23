"""Where the bytes live (generated): any S3-compatible object store, through boto3.

boto3 is synchronous, so every call runs in a worker thread. The interface below is what the rest
of the module uses; tests swap in an in-memory implementation with `set_backend`.

Objects are written with a generic content type and without any user-supplied metadata: what a file
is, and what it is called, is decided by this application's database, not by the bucket.
"""

import asyncio
from collections.abc import AsyncIterator
from typing import Any, BinaryIO, Protocol

import structlog

from app.storage import config

logger = structlog.get_logger()
STREAM_CHUNK = 64 * 1024
GENERIC_TYPE = "application/octet-stream"


class ObjectMissing(Exception):
    """The object is not in the bucket."""


class BackendUnavailable(Exception):
    """The object store did not do what was asked (down, refused, timed out)."""


class ObjectBackend(Protocol):
    async def put(self, key: str, file: BinaryIO, *, sha256: str) -> None: ...

    def stream(self, key: str) -> AsyncIterator[bytes]: ...

    async def delete(self, key: str) -> None: ...

    async def exists(self, key: str) -> bool: ...

    def presign(self, key: str, *, filename_header: str, ttl: int) -> str: ...

    async def check(self) -> None: ...

    async def ensure_bucket(self) -> None: ...


class S3Backend:
    def __init__(self, settings: config.StorageSettings) -> None:
        import boto3
        from botocore.config import Config

        self._bucket = config.BUCKET
        self._settings = settings
        addressing = settings.addressing_style()
        client_config = Config(
            signature_version="s3v4",
            retries={"max_attempts": 3, "mode": "standard"},
            connect_timeout=5,
            read_timeout=60,
            s3={"addressing_style": addressing},
            # Newer boto3 adds CRC checksums that several S3-compatible servers do not accept.
            request_checksum_calculation="when_required",
            response_checksum_validation="when_required",
        )
        common: dict[str, Any] = {
            "region_name": settings.region(),
            "config": client_config,
        }
        if settings.storage_access_key_id and settings.storage_secret_access_key:
            common["aws_access_key_id"] = settings.storage_access_key_id
            common["aws_secret_access_key"] = settings.storage_secret_access_key.get_secret_value()
        # No keys given: boto3's normal credential chain (instance or task role, profile).
        self._client = boto3.client("s3", endpoint_url=settings.storage_endpoint_url, **common)
        # Links handed to browsers must use an address the browser can reach.
        public = settings.storage_public_endpoint_url or settings.storage_endpoint_url
        self._signer = (
            self._client
            if public == settings.storage_endpoint_url
            else boto3.client("s3", endpoint_url=public, **common)
        )

    def _extra_args(self, sha256: str) -> dict[str, Any]:
        extra: dict[str, Any] = {"ContentType": GENERIC_TYPE, "Metadata": {"sha256": sha256}}
        sse = self._settings.sse()
        if sse is not None:
            extra["ServerSideEncryption"] = sse
            if sse == "aws:kms" and self._settings.storage_kms_key_id:
                extra["SSEKMSKeyId"] = self._settings.storage_kms_key_id
        return extra

    async def put(self, key: str, file: BinaryIO, *, sha256: str) -> None:
        def run() -> None:
            file.seek(0)
            self._client.upload_fileobj(file, self._bucket, key, ExtraArgs=self._extra_args(sha256))

        try:
            await self._call(run)
        except BackendUnavailable:
            # Development only: the bucket may simply not exist yet. Create it and try once more.
            if self._settings.production or not self._settings.storage_create_bucket:
                raise
            await self.ensure_bucket()
            await self._call(run)

    async def stream(self, key: str) -> AsyncIterator[bytes]:
        def open_body() -> Any:
            return self._client.get_object(Bucket=self._bucket, Key=key)["Body"]

        body = await self._call(open_body, missing_ok=True)
        try:
            chunks = body.iter_chunks(STREAM_CHUNK)
            while True:
                chunk = await asyncio.to_thread(next, chunks, None)
                if chunk is None:
                    break
                yield chunk
        finally:
            await asyncio.to_thread(body.close)

    async def delete(self, key: str) -> None:
        def run() -> None:
            self._client.delete_object(Bucket=self._bucket, Key=key)
            # On a versioned bucket the delete above only hides the object. Remove the old versions
            # too (an erasure request means the bytes are gone), where the credentials allow it.
            try:
                listing = self._client.list_object_versions(Bucket=self._bucket, Prefix=key)
                for item in [*listing.get("Versions", []), *listing.get("DeleteMarkers", [])]:
                    if item.get("Key") == key and item.get("VersionId") not in (None, "null"):
                        self._client.delete_object(
                            Bucket=self._bucket, Key=key, VersionId=item["VersionId"]
                        )
            except Exception as exc:  # not versioned, not supported, or not allowed: not an error
                logger.info("storage_version_purge_skipped", error=type(exc).__name__)

        await self._call(run)

    async def exists(self, key: str) -> bool:
        def run() -> bool:
            try:
                self._client.head_object(Bucket=self._bucket, Key=key)
            except self._client.exceptions.ClientError as exc:
                if exc.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
                    return False
                raise
            return True

        return bool(await self._call(run))

    def presign(self, key: str, *, filename_header: str, ttl: int) -> str:
        return str(
            self._signer.generate_presigned_url(
                "get_object",
                Params={
                    "Bucket": self._bucket,
                    "Key": key,
                    "ResponseContentDisposition": filename_header,
                    "ResponseContentType": GENERIC_TYPE,
                },
                ExpiresIn=ttl,
            )
        )

    async def check(self) -> None:
        await self._call(lambda: self._client.head_bucket(Bucket=self._bucket))

    async def ensure_bucket(self) -> None:
        """Creates the bucket only outside production and only when asked to (local development).
        In production the bucket, its policy and its credentials are set up by hand (see
        deploy/storage/STORAGE.md)."""
        try:
            await self.check()
            return
        except BackendUnavailable:
            if self._settings.production or not self._settings.storage_create_bucket:
                raise
        try:
            await self._call(lambda: self._client.create_bucket(Bucket=self._bucket))
        except BackendUnavailable:
            await self.check()  # someone else may have created it a moment ago

    async def _call(self, fn: Any, *, missing_ok: bool = False) -> Any:
        """Run a blocking boto3 call in a thread. `missing_ok` marks a call about one object: there a
        404 means "no such object". Everywhere else (the bucket itself) a 404 is a failure."""
        try:
            return await asyncio.to_thread(fn)
        except Exception as exc:
            code = getattr(exc, "response", {}).get("Error", {}).get("Code", "")
            if missing_ok and code in ("NoSuchKey", "404", "NotFound"):
                raise ObjectMissing("the object is not in the bucket") from exc
            # Log the class and the S3 error code only: never the endpoint, keys or the message.
            logger.warning("storage_backend_error", error=type(exc).__name__, code=code)
            raise BackendUnavailable("the object store did not complete the request") from exc


_backend: ObjectBackend | None = None


def get_backend() -> ObjectBackend:
    global _backend
    if _backend is None:
        _backend = S3Backend(config.get_storage_settings())
    return _backend


async def prepare_bucket() -> None:
    """Development convenience: create the bucket at start-up when STORAGE_CREATE_BUCKET is set.
    A problem is logged, never raised: start-up must not depend on the object store being up."""
    if not config.get_storage_settings().storage_create_bucket:
        return
    try:
        await get_backend().ensure_bucket()
    except Exception as exc:
        logger.warning("storage_bucket_not_ready", error=type(exc).__name__)


def set_backend(backend: ObjectBackend | None) -> None:
    """Replace the object store (tests use an in-memory one) or, with None, forget it."""
    global _backend
    _backend = backend
