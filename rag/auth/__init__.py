"""fastapi-users wiring for NEXUS Phase 27 Part 1.

Public surface re-exported here so route modules can import everything from
``rag.auth`` without reaching into the sub-modules.
"""

from rag.auth.config import (
    auth_backend,
    current_active_user,
    current_superuser,
    fastapi_users,
    get_jwt_strategy,
)
from rag.auth.schemas import (
    MemberRead,
    MemberRoleUpdate,
    TenantCreate,
    TenantRead,
    TenantUpdate,
    UserCreate,
    UserRead,
    UserUpdate,
)
from rag.auth.tenant import (
    get_current_tenant,
    list_tenants_for_user,
    slugify_tenant_name,
)

__all__ = [
    "auth_backend",
    "current_active_user",
    "current_superuser",
    "fastapi_users",
    "get_jwt_strategy",
    "get_current_tenant",
    "list_tenants_for_user",
    "slugify_tenant_name",
    "MemberRead",
    "MemberRoleUpdate",
    "TenantCreate",
    "TenantRead",
    "TenantUpdate",
    "UserCreate",
    "UserRead",
    "UserUpdate",
]
