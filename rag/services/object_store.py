"""Async S3 / Minio client for avatar (and future) object storage.

Phase 28 Part 2 wraps ``aioboto3`` behind a focused, mypy-strict interface so
route handlers never touch the SDK directly. The client is lazily constructed
from ``rag.config.settings`` and respects:

    minio_endpoint        — full URL (e.g. ``http://minio:9000``)
    minio_access_key      — root user / access key id
    minio_secret_key      — root password / secret access key
    minio_region          — region label (Minio doesn't enforce, S3 does)
    minio_bucket_avatars  — bucket name for avatar blobs
    minio_public_base_url — CDN / nginx base URL; when set the upload helper
                            returns ``{base}/{bucket}/{key}`` so the SPA can
                            <img src> the avatar directly. When empty the
                            caller must mint a presigned URL via
                            ``presigned_get_url`` and return that.

The provisioning script (``rag.scripts.phase28_bootstrap_minio``) creates the
bucket once; this module does **not** auto-create buckets at runtime.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

import aioboto3
from botocore.config import Config

from rag.config import settings


def _session() -> aioboto3.Session:
    """Build an aioboto3 session bound to the configured Minio credentials."""
    return aioboto3.Session(
        aws_access_key_id=settings.minio_access_key,
        aws_secret_access_key=settings.minio_secret_key,
        region_name=settings.minio_region,
    )


@asynccontextmanager
async def s3_client() -> AsyncIterator[Any]:
    """Yield an aioboto3 S3 client bound to the Minio endpoint.

    ``Config(signature_version="s3v4")`` is required for Minio presigned URLs
    to verify correctly. ``addressing_style="path"`` keeps the bucket name in
    the URL path rather than as a subdomain, which Minio (no DNS magic)
    needs.
    """
    session = _session()
    # aioboto3's overload registry doesn't model the Config kwarg well in
    # strict mode; the runtime call is correct and exercised by the avatar
    # test suite (moto S3 backend).
    async with session.client(  # type: ignore[call-overload]
        "s3",
        endpoint_url=settings.minio_endpoint,
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": "path"},
        ),
    ) as client:
        yield client


async def put_object(
    *,
    bucket: str,
    key: str,
    body: bytes,
    content_type: str,
) -> None:
    """Upload ``body`` to ``s3://{bucket}/{key}`` with the given content-type."""
    async with s3_client() as client:
        await client.put_object(
            Bucket=bucket,
            Key=key,
            Body=body,
            ContentType=content_type,
        )


async def ensure_bucket(bucket: str) -> bool:
    """Create ``bucket`` if it does not exist. Idempotent.

    Returns True if the bucket was created in this call, False if it was
    already present. Used by Phase 32 product setup and any future
    bucket-bootstrap path so the runtime does not need pre-provisioning
    when running in a fresh environment.
    """
    async with s3_client() as client:
        try:
            await client.head_bucket(Bucket=bucket)
            return False
        except Exception:  # noqa: BLE001 — head_bucket raises ClientError on 404
            pass
        await client.create_bucket(Bucket=bucket)
        return True


async def delete_object(*, bucket: str, key: str) -> None:
    """Delete ``s3://{bucket}/{key}``. Idempotent: no error if the key is absent."""
    async with s3_client() as client:
        await client.delete_object(Bucket=bucket, Key=key)


async def presigned_get_url(
    *,
    bucket: str,
    key: str,
    expires_in: int = 3600,
) -> str:
    """Mint a short-lived presigned GET URL for ``s3://{bucket}/{key}``."""
    async with s3_client() as client:
        url = await client.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket, "Key": key},
            ExpiresIn=expires_in,
        )
        return str(url)


def public_url_for(key: str, *, bucket: str | None = None) -> str | None:
    """Return a stable public URL for ``key`` or ``None`` when no CDN is set.

    Composes ``{minio_public_base_url}/{bucket}/{key}``. The bootstrap script
    sets the bucket's anonymous-read policy when ``--public`` is passed so
    the resulting URL renders without a presigned signature. Defaults to the
    avatar bucket for backwards compatibility; Phase 32 callers pass the
    products bucket explicitly.
    """
    base = settings.minio_public_base_url.rstrip("/")
    if not base:
        return None
    bucket_name = bucket if bucket is not None else settings.minio_bucket_avatars
    return f"{base}/{bucket_name}/{key}"
