"""SQLAlchemy ORM models for the ``app`` Postgres schema.

Phase 27 Part 1 shipped:
    * ``app.users`` — fastapi-users default columns + display_name + profile_image_url.
    * ``app.access_token`` — reserved for fastapi-users' ``DatabaseStrategy``;
      we use ``JWTStrategy`` today (stateless), but ship the table now so
      Part 2 can flip without a migration.
    * ``app.chat_sessions`` — server-issued session_id PK, FK to users.id.
      Every chat turn looks up this row to enforce tenant ownership before
      LangGraph is invoked.

Phase 29 adds:
    * ``app.tenants`` — top-level workspace boundary (Hunter, Akiro, ...).
    * ``app.tenant_users`` — many-to-many: users may belong to many tenants
      with a per-row role (``owner`` | ``member``).
    * ``ChatSession.tenant_id`` — every session is now tenant-scoped.

Phase 29.2 adds:
    * ``app.messenger_page_tenants`` — maps inbound Meta page ids to the
      owning tenant so the Messenger webhook can lock each turn to the
      correct workspace before the orchestrator runs.

Phase 30.1 promotes the last five SQLite-resident tables to Postgres:
    * ``app.conversations`` / ``app.messages`` — chat memory, UUID-keyed
      with strict ``user_id`` / ``tenant_id`` FKs (CASCADE on user delete).
    * ``app.api_tokens`` — programmatic bearer tokens; user-scoped only
      (tenant scoping deferred to a later phase).
    * ``app.integrations`` — outbound provider config with JSONB payload.
    * ``app.settings`` — global typed KV store with JSONB values.

Phase 31 closes the cross-tenant data leak:
    * ``app.documents`` / ``app.document_links`` — per-tenant document
      registry that replaces the global ``nexus_graph.db`` SQLite store.
    * ``app.api_tokens.tenant_id`` / ``app.integrations.tenant_id`` —
      now NOT NULL FKs, every admin-class row is owned by exactly one
      tenant and the ``require_owner`` dependency enforces the access
      check.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi_users.db import SQLAlchemyBaseUserTableUUID
from fastapi_users_db_sqlalchemy.access_token import SQLAlchemyBaseAccessTokenTableUUID
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
    true,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from rag.database.base import Base


class User(SQLAlchemyBaseUserTableUUID, Base):
    __tablename__ = "users"

    display_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    profile_image_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # Phase 54 — per-user UI language (BCP-47 base code, e.g. "en", "ja",
    # "fil"). Validated against the supported set in auth/schemas.py.
    language: Mapped[str] = mapped_column(
        String(8), nullable=False, server_default="en"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AccessToken(SQLAlchemyBaseAccessTokenTableUUID, Base):
    __tablename__ = "access_token"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("app.users.id", ondelete="CASCADE"), nullable=False
    )


class Tenant(Base):
    """Top-level workspace boundary. Every data row is scoped to one tenant.

    The ``slug`` is the human-readable handle used inside Qdrant payloads
    and SQLite ``tenant_id`` columns (the UUID would bloat every chunk
    payload by ~50 bytes). The pair (id, slug) is 1:1 and both unique.
    """

    __tablename__ = "tenants"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    slug: Mapped[str] = mapped_column(
        String(120), nullable=False, unique=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # Phase 52 — Workspace Lifecycle & Danger Zone.
    # ``avatar_url`` is either a stable public HTTPS URL (CDN) or the
    # ``minio:tenant/{id}.webp`` sentinel used by the profile avatar system.
    # ``archived_at`` is the soft-delete timestamp; data routes return 403
    # ``workspace_archived`` when this is non-null so active members cannot
    # continue using a suspended workspace.
    avatar_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Phase 56 — Google SSO domain auto-join. When set (e.g. "acmewidgets.com")
    # an OAuth login whose *verified* email ends in this domain creates a
    # pending domain_join_request instead of provisioning a brand-new
    # workspace. Nullable: most tenants never opt in.
    domain: Mapped[str | None] = mapped_column(String(253), nullable=True, index=True)

    # Phase 45 — Lifecycle Persona Engine. Carries the full ai_settings blob
    # (scenario_prompts, active_nodes, model_params). Default is the empty-
    # string / True / None shape so existing tenants behave byte-identically
    # to pre-Phase-45. Never mutated mid-run; loaded fresh at graph entry.
    ai_settings: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text(
            '\'{"version":1,"scenario_prompts":{"introduction":"","core_behavior":"",'
            '"checkout_transition":"","human_handoff":""},'
            '"active_nodes":{"sentiment_analysis":true,"research_mode":true,'
            '"inject_product_context":true,"build_carousel":true,'
            '"sdr_persona":true,"hitl_handover":true},'
            '"model_params":{"temperature":null,"max_tokens":null,"model_choice":null}}\'::jsonb'
        ),
    )


class TenantUser(Base):
    """Membership table — composite PK (tenant_id, user_id).

    Phase 50 RBAC tiers (``role``):
        * ``owner``  — created/transferred-in; full control incl. archive,
          transfer, hard-delete.
        * ``admin``  — manage members, settings, integrations; cannot delete
          or transfer the workspace.
        * ``member`` — standard user (chat, read, upload).

    The CHECK constraint pins ``role`` to that closed set so a stray write
    can never mint an out-of-band role.
    """

    __tablename__ = "tenant_users"
    __table_args__ = (
        CheckConstraint(
            "role IN ('owner', 'admin', 'member')",
            name="ck_app_tenant_users_role",
        ),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("app.tenants.id", ondelete="CASCADE"),
        primary_key=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("app.users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="owner")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class TenantInvite(Base):
    """Phase 51 — one row per outstanding invite (email-targeted or open code).

    token_hash is SHA-256(raw_token). The raw token is returned once at
    creation time and is never stored. Default expiry: 7 days.
    """

    __tablename__ = "tenant_invites"
    __table_args__ = (
        CheckConstraint(
            "role IN ('owner', 'admin', 'member')",
            name="ck_tenant_invites_role",
        ),
        CheckConstraint(
            "status IN ('pending', 'accepted', 'revoked')",
            name="ck_tenant_invites_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("app.tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    email: Mapped[str | None] = mapped_column(String(256), nullable=True)
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="member")
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    invited_by: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("app.users.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class MessengerPageTenant(Base):
    """Phase 29.2 — bind a Facebook/Messenger page id to its owning tenant.

    The inbound webhook reads this table for every coalesced event group
    before scheduling the orchestrator background task. A missing row is
    operational state — the event is dropped with a
    ``messenger.event.no_tenant_mapping`` log; we never silently route
    the message to a default tenant (that would re-open the cross-tenant
    leak Phase 29 closes).
    """

    __tablename__ = "messenger_page_tenants"
    __table_args__ = (
        CheckConstraint(
            "token_status IN ('active', 'expired', 'revoked', 'invalid')",
            name="ck_mpt_token_status",
        ),
        CheckConstraint(
            "sync_status IN ('ok', 'stale', 'error')",
            name="ck_mpt_sync_status",
        ),
    )

    facebook_page_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("app.tenants.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # ---- Phase 55 — Page metadata sync (name / about / picture) ----
    # The webhook is a *signal*; the sync worker fetches the authoritative
    # values from the Graph API with the page's own token and writes them here.
    page_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    page_about: Mapped[str | None] = mapped_column(Text, nullable=True)
    profile_picture_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    # Fernet ciphertext (rag.crypto) — the per-page access token used to read
    # metadata. Never stored plaintext. Nullable until the page is connected
    # via the OAuth-backed bind flow.
    page_access_token_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    token_status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="active"
    )
    token_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Fields this page is subscribed to on the app webhook (audit/debug only).
    subscribed_fields: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True
    )
    last_synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    sync_status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="ok"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class FacebookUserToken(Base):
    """Phase 55 — per-tenant long-lived Facebook *user* token (~60 days).

    Distinct from the per-page token on ``MessengerPageTenant``: the user
    token is what mints fresh page tokens and (re)subscribes webhook fields
    when a page token expires. One row per tenant; the ciphertext is Fernet
    (rag.crypto).
    """

    __tablename__ = "facebook_user_tokens"
    __table_args__ = (
        CheckConstraint(
            "token_status IN ('active', 'expired', 'revoked', 'invalid')",
            name="ck_fut_token_status",
        ),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("app.tenants.id", ondelete="CASCADE"), primary_key=True
    )
    fb_user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    user_token_enc: Mapped[str] = mapped_column(Text, nullable=False)
    scopes: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    token_status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="active"
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class OAuthAccount(Base):
    """Phase 56 — third-party identity link (one row per provider account).

    Plain model (not fastapi-users' base) so the FK targets ``app.users.id``
    and the row lives in the ``app`` schema. ``(oauth_name, account_id)`` is
    unique so the same Google ``sub`` can never fan out to two NEXUS users.
    ``access_token`` is Fernet ciphertext (rag.crypto).
    """

    __tablename__ = "oauth_accounts"
    __table_args__ = (
        UniqueConstraint("oauth_name", "account_id", name="uq_oauth_provider_account"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("app.users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    oauth_name: Mapped[str] = mapped_column(String(100), nullable=False)
    account_id: Mapped[str] = mapped_column(String(320), nullable=False)
    account_email: Mapped[str] = mapped_column(String(320), nullable=False)
    access_token_enc: Mapped[str] = mapped_column(Text, nullable=False)
    refresh_token_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class OAuthState(Base):
    """Phase 56 — single-use CSRF state + replay nonce + PKCE verifier.

    Persisted server-side *before* the redirect to Google and consumed exactly
    once on the callback. Short TTL (``oauth_state_ttl_seconds``). ``state`` is
    the URL-visible random token; ``nonce`` is bound into the id_token and
    re-checked; ``code_verifier`` proves the PKCE exchange.
    """

    __tablename__ = "oauth_states"

    state: Mapped[str] = mapped_column(String(64), primary_key=True)
    nonce: Mapped[str] = mapped_column(String(64), nullable=False)
    code_verifier: Mapped[str] = mapped_column(String(128), nullable=False)
    invite_token: Mapped[str | None] = mapped_column(String(128), nullable=True)
    redirect_after: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    consumed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class RefreshToken(Base):
    """Phase 56 — rotating refresh token backing the HttpOnly session cookie.

    Only the SHA-256 hash is stored (same discipline as TenantInvite). Each
    use rotates: the old row is marked ``revoked_at`` and a fresh row issued,
    so a stolen-then-replayed token is detectable and revocable.
    """

    __tablename__ = "refresh_tokens"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("app.users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class DomainJoinRequest(Base):
    """Phase 56 — pending domain auto-join awaiting admin approval.

    Created when an OAuth user's verified email domain matches a
    ``tenant.domain`` but they have no invite/membership. A manager approves
    or rejects; approval mints the ``TenantUser`` membership.
    """

    __tablename__ = "domain_join_requests"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'approved', 'rejected')",
            name="ck_djr_status",
        ),
        UniqueConstraint("tenant_id", "user_id", name="uq_djr_tenant_user"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("app.tenants.id", ondelete="CASCADE"), index=True, nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("app.users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    email_domain: Mapped[str] = mapped_column(String(253), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="pending"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    decided_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("app.users.id", ondelete="SET NULL"), nullable=True
    )
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    session_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("app.users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("app.tenants.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    title: Mapped[str | None] = mapped_column(String(256), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_used_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class Conversation(Base):
    """Phase 30.1 — chat conversation root, replaces the legacy SQLite
    ``conversations`` table. UUID PK so the values from the SQLite file
    transfer 1:1 during ``0004_phase30_sqlite_to_pg``.
    """

    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("app.users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("app.tenants.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class Message(Base):
    """Phase 30.1 — chat message row. ``sources`` is the citation block
    streamed alongside assistant turns; stored as JSONB so dashboard
    aggregates can introspect without re-parsing strings.
    """

    __tablename__ = "messages"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("app.conversations.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("app.users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("app.tenants.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    sources: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ApiToken(Base):
    """Phase 30.1 — programmatic bearer tokens. The hashed value is the
    only authoritative form; ``prefix`` is shown in the UI for operator
    recognition.

    Phase 31 hardening:
        * ``user_id`` is no longer optional. Pre-Phase-28 NULL rows are
          dropped by the ``0005_phase31_security_and_docs`` migration.
        * ``tenant_id`` is a NOT NULL FK so every token belongs to a
          single workspace. ``require_owner`` filters every router query
          by ``tenant_id``.
    """

    __tablename__ = "api_tokens"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    prefix: Mapped[str] = mapped_column(String(32), nullable=False)
    scopes_csv: Mapped[str] = mapped_column(String(512), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("app.users.id", ondelete="CASCADE"),
        index=True,
        nullable=True,
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("app.tenants.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )


class Integration(Base):
    """Phase 30.1 — outbound provider config (Slack, Discord, Messenger,
    webhook, ...). ``config`` carries provider-specific payloads as JSONB.

    Phase 31 — ``tenant_id`` is now a NOT NULL FK; every integration is
    owned by a single workspace. ``require_owner`` filters every router
    query by ``tenant_id``.
    """

    __tablename__ = "integrations"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("app.tenants.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    type: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    events_csv: Mapped[str] = mapped_column(
        String(1024), nullable=False, server_default=""
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=true()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    last_fired_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_status: Mapped[str | None] = mapped_column(String(256), nullable=True)


class Document(Base):
    """Phase 31 — per-tenant document registry.

    Replaces the filesystem walker that ``GET /api/documents`` relied on,
    closing the horizontal data leak where every tenant could see every
    other tenant's note paths. Rows are upserted by the ingest pipeline,
    one per ``(tenant_id, file)`` pair; ``archived_at`` is the soft-delete
    flag flipped by ``POST /api/documents/archive``.
    """

    __tablename__ = "documents"
    __table_args__ = (
        UniqueConstraint("tenant_id", "file", name="uq_app_documents_tenant_file"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("app.tenants.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    file: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    folder: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    aliases: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    source_kind: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="note"
    )
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    chunk_total: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    modified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    indexed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class DocumentLink(Base):
    """Phase 31 — per-tenant wikilink edges.

    Replaces ``vault_links`` from the legacy SQLite ``nexus_graph.db``.
    ``dst_document_id`` is resolved late (in a second pass after every
    file in a batch has registered its title + outbound links) so a link
    written before its target is not lost.
    """

    __tablename__ = "document_links"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("app.tenants.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    src_document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("app.documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    dst_target: Mapped[str] = mapped_column(Text, nullable=False)
    dst_document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("app.documents.id", ondelete="SET NULL"),
        nullable=True,
    )
    anchor: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    alias: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Product(Base):
    """Phase 32 — tenant-scoped product catalog row.

    The pair ``(tenant_id, slug)`` is unique so each workspace owns its
    URL-friendly handle independently. ``price_cents`` is the integer
    minor-unit price (cents for USD, sen for JPY, ...); ``currency`` is
    the ISO-4217 alpha code. ``quantity`` is the only stock-out signal
    consulted by the carousel formatter — a row with ``is_active=False``
    or ``quantity=0`` is excluded by the orchestrator's ``enrich_products``
    SQL filter and its Qdrant point is removed by ``products.sync``.
    """

    __tablename__ = "products"
    __table_args__ = (
        UniqueConstraint("tenant_id", "slug", name="uq_app_products_tenant_slug"),
        CheckConstraint("price_cents >= 0", name="ck_app_products_price_nonneg"),
        CheckConstraint("quantity >= 0", name="ck_app_products_qty_nonneg"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("app.tenants.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    slug: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    price_cents: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    currency: Mapped[str] = mapped_column(
        String(3), nullable=False, server_default="USD"
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=true()
    )
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    extra_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    images: Mapped[list["ProductImage"]] = relationship(
        "ProductImage",
        back_populates="product",
        cascade="all, delete-orphan",
        order_by="ProductImage.display_order",
        lazy="selectin",
    )


class FacebookAutomation(Base):
    """Phase 57 — deterministic keyword-triggered Private Reply automation.

    One row per keyword rule per page. When a visitor comments on a Page
    post and their text matches ``trigger_keyword`` (exact or contains),
    the worker sends a pre-configured ``reply_payload`` as a private reply
    instead of routing to the LLM triage engine.

    Index on ``(page_id, is_active)`` keeps the per-comment lookup cheap.
    """

    __tablename__ = "facebook_automations"
    __table_args__ = (
        CheckConstraint(
            "match_type IN ('exact', 'contains')",
            name="ck_fba_match_type",
        ),
        {"schema": "app"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("app.tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    page_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    trigger_keyword: Mapped[str] = mapped_column(String(255), nullable=False)
    match_type: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="exact"
    )
    reply_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=true()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ProcessedFbComment(Base):
    """Phase 57 — idempotency lock table for comment-to-message jobs.

    A row is inserted (comment_id as PK) before any send attempt. An
    ``IntegrityError`` on insert means a duplicate webhook — the job is
    silently dropped without a second send.
    """

    __tablename__ = "processed_fb_comments"
    __table_args__ = {"schema": "app"}

    comment_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    page_id: Mapped[str] = mapped_column(String(64), nullable=False)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("app.tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    processed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ProductImage(Base):
    """Phase 32 — ordered image attachment for a product.

    ``storage_key`` is the canonical MinIO object key; ``image_url`` is
    the optional cached public URL (filled when ``MINIO_PUBLIC_BASE_URL``
    is set; otherwise the carousel formatter regenerates a 1h presigned
    URL on every dispatch). The ``(product_id, display_order)`` unique
    constraint forces gap-free ordering; the router uses a negative-offset
    swap inside a transaction to reassign positions safely under
    concurrent edits.
    """

    __tablename__ = "product_images"
    __table_args__ = (
        UniqueConstraint(
            "product_id", "display_order", name="uq_app_product_images_order"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    product_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("app.products.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    storage_key: Mapped[str] = mapped_column(Text, nullable=False)
    image_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    display_order: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default="0"
    )
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    content_type: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default="image/webp"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    product: Mapped[Product] = relationship("Product", back_populates="images")


class Setting(Base):
    """Phase 30.1 — global typed KV settings store. ``value`` is JSONB
    since legacy SQLite already stored every entry as a JSON-encoded
    scalar; the column type matches what's read/written by
    ``rag.settings_service``.
    """

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[Any] = mapped_column(JSONB, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
