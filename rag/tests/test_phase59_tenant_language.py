"""Phase 59 — unit tests for the shared language helpers and tenant schema.

Pure, no DB / network. Covers:
    * language_directive: en/None/unknown -> "", non-en -> strict directive.
    * apply_language_directive: appends for non-en, no-op for en.
    * SUPPORTED_LANGUAGES is derived from LANGUAGE_NAMES (no drift).
    * TenantUpdate.preferred_language validator accepts/rejects correctly.
"""

from __future__ import annotations

import pytest

from rag.i18n import (
    DEFAULT_LANGUAGE,
    LANGUAGE_NAMES,
    SUPPORTED_LANGUAGES,
    apply_language_directive,
    language_directive,
)


@pytest.mark.unit
class TestLanguageDirective:
    def test_english_returns_empty(self) -> None:
        assert language_directive("en") == ""

    def test_none_returns_empty(self) -> None:
        assert language_directive(None) == ""

    def test_unknown_code_returns_empty(self) -> None:
        assert language_directive("xx") == ""

    @pytest.mark.parametrize(
        ("code", "name"),
        [("es", "Spanish"), ("fr", "French"), ("ja", "Japanese"), ("de", "German")],
    )
    def test_non_english_returns_strict_directive(self, code: str, name: str) -> None:
        assert language_directive(code) == f"You must reply exclusively in {name}."


@pytest.mark.unit
class TestApplyLanguageDirective:
    def test_appends_for_non_english(self) -> None:
        out = apply_language_directive("Base prompt.", "ja")
        assert out == "Base prompt.\n\nYou must reply exclusively in Japanese."

    def test_noop_for_english(self) -> None:
        assert apply_language_directive("Base prompt.", "en") == "Base prompt."

    def test_noop_for_none(self) -> None:
        assert apply_language_directive("Base prompt.", None) == "Base prompt."


@pytest.mark.unit
class TestLanguageConstants:
    def test_default_is_english(self) -> None:
        assert DEFAULT_LANGUAGE == "en"

    def test_supported_derived_from_names(self) -> None:
        assert SUPPORTED_LANGUAGES == frozenset(LANGUAGE_NAMES)

    def test_english_is_supported(self) -> None:
        assert "en" in SUPPORTED_LANGUAGES


@pytest.mark.unit
class TestTenantUpdateLanguageValidator:
    def test_accepts_supported_language(self) -> None:
        from rag.auth.schemas import TenantUpdate

        body = TenantUpdate(preferred_language="es")
        assert body.preferred_language == "es"

    def test_accepts_none(self) -> None:
        from rag.auth.schemas import TenantUpdate

        body = TenantUpdate(name="Acme")
        assert body.preferred_language is None

    def test_rejects_unsupported_language(self) -> None:
        from pydantic import ValidationError

        from rag.auth.schemas import TenantUpdate

        with pytest.raises(ValidationError):
            TenantUpdate(preferred_language="zz")
