"""Outbound payload schemas + builder for Phase 6.

The shape posted to n8n / Make is intentionally flat so the downstream
workflow can map fields into the Facebook Graph API without nested-path
gymnastics. Strict (``extra="forbid"``) so schema drift never silently
ships a malformed payload to production webhooks.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from rag.messenger.schemas import Channel, InboundMessage


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


class TokenUsage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt: int = Field(ge=0, default=0)
    completion: int = Field(ge=0, default=0)
    total: int = Field(ge=0, default=0)


class OutboundMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str | None = None
    tokens: TokenUsage = Field(default_factory=TokenUsage)
    latency_ms: int = Field(default=0, ge=0)
    generated_at: str = Field(default_factory=_now_iso)
    abstained: bool = False
    surface: str = "messenger"


class GenericTemplateButton(BaseModel):
    """Meta Generic Template button. ``web_url`` opens an external URL;
    ``postback`` echoes the payload back to the webhook.

    Meta hard limit: button title ≤ 20 chars.
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal["web_url", "postback"]
    title: str = Field(min_length=1, max_length=20)
    url: HttpUrl | None = None
    payload: str | None = None


class GenericTemplateElement(BaseModel):
    """One card in a Meta Generic Template carousel.

    Meta hard limits: title ≤ 80 chars, subtitle ≤ 80 chars, ≤ 3 buttons.
    """

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=80)
    subtitle: str | None = Field(default=None, max_length=80)
    image_url: HttpUrl | None = None
    default_action: dict[str, Any] | None = None
    buttons: list[GenericTemplateButton] = Field(
        default_factory=list, max_length=3
    )


class ProductCarouselBlock(BaseModel):
    """Phase 32 — product cards rendered as a Generic Template carousel.

    Meta hard limit: ≤ 10 elements per template message.
    """

    model_config = ConfigDict(extra="forbid")

    elements: list[GenericTemplateElement] = Field(min_length=1, max_length=10)


class ReplyBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Text became optional in Phase 32 so a pure-carousel reply (product
    # cards only, no preamble) can be dispatched. The webhook always sends
    # at least one of (text, carousel); the orchestrator enforces that.
    # min_length=1 preserves the Phase 6 invariant that empty strings are
    # rejected — pass ``None`` instead when you want no text.
    text: str | None = Field(default=None, min_length=1, max_length=2000)
    citations: list[str] = Field(default_factory=list)
    carousel: ProductCarouselBlock | None = None
    requires_human_handover: bool = False
    handover_reason: str | None = None
    uncertainty_score: float = Field(default=0.0, ge=0.0, le=1.0)
    validator_failures: list[str] = Field(default_factory=list)


class OutboundPayload(BaseModel):
    """The exact JSON body POSTed to the n8n / Make outbound webhook."""

    model_config = ConfigDict(extra="forbid")

    correlation_id: str = Field(min_length=1, max_length=128)
    user_id: str = Field(min_length=1, max_length=64)
    channel: Channel
    page_id: str | None = None
    reply: ReplyBlock
    metadata: OutboundMetadata


def build_outbound_payload(
    *,
    inbound: InboundMessage,
    correlation_id: str,
    reply_text: str,
    graph_result: dict[str, Any],
) -> OutboundPayload:
    """Compose the outbound payload from inbound + final graph state.

    Defensive about missing graph_result keys — the graph may have failed
    early (LLM error, guardrails abstention) but the payload contract
    still has to be filled.
    """

    tokens = TokenUsage(
        prompt=int(graph_result.get("llm_prompt_tokens", 0) or 0),
        completion=int(graph_result.get("llm_completion_tokens", 0) or 0),
        total=int(graph_result.get("llm_total_tokens", 0) or 0),
    )

    carousel_block: ProductCarouselBlock | None = None
    carousel = graph_result.get("product_carousel")
    if isinstance(carousel, ProductCarouselBlock):
        carousel_block = carousel
    elif isinstance(carousel, dict) and carousel.get("elements"):
        try:
            carousel_block = ProductCarouselBlock.model_validate(carousel)
        except Exception:  # noqa: BLE001 — defensive; fall back to text
            carousel_block = None

    return OutboundPayload(
        correlation_id=correlation_id,
        user_id=inbound.user_id,
        channel=inbound.channel,
        page_id=inbound.page_id,
        reply=ReplyBlock(
            text=reply_text or None,
            citations=list(graph_result.get("citations") or []),
            carousel=carousel_block,
            requires_human_handover=bool(graph_result.get("requires_human_handover")),
            handover_reason=graph_result.get("handover_reason"),
            uncertainty_score=float(graph_result.get("uncertainty_score", 0.0) or 0.0),
            validator_failures=list(graph_result.get("validator_failures") or []),
        ),
        metadata=OutboundMetadata(
            model=graph_result.get("llm_model"),
            tokens=tokens,
            latency_ms=int(graph_result.get("llm_latency_ms", 0) or 0),
            abstained=bool(graph_result.get("abstained")),
            surface=str(graph_result.get("surface", "messenger")),
        ),
    )
