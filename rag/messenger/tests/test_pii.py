"""Tests for the regex PII scrubber.

Coverage targets:
    * Each kind detected, replaced, counted.
    * Luhn rejects long digit strings that aren't valid cards.
    * Idempotent — running scrub on its own output is a no-op.
    * Mixed-kind paragraph counts correctly per kind.
"""

from __future__ import annotations

import pytest

from rag.messenger.pii import REPLACEMENTS, scrub


@pytest.mark.unit
class TestEmail:
    def test_simple(self) -> None:
        result = scrub("ping me at john.doe@example.com please")
        assert "[EMAIL_REDACTED]" in result.scrubbed_text
        assert "john.doe@example.com" not in result.scrubbed_text
        assert result.counts_by_kind == {"EMAIL": 1}

    def test_two_emails(self) -> None:
        result = scrub("a@x.io and b+tag@y.co.uk")
        assert result.counts_by_kind == {"EMAIL": 2}


@pytest.mark.unit
class TestPhone:
    @pytest.mark.parametrize(
        "raw",
        [
            "call me at 555-867-5309",
            "phone: +1 (555) 867-5309",
            "+639171234567",
            "tel 0917.123.4567",
        ],
    )
    def test_variants_detected(self, raw: str) -> None:
        result = scrub(raw)
        assert "[PHONE_REDACTED]" in result.scrubbed_text
        assert result.counts_by_kind.get("PHONE") == 1

    def test_short_digit_string_not_matched(self) -> None:
        # 4 digits is not a phone — should pass through untouched.
        result = scrub("order 1234 confirmed")
        assert "[PHONE_REDACTED]" not in result.scrubbed_text


@pytest.mark.unit
class TestCard:
    def test_valid_visa_detected(self) -> None:
        # Valid Luhn — well-known test card.
        result = scrub("paid with 4111 1111 1111 1111 today")
        assert "[CARD_REDACTED]" in result.scrubbed_text
        assert result.counts_by_kind == {"CARD": 1}

    def test_luhn_rejects_random_16_digit(self) -> None:
        # 1234567890123456 fails Luhn → must NOT be treated as a card.
        # (It may still be flagged as a phone candidate; that's a separate
        # category and acceptable. We only assert no CARD redaction.)
        result = scrub("order id 1234567890123456 placed")
        assert result.counts_by_kind.get("CARD", 0) == 0


@pytest.mark.unit
class TestSsn:
    def test_detected(self) -> None:
        result = scrub("SSN: 123-45-6789 on file")
        assert "[SSN_REDACTED]" in result.scrubbed_text
        assert result.counts_by_kind == {"SSN": 1}


@pytest.mark.unit
class TestIban:
    def test_detected(self) -> None:
        result = scrub("wire to DE89370400440532013000 by friday")
        assert "[IBAN_REDACTED]" in result.scrubbed_text
        assert result.counts_by_kind.get("IBAN") == 1


@pytest.mark.unit
class TestIp:
    def test_detected(self) -> None:
        result = scrub("server at 192.168.1.42 is down")
        assert "[IP_REDACTED]" in result.scrubbed_text
        assert result.counts_by_kind == {"IP": 1}

    def test_invalid_octet_skipped(self) -> None:
        result = scrub("version 1.2.3.999 release notes")
        # 999 > 255 → not a valid IP.
        assert "[IP_REDACTED]" not in result.scrubbed_text


@pytest.mark.unit
class TestMixed:
    def test_paragraph_with_three_kinds(self) -> None:
        text = (
            "Hi! Reach me at jane@acme.com or 555-867-5309. "
            "Card on file is 4111 1111 1111 1111."
        )
        result = scrub(text)
        counts = result.counts_by_kind
        assert counts.get("EMAIL") == 1
        assert counts.get("PHONE") == 1
        assert counts.get("CARD") == 1
        for token in [
            REPLACEMENTS["EMAIL"],
            REPLACEMENTS["PHONE"],
            REPLACEMENTS["CARD"],
        ]:
            assert token in result.scrubbed_text


@pytest.mark.unit
class TestIdempotent:
    def test_double_scrub_is_noop(self) -> None:
        text = "email a@b.io phone +14155551234 card 4111111111111111"
        once = scrub(text)
        twice = scrub(once.scrubbed_text)
        assert twice.redactions == ()
        assert twice.scrubbed_text == once.scrubbed_text


@pytest.mark.unit
class TestEmpty:
    def test_empty_string(self) -> None:
        result = scrub("")
        assert result.scrubbed_text == ""
        assert result.redactions == ()

    def test_no_pii(self) -> None:
        text = "Hello, what is the meaning of life?"
        result = scrub(text)
        assert result.scrubbed_text == text
        assert result.redactions == ()
