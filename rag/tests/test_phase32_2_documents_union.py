"""Phase 32.2 — products appear as rows in the Documents list.

Pre-32.2 the endpoint only returned vault notes (``app.documents`` rows).
The user expects products they create to surface in /documents as well.

Behavioral test mocks the ``AsyncSession`` so the list handler can run
without a live Postgres. Source guards back it up against regressions.
"""

from __future__ import annotations

import inspect
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

import pytest

from routers import documents as documents_module


class _FakeResult:
    def __init__(self, value: Any) -> None:
        self._value = value

    def scalar_one(self) -> Any:
        return self._value

    class _Scalars:
        def __init__(self, items: list[Any]) -> None:
            self._items = items

        def all(self) -> list[Any]:
            return list(self._items)

    def scalars(self) -> "_FakeResult._Scalars":
        return _FakeResult._Scalars(self._value)


class _FakeSession:
    """Sequenced results: list_documents issues
    (docs_total, products_total, docs_rows, product_rows) in order.
    """

    def __init__(self, results: list[Any]) -> None:
        self._results = list(results)
        self.queries = 0

    async def execute(self, _stmt: Any) -> _FakeResult:
        self.queries += 1
        return _FakeResult(self._results.pop(0))


def _doc(*, file: str, title: str, folder: str, modified_ts: float) -> Any:
    return SimpleNamespace(
        file=file,
        title=title,
        folder=folder,
        tags=[],
        source_kind="note",
        modified_at=datetime.fromtimestamp(modified_ts, tz=timezone.utc),
        indexed_at=datetime.fromtimestamp(modified_ts, tz=timezone.utc),
    )


def _product(*, name: str, slug: str, updated_ts: float) -> Any:
    return SimpleNamespace(
        name=name,
        slug=slug,
        updated_at=datetime.fromtimestamp(updated_ts, tz=timezone.utc),
    )


@pytest.mark.asyncio
async def test_list_documents_unions_products_with_notes() -> None:
    docs = [
        _doc(file="01 - Projects/A.md", title="Note A", folder="01 - Projects", modified_ts=1000),
        _doc(file="02 - Areas/B.md", title="Note B", folder="02 - Areas", modified_ts=3000),
    ]
    products = [
        _product(name="Luffy", slug="luffy", updated_ts=2000),
    ]

    db = _FakeSession(results=[len(docs), len(products), docs, products])
    user = SimpleNamespace(id=uuid.uuid4())
    tenant = SimpleNamespace(id=uuid.uuid4(), slug="hunter")

    out = await documents_module.list_documents(
        search="",
        page=1,
        limit=50,
        user=user,
        tenant=tenant,
        db=db,  # type: ignore[arg-type]
    )

    assert out["total"] == 3
    titles = [row["title"] for row in out["items"]]
    assert "Luffy" in titles, "product must appear in the unified list"
    assert {"Note A", "Note B"}.issubset(set(titles)), "notes must still appear"

    luffy = next(r for r in out["items"] if r["title"] == "Luffy")
    assert luffy["folder"] == "/products"
    assert luffy["path"] == "/products/luffy"
    assert luffy["source_kind"] == "product"
    assert "product" in luffy["tags"]

    # Modified-desc ordering: Note B (3000) > Luffy (2000) > Note A (1000).
    assert titles == ["Note B", "Luffy", "Note A"]


def test_product_to_doc_dict_shape() -> None:
    p = _product(name="Glow Serum", slug="glow-serum", updated_ts=5000)
    row = documents_module._product_to_doc_dict(p)
    assert row["path"] == "/products/glow-serum"
    assert row["folder"] == "/products"
    assert row["source_kind"] == "product"
    assert row["tags"] == ["product"]
    assert row["title"] == "Glow Serum"
    assert isinstance(row["modified"], float)


def test_documents_module_imports_product() -> None:
    """Source guard: a future refactor that drops the Product import will
    silently revert the union back to notes-only. Fail loudly instead."""
    src = inspect.getsource(documents_module)
    assert "from rag.database.models import Document, Product" in src
    assert "_product_to_doc_dict" in src
