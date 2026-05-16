"""GitHub provider — read-only repo status + push-selected-file mode.

Config:
    {"pat": "ghp_...", "repo": "owner/name", "branch": "main"}
"""

from __future__ import annotations

import base64
from typing import Any

import httpx


def _api(repo: str, path: str) -> str:
    return f"https://api.github.com/repos/{repo}/{path}"


def redact(config: dict[str, Any]) -> dict[str, Any]:
    out = dict(config)
    if pat := out.get("pat"):
        s = str(pat)
        out["pat"] = f"***{s[-4:]}" if len(s) >= 4 else "***"
    return out


async def status(config: dict[str, Any]) -> tuple[int, str]:
    pat = config.get("pat")
    repo = config.get("repo")
    if not pat or not repo:
        return (0, "missing pat or repo")
    async with httpx.AsyncClient(timeout=10.0) as c:
        r = await c.get(
            _api(repo, ""),
            headers={"Authorization": f"token {pat}", "Accept": "application/vnd.github+json"},
        )
    return (r.status_code, r.text[:200])


async def dispatch(
    config: dict[str, Any], event: str, payload: dict[str, Any]
) -> tuple[int, str]:
    """Post a comment to a tracking issue if `issue_number` is set, else no-op."""
    pat = config.get("pat")
    repo = config.get("repo")
    issue = config.get("issue_number")
    if not (pat and repo and issue):
        return (204, "no issue_number configured; skipped")
    body = f"**NEXUS event** `{event}`\n\n```json\n{payload}\n```"
    async with httpx.AsyncClient(timeout=10.0) as c:
        r = await c.post(
            _api(repo, f"issues/{issue}/comments"),
            headers={"Authorization": f"token {pat}", "Accept": "application/vnd.github+json"},
            json={"body": body},
        )
    return (r.status_code, r.text[:200])


async def push_file(
    config: dict[str, Any], path: str, content: str, message: str
) -> tuple[int, str]:
    pat = config.get("pat")
    repo = config.get("repo")
    branch = config.get("branch", "main")
    if not pat or not repo:
        return (0, "missing pat or repo")
    headers = {"Authorization": f"token {pat}", "Accept": "application/vnd.github+json"}
    encoded = base64.b64encode(content.encode("utf-8")).decode("ascii")

    async with httpx.AsyncClient(timeout=15.0) as c:
        existing = await c.get(_api(repo, f"contents/{path}?ref={branch}"), headers=headers)
        sha = existing.json().get("sha") if existing.status_code == 200 else None
        body: dict[str, Any] = {"message": message, "content": encoded, "branch": branch}
        if sha:
            body["sha"] = sha
        r = await c.put(_api(repo, f"contents/{path}"), headers=headers, json=body)
    return (r.status_code, r.text[:200])
