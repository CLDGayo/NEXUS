"""Phase 25 — ``fuse_node`` weight-matrix dispatch tests.

``fuse_node`` reads ``state["query_intent"]`` and must pass the matching
weight matrix from ``_WEIGHTS_BY_INTENT`` into ``reciprocal_rank_fusion``
alongside named rankings. Router outages (``intent=None`` or unset) must
collapse to ``_UNIFORM_WEIGHTS`` so the pipeline degrades to its
pre-Phase-25 mathematical baseline.
"""

from __future__ import annotations

import os

os.environ.setdefault("WEBHOOK_API_KEY", "test-key")
os.environ.setdefault("LANGGRAPH_CHECKPOINT", "memory")

from typing import Any

import pytest

from rag.orchestrator import nodes as nodes_module
from rag.retrieval.types import ScoredChunk


def _chunk(id_: str) -> ScoredChunk:
    return ScoredChunk(id=id_, text=f"text-{id_}", score=0.0)


@pytest.fixture
def captured_rrf(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Monkeypatch ``reciprocal_rank_fusion`` to capture the args the node
    passes to it, so the test asserts wiring without depending on the
    fusion math (covered by ``test_rrf.py``)."""

    box: dict[str, Any] = {}

    def fake_rrf(rankings, *, k=60, weights=None):
        box["rankings"] = rankings
        box["weights"] = weights
        box["k"] = k
        return [_chunk("captured")]

    monkeypatch.setattr(
        "rag.orchestrator.nodes.reciprocal_rank_fusion", fake_rrf
    )
    return box


def _state_with_hits(intent: str | None) -> dict[str, Any]:
    state: dict[str, Any] = {
        "dense_hits": [_chunk("d1")],
        "sparse_hits": [_chunk("s1")],
        "graph_hits": [_chunk("g1")],
    }
    if intent is not None:
        state["query_intent"] = intent
    return state


@pytest.mark.unit
async def test_fuse_node_factual_intent_applies_sparse_heavy_weights(
    captured_rrf: dict[str, Any],
) -> None:
    state = _state_with_hits("factual")
    await nodes_module.fuse_node(state)
    assert captured_rrf["weights"] == nodes_module._FACTUAL_WEIGHTS
    assert captured_rrf["weights"]["sparse"] == 1.5
    assert captured_rrf["weights"]["dense"] == 0.5
    assert captured_rrf["weights"]["graph"] == 1.0


@pytest.mark.unit
async def test_fuse_node_conceptual_intent_applies_dense_heavy_weights(
    captured_rrf: dict[str, Any],
) -> None:
    state = _state_with_hits("conceptual")
    await nodes_module.fuse_node(state)
    assert captured_rrf["weights"] == nodes_module._CONCEPTUAL_WEIGHTS
    assert captured_rrf["weights"]["dense"] == 1.5
    assert captured_rrf["weights"]["sparse"] == 0.5
    assert captured_rrf["weights"]["graph"] == 1.0


@pytest.mark.unit
async def test_fuse_node_mixed_intent_applies_uniform_weights(
    captured_rrf: dict[str, Any],
) -> None:
    state = _state_with_hits("mixed")
    await nodes_module.fuse_node(state)
    assert captured_rrf["weights"] == nodes_module._UNIFORM_WEIGHTS
    assert set(captured_rrf["weights"].values()) == {1.0}


@pytest.mark.unit
async def test_fuse_node_missing_intent_applies_uniform_weights(
    captured_rrf: dict[str, Any],
) -> None:
    state = _state_with_hits(None)
    await nodes_module.fuse_node(state)
    assert captured_rrf["weights"] == nodes_module._UNIFORM_WEIGHTS


@pytest.mark.unit
async def test_fuse_node_none_intent_applies_uniform_weights(
    captured_rrf: dict[str, Any],
) -> None:
    """Explicit ``query_intent=None`` (parser failure) must behave identically
    to a fully-unset intent — degrade to uniform."""

    state = _state_with_hits(None)
    state["query_intent"] = None
    await nodes_module.fuse_node(state)
    assert captured_rrf["weights"] == nodes_module._UNIFORM_WEIGHTS


@pytest.mark.unit
async def test_fuse_node_passes_named_rankings_to_rrf(
    captured_rrf: dict[str, Any],
) -> None:
    """Regression guard against future drift back to positional rankings —
    weights only make sense when each arm has an identity."""

    state = _state_with_hits("factual")
    await nodes_module.fuse_node(state)
    rankings = captured_rrf["rankings"]
    assert isinstance(rankings, dict)
    assert set(rankings.keys()) == {"dense", "sparse", "graph"}
    assert [c.id for c in rankings["dense"]] == ["d1"]
    assert [c.id for c in rankings["sparse"]] == ["s1"]
    assert [c.id for c in rankings["graph"]] == ["g1"]
