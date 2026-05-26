"""Observation Apparatus Refinement Stage 2 — invariants on AmbientRecallResponse.

Stage 2 extended ``AmbientRecallResponse`` with a ``dormant`` list. These
unit tests pin the type-level guarantees so the rest of the system can
rely on the new field without defensive None-checks.
"""

from __future__ import annotations

from gaottt.core.types import (
    AmbientMemory,
    AmbientRecallResponse,
    ScoreBreakdown,
)


def test_default_dormant_is_empty_list() -> None:
    """A fresh response has an empty dormant list, not None."""
    r = AmbientRecallResponse()
    assert r.dormant == []
    assert isinstance(r.dormant, list)


def test_dormant_is_independent_from_direct_and_lensing() -> None:
    """The three lists are independent — mutating one does not affect others."""
    r = AmbientRecallResponse()
    r.direct.append(_make_memory("a"))
    r.lensing.append(_make_memory("b"))
    r.dormant.append(_make_memory("c"))
    assert [m.id for m in r.direct] == ["a"]
    assert [m.id for m in r.lensing] == ["b"]
    assert [m.id for m in r.dormant] == ["c"]


def test_dormant_carries_reason_via_breakdown() -> None:
    """Stage 1 ↔ Stage 2: a dormant slot stores its reason inside breakdown."""
    bd = ScoreBreakdown(
        bm25_score=0.7,
        bm25_contributed=True,
        dormant_percentile=8.0,
        node_mass=1.1,
        reason="dormant surface (percentile=8, mass=1.10) — counter-importance sampling",
    )
    m = AmbientMemory(id="x", content="...", breakdown=bd)
    r = AmbientRecallResponse(dormant=[m], count=1)
    assert r.dormant[0].breakdown is not None
    assert r.dormant[0].breakdown.reason is not None
    assert "dormant surface" in r.dormant[0].breakdown.reason


def _make_memory(node_id: str) -> AmbientMemory:
    return AmbientMemory(id=node_id, content=f"content {node_id}")
