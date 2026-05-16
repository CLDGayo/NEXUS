"""Generic outbound webhook (n8n, Make.com, custom).

Config:
    {"url": "https://...", "secret": "optional-shared-secret"}
"""

from __future__ import annotations

from typing import Any

import httpx


def format_payload(event: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {"event": event, "payload": payload}


def redact(config: dict[str, Any]) -> dict[str, Any]:
    out = dict(config)
    if "secret" in out and out["secret"]:
        s = str(out["secret"])
        out["secret"] = f"***{s[-4:]}" if len(s) >= 4 else "***"
    return out


async def dispatch(
    config: dict[str, Any], event: str, payload: dict[str, Any]
) -> tuple[int, str]:
    url = config.get("url")
    if not url:
        return (0, "missing url")
    headers = {"Content-Type": "application/json"}
    if config.get("secret"):
        headers["X-Nexus-Secret"] = str(config["secret"])
    body = format_payload(event, payload)
    async with httpx.AsyncClient(timeout=10.0) as c:
        r = await c.post(url, json=body, headers=headers)
    return (r.status_code, r.text[:200])
