"""Phase 28 Part 2 — one-time Minio bootstrap for the avatar bucket.

Run me ONCE per environment before the avatar router starts handling
uploads. The script:

    1. Creates the bucket named by ``--bucket`` (default
       ``settings.minio_bucket_avatars``) — idempotent: existing buckets are
       left alone.
    2. When ``--public`` is passed, applies an anonymous-read bucket policy
       so the SPA can render avatars via the public CDN base URL stored in
       ``profile_image_url``. Without ``--public`` the bucket stays private
       and clients must mint presigned URLs via ``GET /api/users/me/avatar/url``.

Examples:

    # Local dev (docker compose) — bucket goes public so the SPA can <img>
    # straight at the minio service's published port.
    uv run python -m rag.scripts.phase28_bootstrap_minio --public

    # VPS — bucket goes public; the media.nexus.gayo-sphere.cloud nginx
    # subdomain (separately provisioned) proxies through to :9000.
    uv run python -m rag.scripts.phase28_bootstrap_minio --public

    # Dry-run: report what would happen without mutating Minio.
    uv run python -m rag.scripts.phase28_bootstrap_minio --dry-run

Exit codes:
    0 — success (bucket exists and policy matches request)
    1 — Minio unreachable or auth failed
    2 — unexpected exception during bucket create / policy put
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from dataclasses import dataclass
from typing import Any

from botocore.exceptions import ClientError, EndpointConnectionError

from rag.config import settings
from rag.services.object_store import s3_client

_log = logging.getLogger("phase28_bootstrap_minio")


@dataclass(frozen=True)
class BootstrapResult:
    bucket: str
    created: bool
    public_policy_applied: bool
    endpoint: str


def _public_read_policy(bucket: str) -> dict[str, object]:
    """Build a minimal s3:GetObject anonymous policy for ``bucket``.

    Matches the AWS S3 / Minio public-read policy shape — Minio's `mc
    anonymous set download` produces an equivalent document. Limited to
    GetObject so writes still require credentials.
    """
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "AllowPublicRead",
                "Effect": "Allow",
                "Principal": {"AWS": ["*"]},
                "Action": ["s3:GetObject"],
                "Resource": [f"arn:aws:s3:::{bucket}/*"],
            }
        ],
    }


async def _ensure_bucket(client: Any, bucket: str) -> bool:
    """Create ``bucket`` if absent. Returns True when a creation actually ran."""
    try:
        await client.head_bucket(Bucket=bucket)
        return False
    except ClientError as exc:
        status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        if status not in {404, 403}:
            # 403 surfaces on some Minio versions when the bucket is owned by
            # another principal; we treat it the same as "not found" and let
            # create_bucket either succeed or surface a clearer error.
            raise

    await client.create_bucket(Bucket=bucket)
    return True


async def _apply_public_policy(client: Any, bucket: str) -> None:
    policy = _public_read_policy(bucket)
    await client.put_bucket_policy(
        Bucket=bucket,
        Policy=json.dumps(policy),
    )


async def bootstrap(bucket: str, public: bool, dry_run: bool) -> BootstrapResult:
    if dry_run:
        _log.info(
            "dry-run bucket=%s endpoint=%s public=%s — no Minio calls issued",
            bucket,
            settings.minio_endpoint,
            public,
        )
        return BootstrapResult(
            bucket=bucket,
            created=False,
            public_policy_applied=False,
            endpoint=settings.minio_endpoint,
        )

    async with s3_client() as client:
        created = await _ensure_bucket(client, bucket)
        if created:
            _log.info("bucket created bucket=%s", bucket)
        else:
            _log.info("bucket already exists bucket=%s", bucket)

        if public:
            await _apply_public_policy(client, bucket)
            _log.info("public-read policy applied bucket=%s", bucket)

        return BootstrapResult(
            bucket=bucket,
            created=created,
            public_policy_applied=public,
            endpoint=settings.minio_endpoint,
        )


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="phase28_bootstrap_minio",
        description="One-time Minio bucket provisioner for Nexus avatars.",
    )
    parser.add_argument(
        "--bucket",
        default=settings.minio_bucket_avatars,
        help="Bucket name (default: settings.minio_bucket_avatars).",
    )
    parser.add_argument(
        "--public",
        action="store_true",
        help="Apply anonymous-read bucket policy for public avatar URLs.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Log intended actions without touching Minio.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Emit DEBUG-level logs.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(list(sys.argv[1:] if argv is None else argv))
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    try:
        result = asyncio.run(bootstrap(args.bucket, args.public, args.dry_run))
    except EndpointConnectionError as exc:
        _log.error("minio unreachable endpoint=%s detail=%s", settings.minio_endpoint, exc)
        return 1
    except ClientError as exc:
        _log.error("minio client error detail=%s", exc)
        return 2
    except Exception as exc:  # pragma: no cover — last-resort logger
        _log.exception("unexpected error: %s", exc)
        return 2

    print(
        json.dumps(
            {
                "bucket": result.bucket,
                "created": result.created,
                "public_policy_applied": result.public_policy_applied,
                "endpoint": result.endpoint,
            }
        )
    )
    return 0


if __name__ == "__main__":  # pragma: no cover — CLI entrypoint
    raise SystemExit(main())
