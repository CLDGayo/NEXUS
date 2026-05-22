"""fastapi-users authentication backend wiring.

Transport: ``BearerTransport`` (Authorization header) — matches the existing
SPA which already sends ``Authorization: Bearer <jwt>``.
Strategy: ``JWTStrategy`` with ``lifetime_seconds=3600`` and the secret
sourced from ``settings.nexus_jwt_secret`` (env var ``NEXUS_JWT_SECRET``).
"""

from __future__ import annotations

import uuid

from fastapi_users import FastAPIUsers
from fastapi_users.authentication import (
    AuthenticationBackend,
    BearerTransport,
    JWTStrategy,
)

from rag.auth.manager import get_user_manager
from rag.config import settings
from rag.database.models import User

bearer_transport = BearerTransport(tokenUrl="api/auth/jwt/login")


def get_jwt_strategy() -> JWTStrategy:
    secret = settings.nexus_jwt_secret or "test-nexus-jwt-secret"
    return JWTStrategy(secret=secret, lifetime_seconds=3600)


auth_backend = AuthenticationBackend(
    name="jwt",
    transport=bearer_transport,
    get_strategy=get_jwt_strategy,
)

fastapi_users = FastAPIUsers[User, uuid.UUID](get_user_manager, [auth_backend])

current_active_user = fastapi_users.current_user(active=True)
current_superuser = fastapi_users.current_user(active=True, superuser=True)
