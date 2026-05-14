"""Phase O Stage 3 — unit tests for the routing-hint formatter.

Tests only the formatter helper (`_format_routing_hint`) and the trailer
attachment via ``format_recall`` / ``format_explore`` — no engine involved.
"""
from __future__ import annotations

from gaottt.core.types import (
    ExploreResponse,
    MemoryItem,
    RecallResponse,
    RoutingHint,
    ScoreBreakdown,
    TrainingDelta,
)
from gaottt.services.formatters import (
    _format_routing_hint,
    format_explore,
    format_recall,
)


def _item() -> MemoryItem:
    return MemoryItem(
        id="abc12345",
        content="probe content",
        metadata={"source": "user"},
        raw_score=0.5,
        final_score=0.6,
        source="user",
        tags=["t1"],
        displacement_norm=0.01,
        score_breakdown=ScoreBreakdown(virtual_cosine=0.5, decay_factor=1.0),
    )


def test_format_routing_hint_none_returns_empty():
    assert _format_routing_hint(None) == ""


def test_format_routing_hint_no_route_returns_empty():
    h = RoutingHint(aspect=None, pattern_matched=False, auto_routed=False)
    assert _format_routing_hint(h) == ""


def test_format_routing_hint_pattern_no_summary_returns_empty():
    """auto_routed=False (e.g. config off) → no trailer attached."""
    h = RoutingHint(
        aspect="commitments",
        pattern_matched=True,
        auto_routed=False,
        reflect_summary=None,
    )
    assert _format_routing_hint(h) == ""


def test_format_routing_hint_emits_section_when_routed():
    h = RoutingHint(
        aspect="commitments",
        pattern_matched=True,
        auto_routed=True,
        reflect_summary="Active commitments (1):\n  id=abc | hold the line",
    )
    out = _format_routing_hint(h)
    assert "関連 reflect サマリ" in out
    assert "auto-routed" in out
    assert "commitments" in out
    assert "hold the line" in out


def test_format_recall_appends_trailer_when_routed():
    r = RecallResponse(
        items=[_item()],
        count=1,
        training_delta=TrainingDelta(cache_hit=True),
        routing_hint=RoutingHint(
            aspect="values", pattern_matched=True, auto_routed=True,
            reflect_summary="Values (1):\n  honesty",
        ),
    )
    out = format_recall(r)
    assert "auto-routed" in out
    assert "honesty" in out
    # original recall structure preserved
    assert "abc12345" in out


def test_format_recall_no_items_still_surfaces_routing_summary():
    """The whole point of routing: when free-form recall is empty, the reflect
    summary still surfaces (Phase O Stage 3 substitution)."""
    r = RecallResponse(
        items=[],
        count=0,
        routing_hint=RoutingHint(
            aspect="commitments", pattern_matched=True, auto_routed=True,
            reflect_summary="Active commitments (1):\n  promised X",
        ),
    )
    out = format_recall(r)
    assert "No memories found." in out
    assert "auto-routed" in out
    assert "promised X" in out


def test_format_explore_appends_trailer_when_routed():
    r = ExploreResponse(
        items=[_item()],
        count=1,
        diversity=0.5,
        routing_hint=RoutingHint(
            aspect="intentions", pattern_matched=True, auto_routed=True,
            reflect_summary="Intentions (1):\n  ship Phase O",
        ),
    )
    out = format_explore(r)
    assert "auto-routed" in out
    assert "ship Phase O" in out
