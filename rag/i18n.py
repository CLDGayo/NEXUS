"""Phase 59 — language helpers shared by the flow engine and settings API.

Single source of truth for the supported chatbot/UI languages and the strict
LLM system-prompt directive that forces a reply language.  Imported by:

* ``rag.auth.schemas``        — derives ``SUPPORTED_LANGUAGES`` for validators.
* ``rag.messenger.flow_engine`` — injects ``language_directive`` into LLM nodes.

This module imports nothing from the rest of the package so it is safe to pull
in from anywhere (no circular-import risk).

The code → name map mirrors ``nexus-ui/src/i18n/languages.js`` and the user-
language list in ``rag.auth.schemas``.  Keep the three in sync.  English is the
default fallback; a directive is only emitted for non-English tenants so
default tenants get byte-identical prompts.
"""

from __future__ import annotations

DEFAULT_LANGUAGE = "en"

# BCP-47 base code -> English language name used inside the LLM directive.
# Order mirrors nexus-ui/src/i18n/languages.js.
LANGUAGE_NAMES: dict[str, str] = {
    "en": "English",
    "vi": "Vietnamese",
    "fil": "Filipino",
    "de": "German",
    "fr": "French",
    "es": "Spanish",
    "ja": "Japanese",
}

# The set of accepted codes — derived so it can never drift from the name map.
SUPPORTED_LANGUAGES: frozenset[str] = frozenset(LANGUAGE_NAMES)


def language_directive(code: str | None) -> str:
    """Return a strict system-prompt directive forcing replies in *code*.

    Returns ``""`` for English / ``None`` / unknown codes so default-English
    tenants get an unchanged prompt (no behaviour change).  Otherwise returns
    e.g. ``"You must reply exclusively in Spanish."``.
    """
    if not code or code == DEFAULT_LANGUAGE:
        return ""
    name = LANGUAGE_NAMES.get(code)
    if not name:
        return ""
    return f"You must reply exclusively in {name}."


def apply_language_directive(system_prompt: str, code: str | None) -> str:
    """Append the language directive to *system_prompt* when non-English.

    A no-op (returns *system_prompt* unchanged) for English / unknown codes.
    """
    directive = language_directive(code)
    if not directive:
        return system_prompt
    return f"{system_prompt}\n\n{directive}"
