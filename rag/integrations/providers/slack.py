"""Slack incoming-webhook notifier.

Config:
    {"webhook_url": "https://hooks.slack.com/services/..."}
"""

from __future__ import annotations

import json
from typing import Any

import httpx


def _title(event: str, payload: dict[str, Any]) -> str:
    if event.startswith("ingest."):
        return f"NEXUS · {event} · {payload.get('file', '?')}"
    if event.startswith("chat."):
        return f"NEXUS · {event} · session {payload.get('session_id', '?')}"
    return f"NEXUS · {event}"


def format_payload(event: str, payload: dict[str, Any]) -> dict[str, Any]:
    pretty = json.dumps(payload, indent=2, default=str)[:1500]
    return {
        "text": _title(event, payload),
        "blocks": [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*{_title(event, payload)}*"},
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"```{pretty}```"},
            },
        ],
    }


def redact(config: dict[str, Any]) -> dict[str, Any]:
    out = dict(config)
    url = str(out.get("webhook_url", ""))
    if url:
        out["webhook_url"] = url[:30] + "…" + url[-4:] if len(url) > 40 else "***"
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
