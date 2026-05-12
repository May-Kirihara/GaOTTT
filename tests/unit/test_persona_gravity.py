"""Phase J Stage 1 — Persona-anchored gravity boost (unit tests).

Tests the proximity calculation that powers the persona-anchored seed boost
in propagate_gravity_wave. The math we pin down:

  - 0 hop (persona node itself) → proximity = 1.0
  - 1 hop reachable via fulfills / derived_from → decay**1
  - 2 hop chain → decay**2
  - Beyond persona_max_hop → absent from the result (treated as 0.0)
  - Reachable from multiple persona nodes → smallest hop wins
  - Empty persona set → empty result
  - persona_boost_enabled=False → collect_active_persona_ids returns ∅
"""
from __future__ import annotations

from gaottt.config import GaOTTTConfig
from gaottt.core.persona_gravity import (
    collect_active_persona_ids,
    compute_persona_proximities,
)
from gaottt.store.cache import CacheLayer


def _make_cache_with_edges(
    sources: dict[str, str],
    edges: list[tuple[str, str, str]],
) -> CacheLayer:
    """Build a minimal CacheLayer with the requested source map and edges."""
    cache = CacheLayer()
    for nid, src in sources.items():
        cache.set_source(nid, src)
    for src, dst, et in edges:
        cache.set_directed_edge(src, dst, et)
    return cache


# ---------------------------------------------------------------------------
# collect_active_persona_ids
# ---------------------------------------------------------------------------

def test_collect_active_persona_picks_value_intention_commitment():
    cache = _make_cache_with_edges(
        sources={
            "v1": "value",
            "i1": "intention",
            "c1": "commitment",
            "a1": "agent",
            "t1": "task",
            "f1": "file",
        },
        edges=[],
    )
    config = GaOTTTConfig()
    result = collect_active_persona_ids(cache, config, now=0.0)
    assert result == {"v1", "i1", "c1"}


def test_collect_active_persona_empty_when_disabled():
    cache = _make_cache_with_edges(
        sources={"v1": "value", "i1": "intention"}, edges=[],
    )
    config = GaOTTTConfig(persona_boost_enabled=False)
    assert collect_active_persona_ids(cache, config, now=0.0) == set()


def test_collect_active_persona_empty_when_no_persona_nodes():
    cache = _make_cache_with_edges(
        sources={"a1": "agent", "t1": "task"}, edges=[],
    )
    config = GaOTTTConfig()
    assert collect_active_persona_ids(cache, config, now=0.0) == set()


# ---------------------------------------------------------------------------
# compute_persona_proximities — graph traversal
# ---------------------------------------------------------------------------

def test_proximity_zero_hop_self_is_one():
    cache = _make_cache_with_edges(sources={"v1": "value"}, edges=[])
    config = GaOTTTConfig(persona_max_hop=2, persona_hop_decay=0.5)
    p = compute_persona_proximities({"v1"}, cache, config)
    assert p == {"v1": 1.0}


def test_proximity_one_hop_outgoing():
    # v1 → fulfills → c1 (Phase D: commit task → parent — here the edge
    # direction doesn't matter, Stage 1 treats every directed edge as a
    # persona-gravity line).
    cache = _make_cache_with_edges(
        sources={"v1": "value", "c1": "commitment"},
        edges=[("v1", "c1", "derived_from")],
    )
    config = GaOTTTConfig(persona_max_hop=2, persona_hop_decay=0.5)
    p = compute_persona_proximities({"v1"}, cache, config)
    assert p["v1"] == 1.0
    assert abs(p["c1"] - 0.5) < 1e-9


def test_proximity_one_hop_incoming():
    # task t1 fulfills intention i1 — edge is (t1 → i1, "fulfills"). From
    # the persona side we must walk *incoming* edges.
    cache = _make_cache_with_edges(
        sources={"i1": "intention", "t1": "task"},
        edges=[("t1", "i1", "fulfills")],
    )
    config = GaOTTTConfig(persona_max_hop=2, persona_hop_decay=0.5)
    p = compute_persona_proximities({"i1"}, cache, config)
    assert p["i1"] == 1.0
    assert abs(p["t1"] - 0.5) < 1e-9


