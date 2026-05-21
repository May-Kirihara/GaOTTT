"""Ambient Recall Enrichment — unit tests for the gravitational-lensing pick.

``_pick_lensing`` selects the memory with the largest virtual−raw cosine gap
(the association the gravity field *learned*), subject to a noise floor on
virtual_cosine and a minimum gap. Pure function over MemoryItem breakdowns —
exercised here with constructed breakdowns, no engine.
"""
from __future__ import annotations

from types import SimpleNamespace

from gaottt.config import GaOTTTConfig
from gaottt.core.types import MemoryItem, ScoreBreakdown
from gaottt.index.bm25_index import BM25Index
from gaottt.services.memory import _bm25_gate, _pick_lensing


def _item(node_id: str, raw_cos: float, virt_cos: float) -> MemoryItem:
    return MemoryItem(
        id=node_id,
        content=f"content-{node_id}",
        raw_score=virt_cos,
        final_score=0.5,
        score_breakdown=ScoreBreakdown(
            raw_cosine=raw_cos, virtual_cosine=virt_cos,
        ),
    )


def _engine(**overrides):
    return SimpleNamespace(config=GaOTTTConfig(**overrides))


def test_pick_lensing_selects_max_gap():
    """Among candidates clearing the floors, the largest virtual−raw gap wins."""
    engine = _engine()  # defaults: enabled, min_score 0.5, min_gap 0.05
    items = [
        _item("a", 0.80, 0.82),  # gap 0.02 — below min_gap → not a candidate
        _item("b", 0.30, 0.75),  # gap 0.45 — biggest, virt ≥ 0.5 → candidate
        _item("c", 0.20, 0.40),  # virt 0.40 < min_score 0.5 → excluded
        _item("d", 0.50, 0.62),  # gap 0.12 — candidate, smaller than b
    ]
    picked = _pick_lensing(engine, items, exclude=set())
    assert picked is not None
    item, gap = picked
    assert item.id == "b"
    assert abs(gap - 0.45) < 1e-9


def test_pick_lensing_respects_exclude():
    """The direct-hit ids are excluded so lensing never duplicates them."""
    engine = _engine()
    items = [_item("b", 0.30, 0.75), _item("d", 0.50, 0.62)]
    picked = _pick_lensing(engine, items, exclude={"b"})
    assert picked is not None
    assert picked[0].id == "d"


def test_pick_lensing_noise_floor_can_empty_the_slot():
    """All candidates below the virtual_cosine floor → no lensing pick."""
    engine = _engine()
    items = [_item("c", 0.05, 0.40), _item("e", 0.10, 0.45)]
    assert _pick_lensing(engine, items, exclude=set()) is None


def test_pick_lensing_disabled_returns_none():
    engine = _engine(ambient_lensing_enabled=False)
    items = [_item("b", 0.30, 0.95)]
    assert _pick_lensing(engine, items, exclude=set()) is None


def test_pick_lensing_skips_items_without_breakdown():
    """A None score_breakdown (Phase O disabled) cannot be measured → skipped."""
    engine = _engine()
    no_bd = MemoryItem(id="x", content="x", raw_score=0.9, final_score=0.5)
    assert _pick_lensing(engine, [no_bd], exclude=set()) is None


# --- BM25 lexical relevance gate ----------------------------------------------

def _bm25_engine(**overrides):
    idx = BM25Index()  # trigram is fine here — the test exercises gate logic
    idx.add(
        ["a", "b", "c"],
        [
            "gravitational wave propagation through the seed pool",
            "orbital mechanics and displacement decay",
            "mass conservation in the gravity field",
        ],
    )
    return SimpleNamespace(
        config=GaOTTTConfig(**overrides), ambient_gate_index=idx,
    )


def test_bm25_gate_passes_lexically_overlapping_prompt():
    engine = _bm25_engine(ambient_bm25_min_score=0.01)
    assert _bm25_gate(engine, "gravitational wave propagation") is True


def test_bm25_gate_blocks_disjoint_vocabulary():
    """A prompt with zero shared 3-grams scores BM25 0 → blocked."""
    engine = _bm25_engine(ambient_bm25_min_score=0.01)
    assert _bm25_gate(engine, "りんごジュースの値段") is False


def test_bm25_gate_none_when_disabled():
    """ambient_gate_use_bm25=False → None (caller falls back to virtual_score)."""
    engine = _bm25_engine(ambient_gate_use_bm25=False)
    assert _bm25_gate(engine, "gravitational wave propagation") is None


def test_bm25_gate_none_when_index_absent():
    """No gate index (bm25-sudachi extra missing) → None (fall back)."""
    engine = SimpleNamespace(config=GaOTTTConfig(), ambient_gate_index=None)
    assert _bm25_gate(engine, "gravitational wave propagation") is None
