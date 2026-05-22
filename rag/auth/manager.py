"""UserManager — fastapi-users lifecycle hooks (register/login/reset).

Logs ``user.register`` and ``user.login`` events so the v1 ``logs`` router
surface keeps observability parity with the legacy admin password flow.
"""

from __future__ import annotations

import logging
import uuid
from typing import Optional

from fastapi import Depends, Request
from fastapi_users import BaseUserManager, UUIDIDMixin
from fastapi_users.db import SQLAlchemyUserDatabase

from rag.auth.db import get_user_db
from rag.config import settings
from rag.database.models import User

_log = logging.getLogger(__name__)


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

    async def on_after_login(
        self,
        user: User,
        request: Optional[Request] = None,
        response=None,  # noqa: ANN001 -- fastapi-users protocol
    ) -> None:
        _log.info("user.login user_id=%s", str(user.id))


async def get_user_manager(
    user_db: SQLAlchemyUserDatabase = Depends(get_user_db),
):
    yield UserManager(user_db)
