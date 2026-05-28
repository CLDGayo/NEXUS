"""Phase 32 — ``build_outbound_payload`` accepts dict-shaped carousels.

The orchestrator stores the carousel as a serialised dict in state so
it survives JSON round-trip through the LangGraph checkpointer. The
webhook adapter calls ``build_outbound_payload`` with that dict; this
test pins the contract that the adapter accepts both the dict and a
``ProductCarouselBlock`` instance.
"""

from __future__ import annotations

from rag.messenger.payloads import (
    ProductCarouselBlock,
    build_outbound_payload,
)
from rag.messenger.schemas import InboundMessage


def _inbound() -> InboundMessage:
    return InboundMessage(
        user_id="PSID-1",
        message_text="Got matcha?",
        timestamp=0,
        channel="messenger",
        page_id="PAGE-1",
    )


def test_dict_carousel_round_trips_into_reply_block() -> None:
    block = ProductCarouselBlock(
        elements=[
            {
                "title": "Matcha 100g",
                "subtitle": "USD 12.00 · 3 in stock",
                "image_url": "https://example.com/m.webp",
                "buttons": [],
            }
        ]
    )
    payload = build_outbound_payload(
        inbound=_inbound(),
        correlation_id="cid",
        reply_text="Here is the match:",
        graph_result={"product_carousel": block.model_dump(mode="json")},
    )
    assert payload.reply.text == "Here is the match:"
    assert payload.reply.carousel is not None
    assert payload.reply.carousel.elements[0].title == "Matcha 100g"


def test_block_instance_carousel_passthrough() -> None:
    block = ProductCarouselBlock(
        elements=[{"title": "Tea Set", "buttons": []}]
    )
    payload = build_outbound_payload(
        inbound=_inbound(),
        correlation_id="cid",
        reply_text="See below.",
        graph_result={"product_carousel": block},
    )
    assert payload.reply.carousel is block


def test_missing_carousel_leaves_reply_text_only() -> None:
    payload = build_outbound_payload(
        inbound=_inbound(),
        correlation_id="cid",
        reply_text="Plain text reply.",
        graph_result={},
    )
    assert payload.reply.text == "Plain text reply."
    assert payload.reply.carousel is None


def test_malformed_carousel_is_dropped_silently() -> None:
    payload = build_outbound_payload(
        inbound=_inbound(),
        correlation_id="cid",
        reply_text="Still here.",
        graph_result={"product_carousel": {"elements": "not a list"}},
    )
    assert payload.reply.text == "Still here."
    assert payload.reply.carousel is None
