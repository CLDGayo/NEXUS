"""Phase 34 — Sales SDR tool definitions (Messenger surface only).

``check_inventory`` queries the live Postgres catalog.
``generate_checkout_link`` POSTs to n8n which calls Stripe to mint
a real Checkout Session URL. ``capture_lead`` POSTs to n8n which
pushes the email to GoHighLevel CRM. Both fall back gracefully to
mock strings when their respective webhook URLs are not configured.

``SALES_TOOLS_SCHEMA`` is the OpenAI-compatible ``tools`` array passed
to ``chat_complete(extra={"tools": ..., "tool_choice": "auto"})`` when
``surface == "messenger"``.

``SDR_PERSONA_OVERLAY`` is the persona overlay ``generate_node``
appends to the Messenger system prompt at runtime when tools are
bound. Lives here (next to the tools it instructs the LLM to call)
so all SDR concerns share one module.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx
from sqlalchemy import select

from rag.config import settings
from rag.database.engine import get_sessionmaker
from rag.database.models import Product, Tenant

_log = logging.getLogger(__name__)


async def check_inventory(product_name: str, tenant_id: str) -> str:
    """Check real-time inventory by name within the active tenant catalog.

    Args:
        product_name: Full or partial product name to search.
        tenant_id: Tenant slug scoping the catalog query.

    Returns:
        Human-readable summary of matches, or "No products found...".
    """
    sessionmaker = get_sessionmaker()
    stmt = (
        select(Product)
        .join(Tenant, Product.tenant_id == Tenant.id)
        .where(
            Tenant.slug == tenant_id,
            Product.is_active.is_(True),
            Product.name.ilike(f"%{product_name}%"),
        )
        .limit(5)
    )
    async with sessionmaker() as db:
        rows = (await db.scalars(stmt)).all()

    if not rows:
        return f"No products found matching '{product_name}'."

    lines: list[str] = []
    for p in rows:
        price = f"{p.currency} {(p.price_cents or 0) / 100:.2f}"
        stock = "In stock" if p.quantity > 0 else "Out of stock"
        lines.append(f"- {p.name}: {price}, {p.quantity} available ({stock})")
    return "\n".join(lines)


async def generate_checkout_link(product_name: str, quantity: int) -> str:
    """Generate a one-time checkout URL via n8n → Stripe.

    POSTs { product_name, quantity } to the configured n8n webhook.
    n8n creates a Stripe Checkout Session and returns the URL.
    Falls back to mock if the webhook URL is not configured.
    """
    webhook_url = settings.n8n_webhook_checkout_url
    if not webhook_url:
        _log.warning(
            "sales_tools.generate_checkout_link: N8N_WEBHOOK_CHECKOUT_URL "
            "not configured — returning mock link"
        )
        return (
            f"https://checkout.example.com/order?"
            f"product={product_name}&qty={quantity}"
            f" — [Mock link: set N8N_WEBHOOK_CHECKOUT_URL to enable]"
        )

    payload = {"product_name": product_name, "quantity": quantity}
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(connect=5.0, read=15.0, write=5.0, pool=5.0),
        ) as client:
            resp = await client.post(webhook_url, json=payload)
            resp.raise_for_status()

        body = resp.json()
        url = body.get("url") or body.get("checkout_url") or body.get("payment_url")
        if not url:
            _log.error(
                "sales_tools.generate_checkout_link: n8n returned no URL "
                "in response body: %s",
                body,
            )
            return "Checkout link generation failed — no URL in response."
        _log.info(
            "sales_tools.generate_checkout_link product=%r qty=%d url=%s",
            product_name,
            quantity,
            url,
        )
        return str(url)

    except httpx.HTTPStatusError as exc:
        _log.error(
            "sales_tools.generate_checkout_link: n8n returned %d: %s",
            exc.response.status_code,
            exc.response.text[:200],
        )
        return "Checkout link generation failed — payment service error."
    except httpx.TimeoutException:
        _log.error("sales_tools.generate_checkout_link: n8n webhook timed out")
        return "Checkout link generation failed — service timed out."
    except Exception as exc:  # noqa: BLE001
        _log.error("sales_tools.generate_checkout_link: unexpected error: %s", exc)
        return "Checkout link generation failed — unexpected error."


async def capture_lead(email: str) -> str:
    """Record a customer email via n8n → GoHighLevel CRM.

    POSTs { email } to the configured n8n webhook. n8n pushes
    the contact to GHL. Falls back to mock if not configured.
    """
    webhook_url = settings.n8n_webhook_lead_url
    if not webhook_url:
        _log.warning(
            "sales_tools.capture_lead: N8N_WEBHOOK_LEAD_URL "
            "not configured — returning mock confirmation"
        )
        return (
            f"Email {email} captured successfully. "
            f"[Mock: set N8N_WEBHOOK_LEAD_URL to enable]"
        )

    payload = {"email": email}
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(connect=5.0, read=10.0, write=5.0, pool=5.0),
        ) as client:
            resp = await client.post(webhook_url, json=payload)
            resp.raise_for_status()

        _log.info("sales_tools.capture_lead email=%r → n8n 200 OK", email)
        return f"Email {email} captured successfully. We'll follow up shortly!"

    except httpx.HTTPStatusError as exc:
        _log.error(
            "sales_tools.capture_lead: n8n returned %d: %s",
            exc.response.status_code,
            exc.response.text[:200],
        )
        return f"Lead capture failed for {email} — CRM service error."
    except httpx.TimeoutException:
        _log.error("sales_tools.capture_lead: n8n webhook timed out")
        return f"Lead capture failed for {email} — service timed out."
    except Exception as exc:  # noqa: BLE001
        _log.error("sales_tools.capture_lead: unexpected error: %s", exc)
        return f"Lead capture failed for {email} — unexpected error."


SALES_TOOLS_SCHEMA: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "check_inventory",
            "description": (
                "Check real-time inventory for a product by name. Returns "
                "price, stock quantity, and availability. Use when a "
                "customer asks about product availability or stock levels."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "product_name": {
                        "type": "string",
                        "description": ("Product name or partial name to search."),
                    },
                },
                "required": ["product_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_checkout_link",
            "description": (
                "Generate a checkout/payment link. Use when the customer "
                "confirms they want to purchase a specific product and "
                "quantity."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "product_name": {
                        "type": "string",
                        "description": "Exact product name from catalog.",
                    },
                    "quantity": {
                        "type": "integer",
                        "description": "Number of units to purchase.",
                        "default": 1,
                    },
                },
                "required": ["product_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "capture_lead",
            "description": (
                "Capture customer email for follow-up or order updates. "
                "Use when the customer shares their email or you need it "
                "for order processing."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "email": {
                        "type": "string",
                        "description": "Customer email address.",
                    },
                },
                "required": ["email"],
            },
        },
    },
]


TOOL_DISPATCH: dict[str, Any] = {
    "check_inventory": check_inventory,
    "generate_checkout_link": generate_checkout_link,
    "capture_lead": capture_lead,
}


# Phase 33 — SDR persona overlay appended to the Messenger system prompt
# at runtime when tools are bound. Preserves citation rules so the
# guardrails pipeline still validates the answer.
SDR_PERSONA_OVERLAY = (
    "\n\n--- SALES REPRESENTATIVE MODE ---\n"
    "You are now also acting as a proactive sales development "
    "representative. In addition to the customer service rules above, "
    "follow these additional guidelines:\n\n"
    "1. ALWAYS end your reply with a closing question or call to action "
    "that moves the customer toward a purchase decision (e.g., 'Would "
    "you like me to check if we have that in stock?', 'Shall I send you "
    "a checkout link?', 'Can I get your email to send you the order "
    "confirmation?').\n"
    "2. When a customer asks about a product, proactively use the "
    "check_inventory tool to provide real-time availability and "
    "pricing.\n"
    "3. When a customer shows buying intent (asks about price, says 'I "
    "want', 'how much', 'can I buy', 'I'll take it'), use "
    "generate_checkout_link to provide an instant checkout URL.\n"
    "4. When a customer shares their email or you need it for order "
    "follow-up, use capture_lead to record it.\n"
    "5. Be conversational and warm, not pushy. Guide the customer "
    "naturally through the sales funnel: awareness → interest → "
    "decision → action.\n"
    "6. If the customer is browsing, suggest specific products from the "
    "retrieved context. If they're comparing, highlight differentiators.\n"
    "7. All citation and grounding rules from above still apply. Never "
    "invent prices, stock levels, or product details — always cite or "
    "use a tool.\n"
)


async def execute_tool_call(
    tool_call: dict[str, Any],
    *,
    tenant_id: str,
) -> dict[str, str]:
    """Execute one tool call and return an OpenAI ``role=tool`` message.

    The returned dict is appended to the messages list and re-fed to the
    LLM so the next completion can incorporate the tool result. On any
    failure (unknown name, bad JSON args, raised exception) returns a
    diagnostic string rather than raising — keeps the tool loop alive.
    """
    func_name = tool_call.get("function", {}).get("name", "")
    call_id = tool_call.get("id", "")
    raw_args = tool_call.get("function", {}).get("arguments", "{}")

    try:
        args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
    except (json.JSONDecodeError, TypeError):
        args = {}
    if not isinstance(args, dict):
        args = {}

    handler = TOOL_DISPATCH.get(func_name)
    if handler is None:
        result: str = f"Unknown tool: {func_name}"
    else:
        try:
            if func_name == "check_inventory":
                result = await handler(
                    product_name=args.get("product_name", ""),
                    tenant_id=tenant_id,
                )
            elif func_name == "generate_checkout_link":
                result = await handler(
                    product_name=args.get("product_name", ""),
                    quantity=int(args.get("quantity", 1)),
                )
            elif func_name == "capture_lead":
                result = await handler(email=args.get("email", ""))
            else:
                result = f"Unhandled tool: {func_name}"
        except Exception as exc:  # noqa: BLE001 — never raise into the loop
            _log.warning("sales_tools.execute_failed tool=%s error=%s", func_name, exc)
            result = f"Tool error: {exc}"

    return {
        "role": "tool",
        "tool_call_id": call_id,
        "content": str(result),
    }


__all__ = [
    "SALES_TOOLS_SCHEMA",
    "SDR_PERSONA_OVERLAY",
    "TOOL_DISPATCH",
    "capture_lead",
    "check_inventory",
    "execute_tool_call",
    "generate_checkout_link",
]
