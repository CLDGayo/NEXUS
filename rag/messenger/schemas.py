"""Pydantic schemas for the Phase 2 Messenger webhook surface.

The orchestrator (n8n / Make) is expected to have already parsed the raw
Facebook Graph API webhook and to forward a flat, normalized payload.
Schema drift here is rejected with HTTP 422 by FastAPI before any
downstream budget is spent.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Channel = Literal["messenger", "instagram", "whatsapp"]


class InboundMessage(BaseModel):
    """Forwarded user message from the upstream orchestrator."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    user_id: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description="Channel-scoped PSID or equivalent stable user identifier.",
    )
    message_text: str = Field(..., min_length=1, max_length=2000)
    timestamp: int = Field(
        ..., ge=0, description="Unix epoch seconds at message receipt by the orchestrator."
    )
    channel: Channel = Field(default="messenger")
    page_id: str | None = Field(default=None, max_length=64)
    correlation_id: str | None = Field(
        default=None,
        max_length=128,
        description="Idempotency key supplied by the orchestrator. Echoed back in the ack.",
    )
    outbound_url: str | None = Field(
        default=None,
        max_length=2048,
        description=(
            "Per-request override for the n8n / Make webhook the reply should be "
            "POSTed to. Falls back to MAKE_WEBHOOK_URL env when omitted."
        ),
    )


class InboundAck(BaseModel):
    """Synchronous acknowledgment returned to the orchestrator.

    Phase 2 returns a mock reply directly. Phase 8 switches to a fast 202
    + background dispatch + outbound Graph API call via the worker.
    """

    model_config = ConfigDict(extra="forbid")

    status: Literal["accepted", "rejected", "duplicate"]
    correlation_id: str
    reply_text: str | None = None
    latency_ms: int
    received_at: int


class OptOutRequest(BaseModel):
    """Data-deletion intent forwarded by the orchestrator on user request."""

    model_config = ConfigDict(extra="forbid")

    user_id: str = Field(..., min_length=1, max_length=64)
    channel: Channel = Field(default="messenger")
    correlation_id: str | None = Field(default=None, max_length=128)


class OptOutAck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["accepted"]
    correlation_id: str
    received_at: int


class HealthResponse(BaseModel):
    status: Literal["ok"]
    service: str
    version: str