def test_proximity_two_hop_chain():
    # i1 ← fulfills ← t1 ← completed ← a1   (typical Phase D shape)
    cache = _make_cache_with_edges(
        sources={"i1": "intention", "t1": "task", "a1": "agent"},
        edges=[
            ("t1", "i1", "fulfills"),
            ("a1", "t1", "completed"),
        ],
    )
    config = GaOTTTConfig(persona_max_hop=2, persona_hop_decay=0.5)
    p = compute_persona_proximities({"i1"}, cache, config)
    assert abs(p["t1"] - 0.5) < 1e-9
    assert abs(p["a1"] - 0.25) < 1e-9


def test_proximity_truncated_at_max_hop():
    # 3 hop chain, max_hop=2 → 3-hop node is absent
    cache = _make_cache_with_edges(
        sources={
            "i1": "intention",
            "t1": "task",
            "a1": "agent",
            "x1": "agent",
        },
        edges=[
            ("t1", "i1", "fulfills"),
            ("a1", "t1", "completed"),
            ("x1", "a1", "derived_from"),
        ],
    )
    config = GaOTTTConfig(persona_max_hop=2, persona_hop_decay=0.5)
    p = compute_persona_proximities({"i1"}, cache, config)
    assert "x1" not in p  # 3 hop beyond max
    assert "a1" in p       # 2 hop reachable
    assert "t1" in p       # 1 hop reachable


def test_proximity_min_hop_wins_with_multiple_persona():
    # n1 is 2 hop from i1 but 1 hop from c1 — should get the 1-hop proximity
    cache = _make_cache_with_edges(
        sources={
            "i1": "intention",
            "c1": "commitment",
            "t1": "task",
            "n1": "agent",
        },
        edges=[
            ("t1", "i1", "fulfills"),
            ("n1", "t1", "derived_from"),  # 2 hop from i1
            ("n1", "c1", "derived_from"),  # 1 hop from c1
        ],
    )
    config = GaOTTTConfig(persona_max_hop=2, persona_hop_decay=0.5)
    p = compute_persona_proximities({"i1", "c1"}, cache, config)
    assert abs(p["n1"] - 0.5) < 1e-9  # min hop = 1 wins


def test_proximity_empty_persona_returns_empty():
    cache = _make_cache_with_edges(
        sources={"a1": "agent"}, edges=[],
    )
    config = GaOTTTConfig(persona_max_hop=2)
    assert compute_persona_proximities(set(), cache, config) == {}


def test_proximity_zero_decay_collapses_to_persona_only():
    cache = _make_cache_with_edges(
        sources={"i1": "intention", "t1": "task"},
        edges=[("t1", "i1", "fulfills")],
    )
    config = GaOTTTConfig(persona_max_hop=2, persona_hop_decay=0.0)
    p = compute_persona_proximities({"i1"}, cache, config)
    # Persona node itself stays at 1.0, no propagation
    assert p == {"i1": 1.0}


def test_proximity_max_hop_zero_returns_persona_only():
    cache = _make_cache_with_edges(
        sources={"i1": "intention", "t1": "task"},
        edges=[("t1", "i1", "fulfills")],
    )
    config = GaOTTTConfig(persona_max_hop=0, persona_hop_decay=0.5)
    p = compute_persona_proximities({"i1"}, cache, config)
    assert p == {"i1": 1.0}


def test_proximity_handles_cycle_without_infinite_loop():
    # Cyclic 3-node graph; BFS should terminate after the first visit
    cache = _make_cache_with_edges(
        sources={"i1": "intention", "a1": "agent", "a2": "agent"},
        edges=[
            ("a1", "i1", "derived_from"),
            ("a2", "a1", "derived_from"),
            ("a1", "a2", "derived_from"),  # cycle back to a2
        ],
    )
    config = GaOTTTConfig(persona_max_hop=3, persona_hop_decay=0.5)
    p = compute_persona_proximities({"i1"}, cache, config)
    # i1=0, a1=1 (incoming derived_from), a2=2 (via a1)
    assert abs(p["a1"] - 0.5) < 1e-9
    assert abs(p["a2"] - 0.25) < 1e-9
