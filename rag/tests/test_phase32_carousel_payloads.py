"""Phase 32 — Generic Template payload shape + Meta hard-limit guards.

Pure-unit tests on the new payload primitives. No DB, no Qdrant, no
HTTP. Catches drift in: (a) Meta's published character/element limits,
(b) the JSON shape required by the Send API.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from rag.messenger.payloads import (
    GenericTemplateButton,
    GenericTemplateElement,
    OutboundMetadata,
    OutboundPayload,
    ProductCarouselBlock,
    ReplyBlock,
)
from rag.messenger.sender import OutboundSender


def _carousel(n: int = 2) -> ProductCarouselBlock:
    elements = [
        GenericTemplateElement(
            title=f"Product {i}",
            subtitle="USD 19.99 · 5 in stock",
            image_url="https://example.com/p.webp",
            buttons=[
                GenericTemplateButton(
                    type="web_url",
                    title="View",
                    url="https://shop.example.com/p/1",
                )
            ],
        )
        for i in range(n)
    ]
    return ProductCarouselBlock(elements=elements)


# ── Hard-limit guards ──────────────────────────────────────────────────────


def test_button_title_max_20() -> None:
    with pytest.raises(ValidationError):
        GenericTemplateButton(
            type="web_url",
            title="x" * 21,
            url="https://example.com",
        )


def test_element_title_max_80() -> None:
    with pytest.raises(ValidationError):
        GenericTemplateElement(title="x" * 81)


def test_element_subtitle_max_80() -> None:
    with pytest.raises(ValidationError):
        GenericTemplateElement(title="ok", subtitle="x" * 81)


def test_element_max_3_buttons() -> None:
    buttons = [
        GenericTemplateButton(type="web_url", title="A", url="https://e.com"),
        GenericTemplateButton(type="web_url", title="B", url="https://e.com"),
        GenericTemplateButton(type="web_url", title="C", url="https://e.com"),
        GenericTemplateButton(type="web_url", title="D", url="https://e.com"),
    ]
    with pytest.raises(ValidationError):
        GenericTemplateElement(title="ok", buttons=buttons)


def test_carousel_max_10_elements() -> None:
    too_many = [
        GenericTemplateElement(title=f"P{i}") for i in range(11)
    ]
    with pytest.raises(ValidationError):
        ProductCarouselBlock(elements=too_many)


def test_carousel_requires_at_least_one_element() -> None:
    with pytest.raises(ValidationError):
        ProductCarouselBlock(elements=[])


# ── ReplyBlock — text optional once carousel is present ────────────────────


def test_reply_block_text_optional_with_carousel() -> None:
    block = ReplyBlock(carousel=_carousel())
    assert block.text is None
    assert block.carousel is not None
    assert len(block.carousel.elements) == 2


def test_reply_block_accepts_text_and_carousel() -> None:
    block = ReplyBlock(text="Here are some matches:", carousel=_carousel())
    assert block.text == "Here are some matches:"


# ── Send API formatter — shape matches Meta's Generic Template ────────────


def test_format_generic_template_shape() -> None:
    carousel = _carousel(n=1)
    body = OutboundSender._format_generic_template(carousel, "PSID-123")

    assert body["recipient"] == {"id": "PSID-123"}
    assert body["messaging_type"] == "RESPONSE"
    attachment = body["message"]["attachment"]
    assert attachment["type"] == "template"
    payload = attachment["payload"]
    assert payload["template_type"] == "generic"
    assert len(payload["elements"]) == 1
    element = payload["elements"][0]
    assert element["title"] == "Product 0"
    assert element["subtitle"] == "USD 19.99 · 5 in stock"
    # exclude_none keeps the wire body tight — image_url present, no default_action.
    assert "default_action" not in element
    assert element["buttons"][0]["type"] == "web_url"


def test_graph_message_bodies_carousel_then_text_order() -> None:
    sender = OutboundSender()
    payload = OutboundPayload(
        correlation_id="cid",
        user_id="PSID-9",
        channel="messenger",
        page_id="PAGE",
        reply=ReplyBlock(text="Have a look:", carousel=_carousel()),
        metadata=OutboundMetadata(),
    )
    bodies = sender._graph_message_bodies(payload)
    assert len(bodies) == 2
    # Carousel ships first so the cards land at the top of the thread.
    assert "attachment" in bodies[0]["message"]
    assert bodies[1]["message"]["text"] == "Have a look:"


def test_graph_message_bodies_carousel_only() -> None:
    sender = OutboundSender()
    payload = OutboundPayload(
        correlation_id="cid",
        user_id="PSID-9",
        channel="messenger",
        page_id="PAGE",
        reply=ReplyBlock(carousel=_carousel()),
        metadata=OutboundMetadata(),
    )
    bodies = sender._graph_message_bodies(payload)
    assert len(bodies) == 1
    assert "attachment" in bodies[0]["message"]


# ── Phase 32.5 — empty buttons must be omitted before send ─────────────────


def test_format_generic_template_omits_empty_buttons_key() -> None:
    """Meta rejects `"buttons": []` with (#194)/(#100). When _format_carousel
    builds an element with no buttons (e.g. product.url is NULL and no CTA
    template configured), the dispatched JSON must drop the key entirely."""
    element = GenericTemplateElement(
        title="Luffy Gear 4 Bound man",
        subtitle="JPY 2,100.00 · 2 in stock",
        image_url="https://chat.nexus.gayo-sphere.cloud/api/objects/TOK",
        buttons=[],
    )
    carousel = ProductCarouselBlock(elements=[element])
    body = OutboundSender._format_generic_template(carousel, "PSID-123")

    el = body["message"]["attachment"]["payload"]["elements"][0]
    assert "buttons" not in el
    assert el["title"] == "Luffy Gear 4 Bound man"
    assert el["image_url"] == "https://chat.nexus.gayo-sphere.cloud/api/objects/TOK"


def test_format_generic_template_keeps_buttons_when_present() -> None:
    """Sanity: non-empty buttons must still ship."""
    carousel = _carousel(n=1)
    body = OutboundSender._format_generic_template(carousel, "PSID-9")
    el = body["message"]["attachment"]["payload"]["elements"][0]
    assert "buttons" in el
    assert len(el["buttons"]) == 1
    assert el["buttons"][0]["type"] == "web_url"


def test_graph_message_bodies_strips_citation_brackets() -> None:
    sender = OutboundSender()
    payload = OutboundPayload(
        correlation_id="cid",
        user_id="PSID-9",
        channel="messenger",
        page_id=None,
        reply=ReplyBlock(text="Per the docs [1] you can [2] do this."),
        metadata=OutboundMetadata(),
    )
    bodies = sender._graph_message_bodies(payload)
    assert len(bodies) == 1
    assert bodies[0]["message"]["text"] == "Per the docs  you can  do this."
