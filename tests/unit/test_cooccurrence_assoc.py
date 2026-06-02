"""Lateral Association Stage 8 — degree-normalized association strength.

Covers the cache primitive (``CacheLayer.get_association_strength`` /
``get_degree``) and its first consumer (Stage 5 lensing resonance via
``services.memory._lensing_resonance``). The headline property: raw co-recall
counts cannot distinguish a promiscuous hub from a specific neighbour (both
carry equal weight to the anchor), but the normalized strength demotes the
hub — which is what fixes the "〇〇といえば〜" specificity axis.
"""
from __future__ import annotations

import math
from types import SimpleNamespace

from gaottt.config import GaOTTTConfig
from gaottt.services.memory import _lensing_resonance
from gaottt.store.cache import CacheLayer


# --- Cache primitive -------------------------------------------------------

def test_none_mode_is_raw_counts_bit_exact():
    """``mode="none"`` returns the raw co-recall counts — identical to
    ``get_neighbors`` (legacy, bit-exact default)."""
    cache = CacheLayer()
    cache.set_edge("a", "b", 2.0)
    cache.set_edge("a", "c", 7.0)
    assert cache.get_association_strength("a", mode="none") == {"b": 2.0, "c": 7.0}
    assert cache.get_association_strength("a", mode="none") == cache.get_neighbors("a")


def test_degree_is_sum_of_incident_weights_and_invalidates():
    """``deg(x) = Σ incident edge weights``; mutating an edge recomputes it."""
    cache = CacheLayer()
    cache.set_edge("a", "b", 1.0)
    assert cache.get_degree("a") == 1.0
    cache.set_edge("a", "c", 3.0)  # invalidates the lazy degree cache
    assert cache.get_degree("a") == 4.0
    cache.remove_edge("a", "b")    # invalidates again
    assert cache.get_degree("a") == 3.0


def test_cosine_demotes_hub_below_specific_neighbour():
    """A promiscuous hub and a specific neighbour can carry equal raw weight
    to ``a``; cosine normalization divides the hub down by its degree."""
    cache = CacheLayer()
    # b: specific — only co-occurs with a
    cache.set_edge("a", "b", 1.0)
    # hub: co-occurs with a AND four others (high degree, promiscuous)
    cache.set_edge("a", "hub", 1.0)
    for x in ("w", "x", "y", "z"):
        cache.set_edge("hub", x, 10.0)

    raw = cache.get_association_strength("a", mode="none")
    assert raw["b"] == raw["hub"] == 1.0  # raw cannot tell them apart

    cos = cache.get_association_strength("a", mode="cosine")
    assert cos["b"] > cos["hub"]                      # specificity wins
    # b: 1/sqrt(deg(a)=2 · deg(b)=1) = 1/sqrt(2)
    assert math.isclose(cos["b"], 1.0 / math.sqrt(2.0), rel_tol=1e-9)


def test_pmi_is_positive_and_clamps_overexpected_to_zero():
    """Positive PMI: a less-than-chance co-occurrence (hub) clamps to 0,
    a stronger-than-chance pair stays positive."""
    cache = CacheLayer()
    cache.set_edge("a", "b", 1.0)
    cache.set_edge("a", "hub", 1.0)
    for x in ("w", "x", "y", "z"):
        cache.set_edge("hub", x, 10.0)

    pmi = cache.get_association_strength("a", mode="pmi")
    assert pmi["b"] > 0.0           # specific pair: above chance
    assert pmi["hub"] == 0.0        # hub link: at/below chance → clamped
    assert all(v >= 0.0 for v in pmi.values())


def test_hub_degree_cut_drops_high_degree_neighbours():
    """The optional percentile cut removes neighbours whose degree exceeds
    the Pth percentile of the active degree distribution."""
    cache = CacheLayer()
    cache.set_edge("a", "b", 1.0)
    cache.set_edge("a", "hub", 1.0)
    for x in ("w", "x", "y", "z"):
        cache.set_edge("hub", x, 10.0)

    # hub degree (1 + 40 = 41) is the max; p50 cut drops it, keeps b.
    cut = cache.get_association_strength("a", mode="cosine", hub_degree_cut=50.0)
    assert "b" in cut
    assert "hub" not in cut


def test_unknown_mode_and_degenerate_inputs_fall_back():
    """Unknown mode → raw; empty graph / deg=0 node → empty/raw, no crash."""
    cache = CacheLayer()
    cache.set_edge("a", "b", 4.0)
    assert cache.get_association_strength("a", mode="bogus") == {"b": 4.0}
    assert cache.get_association_strength("missing", mode="cosine") == {}
    assert cache.get_degree("missing") == 0.0


# --- Consumer: Stage 5 lensing resonance -----------------------------------

def _engine(mode: str) -> SimpleNamespace:
    cache = CacheLayer()
    # Today's direct hits: D1, D2.
    # S (specific lensing): co-occurs ONLY with the two direct hits.
    cache.set_edge("S", "D1", 5.0)
    cache.set_edge("S", "D2", 5.0)
    # H (hub lensing): co-occurs with D1, D2 AND twenty unrelated nodes.
    cache.set_edge("H", "D1", 5.0)
    cache.set_edge("H", "D2", 5.0)
    for i in range(20):
        cache.set_edge("H", f"x{i}", 5.0)
    cfg = GaOTTTConfig(cooccurrence_assoc_normalization=mode)
    return SimpleNamespace(config=cfg, cache=cache)


def test_resonance_legacy_cannot_distinguish_hub_from_specific():
    """The bug Stage 8 fixes: raw counts give the hub and the specific pick
    the same resonance, because only the D1/D2 edges are summed."""
    direct = ["D1", "D2"]
    eng = _engine("none")
    r_s = _lensing_resonance("S", direct, eng, scale=10.0)
    r_h = _lensing_resonance("H", direct, eng, scale=10.0)
    assert math.isclose(r_s, r_h, rel_tol=1e-9)
    assert math.isclose(r_s, 10.0 / 20.0, rel_tol=1e-9)  # raw 5+5 over scale 10


def test_resonance_cosine_demotes_hub_lensing_pick():
    """Under cosine normalization the hub lensing pick earns *lower* trust
    than the specific one — the field stops trusting promiscuous picks."""
    direct = ["D1", "D2"]
    eng = _engine("cosine")
    r_s = _lensing_resonance("S", direct, eng, scale=1.0)
    r_h = _lensing_resonance("H", direct, eng, scale=1.0)
    assert r_s > r_h
