"""UserManager — fastapi-users lifecycle hooks (register/login/reset).

Logs ``user.register`` and ``user.login`` events so the v1 ``logs`` router
surface keeps observability parity with the legacy admin password flow.

Phase 29 — ``on_after_register`` also provisions a personal tenant for the
new user (one row in ``app.tenants`` + one in ``app.tenant_users`` with
``role=owner``). Without this, every data-bearing endpoint would 403 the
freshly-registered user until they manually POST /api/tenants — a useless
onboarding cliff.
"""

from __future__ import annotations

import logging
import re
import uuid
from typing import Optional

from fastapi import Depends, Request
from fastapi_users import BaseUserManager, UUIDIDMixin
from fastapi_users.db import SQLAlchemyUserDatabase
from sqlalchemy.exc import IntegrityError

from rag.auth.db import get_user_db
from rag.config import settings
from rag.database.engine import get_sessionmaker
from rag.database.models import Tenant, TenantUser, User

# Inline slugifier — duplicated from ``rag.auth.tenant`` to dodge an import
# cycle (tenant.py depends on auth.config, which depends on manager.py).
_SLUG_SAFE_RE = re.compile(r"[^a-z0-9-]+")
_SLUG_HYPHEN_COLLAPSE_RE = re.compile(r"-{2,}")


def _slugify(name: str) -> str:
    candidate = name.strip().lower()
    candidate = _SLUG_SAFE_RE.sub("-", candidate)
    candidate = _SLUG_HYPHEN_COLLAPSE_RE.sub("-", candidate).strip("-")
    if not candidate:
        candidate = "tenant"
    return candidate[:120]

_log = logging.getLogger(__name__)

_MAX_PERSONAL_SLUG_BASE = 100  # leave room for the "-<short-uuid>" suffix


class UserManager(UUIDIDMixin, BaseUserManager[User, uuid.UUID]):
    reset_password_token_secret = ""  # set in __init__
    verification_token_secret = ""  # set in __init__

    def __init__(self, user_db: SQLAlchemyUserDatabase) -> None:
        super().__init__(user_db)
        secret = settings.nexus_jwt_secret or "test-nexus-jwt-secret"
        self.reset_password_token_secret = secret
        self.verification_token_secret = secret

    async def on_after_register(
        self, user: User, request: Optional[Request] = None
    ) -> None:
        _log.info(
            "user.register user_id=%s email=%s", str(user.id), user.email
        )
        await self._provision_personal_tenant(user)

    async def on_after_login(
        self,
        user: User,
        request: Optional[Request] = None,
        response=None,  # noqa: ANN001 -- fastapi-users protocol
    ) -> None:
        _log.info("user.login user_id=%s", str(user.id))

    @staticmethod
    def _candidate_slug(email: str) -> str:
        local = email.split("@", 1)[0]
        base = _slugify(f"personal-{local}")[:_MAX_PERSONAL_SLUG_BASE]
        return base or "personal"

    async def _provision_personal_tenant(self, user: User) -> None:
        """Create a personal tenant for the freshly-registered user.

        Idempotent — on slug collision, retry once with a short-uuid suffix
        so two users with the same email local-part still get a workspace.
        A failure here is logged but never propagated; the user can always
        POST /api/tenants manually later.
        """

        sessionmaker = get_sessionmaker()
        slug = self._candidate_slug(user.email)
        async with sessionmaker() as db:
            tenant = Tenant(
                name=f"{user.email}'s workspace",
                slug=slug,
            )
            db.add(tenant)
            try:
                await db.flush()
            except IntegrityError:
                # Slug collision (extremely rare). Fall back to a unique
                # suffixed slug. The previous transaction is dirty — open a
                # fresh session and retry.
                await db.rollback()
                suffix = uuid.uuid4().hex[:8]
                slug = f"{slug}-{suffix}"[:120]
                tenant = Tenant(
                    name=f"{user.email}'s workspace",
                    slug=slug,
                )
                db.add(tenant)
                try:
                    await db.flush()
                except IntegrityError as exc:
                    await db.rollback()
                    _log.warning(
                        "tenant.provision_failed user_id=%s slug=%s err=%s",
                        str(user.id),
                        slug,
                        exc,
                    )
                    return

            db.add(
                TenantUser(
                    tenant_id=tenant.id, user_id=user.id, role="owner"
                )
            )
            await db.commit()
            _log.info(
                "tenant.provision_personal user_id=%s tenant_id=%s slug=%s",
                str(user.id),
                str(tenant.id),
                slug,
            )


async def get_user_manager(
    user_db: SQLAlchemyUserDatabase = Depends(get_user_db),
):
    yield UserManager(user_db)
