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
    """Among candidates clearing the floors, the largest virtual−raw gap wins.

    Stage 3 returns top-K (default max_k=2); ``max_k=1`` here pins the
    classic Stage 1/2 "single best pick" behaviour.
    """
    engine = _engine(ambient_lensing_max_k=1)  # defaults: enabled, min_score 0.5, min_gap 0.05
    items = [
        _item("a", 0.80, 0.82),  # gap 0.02 — below min_gap → not a candidate
        _item("b", 0.30, 0.75),  # gap 0.45 — biggest, virt ≥ 0.5 → candidate
        _item("c", 0.20, 0.40),  # virt 0.40 < min_score 0.5 → excluded
        _item("d", 0.50, 0.62),  # gap 0.12 — candidate, smaller than b
    ]
    picks = _pick_lensing(engine, items, exclude=set())
    assert len(picks) == 1
    item, gap = picks[0]
    assert item.id == "b"
    assert abs(gap - 0.45) < 1e-9


def test_pick_lensing_respects_exclude():
    """The direct-hit ids are excluded so lensing never duplicates them."""
    engine = _engine(ambient_lensing_max_k=1)
    items = [_item("b", 0.30, 0.75), _item("d", 0.50, 0.62)]
    picks = _pick_lensing(engine, items, exclude={"b"})
    assert len(picks) == 1
    assert picks[0][0].id == "d"


def test_pick_lensing_noise_floor_can_empty_the_slot():
    """All candidates below the virtual_cosine floor → no lensing picks."""
    engine = _engine()
    items = [_item("c", 0.05, 0.40), _item("e", 0.10, 0.45)]
    assert _pick_lensing(engine, items, exclude=set()) == []


def test_pick_lensing_disabled_returns_empty():
    engine = _engine(ambient_lensing_enabled=False)
    items = [_item("b", 0.30, 0.95)]
    assert _pick_lensing(engine, items, exclude=set()) == []


def test_pick_lensing_skips_items_without_breakdown():
    """A None score_breakdown (Phase O disabled) cannot be measured → skipped."""
    engine = _engine()
    no_bd = MemoryItem(id="x", content="x", raw_score=0.9, final_score=0.5)
    assert _pick_lensing(engine, [no_bd], exclude=set()) == []


# --- Lateral Association Stage 5 — lensing resonance --------------------------


def test_lensing_resonance_zero_when_no_cooccurrence():
    """resonance must be 0.0 when the lensing pick has no cooccurrence edges
    to any direct id (the field has never pulled them together)."""
    from gaottt.services.memory import _lensing_resonance

    class _FakeCache:
        def get_neighbors(self, node_id):
            return {}

    class _FakeEngine:
        cache = _FakeCache()

    res = _lensing_resonance(
        "lensing_id", ["direct_a", "direct_b"], _FakeEngine(), scale=10.0,
    )
    assert res == 0.0


def test_lensing_resonance_saturates_with_cooccurrence_count():
    """``raw / (raw + scale)`` saturates toward 1.0. Pin the exact formula so
    a future re-derivation doesn't quietly change agent-visible numbers."""
    from gaottt.services.memory import _lensing_resonance

    class _FakeCache:
        def __init__(self, weights):
            self._w = weights

        def get_neighbors(self, node_id):
            return self._w.get(node_id, {})

    class _FakeEngine:
        def __init__(self, weights):
            self.cache = _FakeCache(weights)

    # Lensing has 3+7=10 cooccurrence count with direct pair → resonance 0.5
    eng = _FakeEngine({"L": {"D1": 3.0, "D2": 7.0}})
    res = _lensing_resonance("L", ["D1", "D2"], eng, scale=10.0)
    assert abs(res - 0.5) < 1e-9, res
    # Higher count saturates higher
    eng = _FakeEngine({"L": {"D1": 90.0}})
    res = _lensing_resonance("L", ["D1"], eng, scale=10.0)
    assert abs(res - (90.0 / 100.0)) < 1e-9, res


def test_lensing_resonance_scale_zero_short_circuits():
    """``scale=0`` is a degenerate "any cooccurrence is fully trusted" mode."""
    from gaottt.services.memory import _lensing_resonance

    class _FakeCache:
        def __init__(self, weights):
            self._w = weights

        def get_neighbors(self, node_id):
            return self._w.get(node_id, {})

    class _FakeEngine:
        def __init__(self, weights):
            self.cache = _FakeCache(weights)

    eng = _FakeEngine({"L": {"D1": 0.5}})
    assert _lensing_resonance("L", ["D1"], eng, scale=0.0) == 1.0
    eng = _FakeEngine({"L": {}})
    assert _lensing_resonance("L", ["D1"], eng, scale=0.0) == 0.0


def test_pick_lensing_returns_top_k_ranked_by_gap_descending():
    """Stage 3 — ``ambient_lensing_max_k > 1`` returns multiple picks ranked
    by gap descending. All kept picks still individually clear the gates."""
    engine = _engine(ambient_lensing_max_k=3)
    items = [
        _item("a", 0.80, 0.82),  # gap 0.02 — below min_gap (default 0.05) → excluded
        _item("b", 0.30, 0.75),  # gap 0.45 — top
        _item("c", 0.20, 0.40),  # virt < 0.5 → excluded
        _item("d", 0.50, 0.62),  # gap 0.12
        _item("e", 0.30, 0.60),  # gap 0.30
        _item("f", 0.40, 0.55),  # gap 0.15 — below b/e/d? b(0.45)>e(0.30)>f(0.15)>d(0.12)
    ]
    picks = _pick_lensing(engine, items, exclude=set())
    # 4 candidates clear (b, d, e, f); cap = 3, so top-3 by gap.
    assert len(picks) == 3
    ranked_ids = [p[0].id for p in picks]
    assert ranked_ids == ["b", "e", "f"], (
        f"Stage 3 ranking by gap desc broken: {ranked_ids}"
    )


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
