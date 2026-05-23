"""Phase 28 Part 2 — bootstrap script smoke + idempotency tests.

Pointed at an in-process moto S3 server. Confirms:

    * First run creates the bucket.
    * Second run is idempotent (created=False).
    * --public applies an anonymous-read policy that GetBucketPolicy echoes.
    * --dry-run never touches the server.
"""

from __future__ import annotations

import asyncio
import json
import socket
from contextlib import contextmanager
from typing import Iterator

import pytest


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@contextmanager
def _moto_server() -> Iterator[str]:
    from moto.server import ThreadedMotoServer

    port = _free_port()
    server = ThreadedMotoServer(ip_address="127.0.0.1", port=port)
    server.start()
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.stop()


@pytest.fixture
def moto_settings(monkeypatch):
    from rag.config import settings

    with _moto_server() as endpoint:
        monkeypatch.setattr(settings, "minio_endpoint", endpoint)
        monkeypatch.setattr(settings, "minio_access_key", "test")
        monkeypatch.setattr(settings, "minio_secret_key", "test-secret")
        monkeypatch.setattr(
            settings, "minio_bucket_avatars", "nexus-avatars-bootstrap-test"
        )
        yield settings


def test_bootstrap_creates_bucket(moto_settings):
    from rag.scripts.phase28_bootstrap_minio import bootstrap

    result = asyncio.run(
        bootstrap(
            bucket=moto_settings.minio_bucket_avatars,
            public=False,
            dry_run=False,
        )
    )
    assert result.created is True
    assert result.public_policy_applied is False
    assert result.bucket == moto_settings.minio_bucket_avatars


def test_bootstrap_is_idempotent(moto_settings):
    from rag.scripts.phase28_bootstrap_minio import bootstrap

    asyncio.run(
        bootstrap(
            bucket=moto_settings.minio_bucket_avatars,
            public=False,
            dry_run=False,
        )
    )
    result = asyncio.run(
        bootstrap(
            bucket=moto_settings.minio_bucket_avatars,
            public=False,
            dry_run=False,
        )
    )
    assert result.created is False


def test_bootstrap_public_policy_applied(moto_settings):
    from rag.scripts.phase28_bootstrap_minio import bootstrap
    from rag.services.object_store import s3_client

    asyncio.run(
        bootstrap(
            bucket=moto_settings.minio_bucket_avatars,
            public=True,
            dry_run=False,
        )
    )

    async def _read_policy() -> dict:
        async with s3_client() as client:
            resp = await client.get_bucket_policy(
                Bucket=moto_settings.minio_bucket_avatars
            )
            return json.loads(resp["Policy"])

    policy = asyncio.run(_read_policy())
    stmts = policy["Statement"]
    assert any(
        s["Action"] == ["s3:GetObject"] and s["Effect"] == "Allow"
        for s in stmts
    )


def test_bootstrap_dry_run_skips_minio(moto_settings):
    """Dry-run never calls Minio. Use a bucket name unique to this test so
    moto's process-global backend state from sibling tests can't bleed in."""
    import uuid as _uuid

    from rag.scripts.phase28_bootstrap_minio import bootstrap
    from rag.services.object_store import s3_client
    from botocore.exceptions import ClientError

    bucket = f"dry-run-only-{_uuid.uuid4().hex[:8]}"

    result = asyncio.run(
        bootstrap(bucket=bucket, public=True, dry_run=True)
    )
    assert result.created is False
    assert result.public_policy_applied is False

    async def _bucket_absent() -> bool:
        async with s3_client() as client:
            try:
                await client.head_bucket(Bucket=bucket)
                return False
            except ClientError:
                return True

    assert asyncio.run(_bucket_absent()) is True
