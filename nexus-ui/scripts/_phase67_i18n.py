#!/usr/bin/env python3
"""Phase 67 — add the ``nav.inbox`` label to every locale's common.json.

Inserts an ``inbox`` nav key immediately after ``broadcasts`` (or appends to the
nav block if ``broadcasts`` is absent), preserving key order via a JSON
round-trip. A round-trip (not a text insert) is used because the hand-translated
locale files order their nav keys differently — ``broadcasts`` is the last nav
key with no trailing comma in several of them, which a naive line insert breaks.

The ``inbox`` feature namespace ships English-only (en/inbox.json); i18next's
``fallbackLng: 'en'`` renders the English copy for the other languages until
real translations land. Idempotent: re-running leaves an existing key untouched.

Run:  python nexus-ui/scripts/_phase67_i18n.py
"""

from __future__ import annotations

import json
from collections import OrderedDict
from pathlib import Path

LOCALES = Path(__file__).resolve().parent.parent / "src" / "i18n" / "locales"

NAV_INBOX = {
    "en": "Inbox",
    "es": "Bandeja de entrada",
    "fr": "Boîte de réception",
    "de": "Posteingang",
    "vi": "Hộp thư",
    "ja": "受信トレイ",
    "fil": "Inbox",
}


def _with_inbox(nav: "OrderedDict[str, str]", label: str) -> "OrderedDict[str, str]":
    """Return a copy of ``nav`` with ``inbox`` placed right after ``broadcasts``."""
    rebuilt: "OrderedDict[str, str]" = OrderedDict()
    inserted = False
    for key, value in nav.items():
        rebuilt[key] = value
        if key == "broadcasts":
            rebuilt["inbox"] = label
            inserted = True
    if not inserted:
        rebuilt["inbox"] = label
    return rebuilt


def main() -> None:
    for lang, label in NAV_INBOX.items():
        common = LOCALES / lang / "common.json"
        if not common.exists():
            print(f"skip (missing): {common}")
            continue
        data = json.loads(common.read_text(encoding="utf-8"), object_pairs_hook=OrderedDict)
        nav = data.get("nav")
        if not isinstance(nav, OrderedDict):
            print(f"skip (no nav): {lang}")
            continue
        if "inbox" in nav:
            print(f"skip (already present): {lang}")
            continue
        data["nav"] = _with_inbox(nav, label)
        common.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"updated: {lang} (nav.inbox = {label})")


if __name__ == "__main__":
    main()
