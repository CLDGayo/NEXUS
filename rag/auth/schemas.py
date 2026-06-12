"""Pydantic schemas for fastapi-users register / read / update routes,
plus Phase 29 tenant CRUD."""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi_users import schemas
from pydantic import BaseModel, Field, field_validator


class UserRead(schemas.BaseUser[uuid.UUID]):
    display_name: str | None = None
    profile_image_url: str | None = None


class UserCreate(schemas.BaseUserCreate):
    display_name: str | None = None


class UserUpdate(schemas.BaseUserUpdate):
    display_name: str | None = None
    profile_image_url: str | None = None


# --------------------------------------------------------------------------
# Phase 29 — tenants
# --------------------------------------------------------------------------


class TenantCreate(BaseModel):
    """Body for ``POST /api/tenants``.

    ``slug`` is optional — when absent the router derives it from ``name``
    via ``slugify_tenant_name`` (lowercase, hyphenated, ASCII-only). Limit
    the slug length so it fits comfortably inside Qdrant payload values
    (which we keep short to bound point storage).
    """

    name: str = Field(min_length=1, max_length=120)
    slug: str | None = Field(default=None, max_length=120)


class TenantRead(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    created_at: datetime
    # Role of the requesting user inside this tenant.
    role: str
    # Phase 50 — member count for the workspace master list. Optional so
    # single-tenant reads (POST/GET detail) can omit it cheaply.
    member_count: int | None = None
    # Phase 52 — Workspace Lifecycle & Danger Zone.
    avatar_url: str | None = None
    archived_at: datetime | None = None


class TenantUpdate(BaseModel):
    """Body for ``PATCH /api/tenants/{id}`` — name, slug, and avatar_url are
    all optional; at least one must be provided.

    Slug validation: lowercase URL-safe (a-z, 0-9, hyphen), 1–120 chars.
    """

    name: str | None = Field(default=None, min_length=1, max_length=120)
    slug: str | None = Field(default=None, min_length=1, max_length=120)
    avatar_url: str | None = None

    @field_validator("slug")
    @classmethod
    def slug_must_be_url_safe(cls, v: str | None) -> str | None:
        import re

        if v is None:
            return v
        v = v.strip().lower()
        if not re.fullmatch(r"[a-z0-9][a-z0-9\-]*[a-z0-9]|[a-z0-9]", v):
            raise ValueError(
                "slug must contain only lowercase letters, digits, and hyphens, "
                "and must not start or end with a hyphen"
            )
        return v


# --------------------------------------------------------------------------
# Phase 50 — workspace member management (RBAC)
# --------------------------------------------------------------------------

_ROLE_VALUES = ("owner", "admin", "member")


class MemberRead(BaseModel):
    """One row in the workspace Members tab."""

    user_id: uuid.UUID
    email: str
    display_name: str | None = None
    role: str
    joined_at: datetime


class MemberRoleUpdate(BaseModel):
    """Body for ``PATCH /api/tenants/{id}/members/{user_id}``."""

    role: str = Field(pattern="^(owner|admin|member)$")
