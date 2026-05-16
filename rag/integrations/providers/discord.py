"""Discord webhook notifier.

Config:
    {"webhook_url": "https://discord.com/api/webhooks/..."}
"""

from __future__ import annotations

import json
from typing import Any

import httpx


def format_payload(event: str, payload: dict[str, Any]) -> dict[str, Any]:
    pretty = json.dumps(payload, indent=2, default=str)[:1500]
    return {
        "username": "NEXUS",
        "embeds": [
            {
                "title": event,
                "description": f"```json\n{pretty}\n```",
                "color": 0x2563EB,
            }
        ],
    }


def redact(config: dict[str, Any]) -> dict[str, Any]:
    out = dict(config)
    url = str(out.get("webhook_url", ""))
    if url:
        out["webhook_url"] = url[:40] + "…" + url[-4:] if len(url) > 50 else "***"
    return out


async def dispatch(
    config: dict[str, Any], event: str, payload: dict[str, Any]
) -> tuple[int, str]:
    url = config.get("webhook_url")
    if not url:
        return (0, "missing webhook_url")
    async with httpx.AsyncClient(timeout=10.0) as c:
        r = await c.post(url, json=format_payload(event, payload))
    return (r.status_code, r.text[:200])
