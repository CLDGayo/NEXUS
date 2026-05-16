"""Per-provider dispatchers (webhook, slack, discord, github)."""

from . import discord, github, slack, webhook

PROVIDERS: dict[str, object] = {
    "webhook": webhook,
    "slack": slack,
    "discord": discord,
    "github": github,
}

__all__ = ["PROVIDERS"]
