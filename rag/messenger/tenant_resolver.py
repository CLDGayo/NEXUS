"""Phase 29.2 — resolve an inbound Meta page id to its owning tenant.

The Messenger webhook (``rag.messenger.routers.webhook``) calls
:func:`resolve_tenant_for_page` once per coalesced event group. A hit
returns the full ``Tenant`` row so the caller can read both the UUID
(for audit / cross-system correlation) and the slug (the value
``NexusState.tenant_id`` actually carries into the retrieval nodes).

A miss is operational state, not a bug: the webhook drops the event
with a ``messenger.event.no_tenant_mapping`` log line. Returning ``None``
keeps the resolver free of HTTP semantics and lets the caller decide
whether to drop, queue, or fall back.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from rag.database.models import MessengerPageTenant, Tenant


async def resolve_tenant_for_page(
    db: AsyncSession, facebook_page_id: str
) -> Tenant | None:
    """Map ``facebook_page_id`` → owning :class:`Tenant`, or ``None``.

    Joins ``messenger_page_tenants`` → ``tenants`` in a single query so
    the caller has both ``tenant.id`` and ``tenant.slug`` available
    without a second round-trip.
    """

    if not facebook_page_id:
        return None
    stmt = (
        select(Tenant)
        .join(
            MessengerPageTenant,
            MessengerPageTenant.tenant_id == Tenant.id,
        )
        .where(MessengerPageTenant.facebook_page_id == facebook_page_id)
    )
    return (await db.execute(stmt)).scalar_one_or_none()
