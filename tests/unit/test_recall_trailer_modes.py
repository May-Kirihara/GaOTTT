"""Instruction Surface Hygiene Stage 2b — recall trailer/breakdown verbose gating.

Pure unit tests: construct RecallResponse models and call format_recall with
various output_mode / verbose combinations.
"""
from __future__ import annotations

from gaottt.core.types import (
    MemoryItem,
    RecallResponse,
    ScoreBreakdown,
    TrainingDelta,
)
from gaottt.services import formatters


def _item(content: str = "test content", *, mid: str = "item1abcd") -> MemoryItem:
    return MemoryItem(
        id=mid,
        content=content,
        raw_score=0.85,
        final_score=0.90,
        source="agent",
        tags=["test"],
        displacement_norm=0.1,
        score_breakdown=ScoreBreakdown(
            raw_cosine=0.8,
            virtual_cosine=0.85,
            decay_factor=0.99,
            wave_score=0.02,
            mass_boost=0.01,
            emotion_term=0.0,
            certainty_term=0.0,
            saturation=1.0,
            persona_proximity=0.0,
        ),
    )


def _response(
    items: list[MemoryItem] | None = None,
    td: TrainingDelta | None = None,
) -> RecallResponse:
    return RecallResponse(
        items=items or [_item()],
        count=len(items) if items else 1,
        training_delta=td or TrainingDelta(
            mass_changes={"node_a": 0.001},
            displacement_changes={"node_b": -0.002},
            wave_reached_count=5,
            wave_max_depth=3,
            persona_hop_reached=0,
        ),
    )


def test_verbose_true_shows_breakdown_and_trailer():
    resp = _response()
    out = formatters.format_recall(resp, output_mode="full", verbose=True)
    assert "breakdown:" in out
    assert "## 訓練差分" in out
    assert "wave_reached=" in out


def test_verbose_false_suppresses_breakdown():
    resp = _response()
    out = formatters.format_recall(resp, output_mode="full", verbose=False)
    assert "breakdown:" not in out


def test_verbose_false_suppresses_trailer():
    resp = _response()
    out = formatters.format_recall(resp, output_mode="full", verbose=False)
    assert "## 訓練差分" not in out


def test_verbose_false_keeps_routing_hint():
    from gaottt.core.types import RoutingHint

    resp = _response()
    resp.routing_hint = RoutingHint(
        aspect="commitments",
        pattern_matched=True,
        auto_routed=True,
        reflect_summary="Active commitments: ...",
    )
    out = formatters.format_recall(resp, output_mode="ids", verbose=False)
    assert "auto-routed" in out


def test_ids_verbose_false_no_breakdown_no_trailer():
    resp = _response()
    out = formatters.format_recall(resp, output_mode="ids", verbose=False)
    assert "breakdown:" not in out
    assert "## 訓練差分" not in out


def test_compact_verbose_false_still_has_content():
    long = "z" * 500
    resp = _response(items=[_item(long)])
    out = formatters.format_recall(resp, output_mode="compact", verbose=False)
    assert "z" * 500 not in out
    assert "…(500 chars)" in out
    assert "breakdown:" not in out


def test_default_verbose_is_true():
    resp = _response()
    out = formatters.format_recall(resp, output_mode="full")
    assert "breakdown:" in out
    assert "## 訓練差分" in out


def test_empty_results_no_trailer():
    resp = RecallResponse(items=[], count=0)
    out = formatters.format_recall(resp, output_mode="full", verbose=False)
    assert out == "No memories found."


def _item_with_reason(reason: str = "dominance artifact detected") -> MemoryItem:
    bd = ScoreBreakdown(
        raw_cosine=0.8,
        virtual_cosine=0.85,
        decay_factor=0.99,
        wave_score=0.02,
        mass_boost=0.01,
        emotion_term=0.0,
        certainty_term=0.0,
        saturation=1.0,
        persona_proximity=0.0,
        reason=reason,
    )
    return MemoryItem(
        id="reason1abcd",
        content="test content",
        raw_score=0.85,
        final_score=0.90,
        source="agent",
        tags=["test"],
        displacement_norm=0.1,
        score_breakdown=bd,
    )


def _resp_with_reason() -> RecallResponse:
    return RecallResponse(
        items=[_item_with_reason()],
        count=1,
        training_delta=None,
    )


def test_show_reason_compact_mode():
    out = formatters.format_recall(
        _resp_with_reason(), output_mode="compact", verbose=False, show_reason=True,
    )
    assert "reason: dominance artifact detected" in out
    assert "breakdown:" not in out


def test_show_reason_ids_mode():
    out = formatters.format_recall(
        _resp_with_reason(), output_mode="ids", verbose=False, show_reason=True,
    )
    assert "reason: dominance artifact detected" in out
    assert "breakdown:" not in out


def test_show_reason_false_compact_suppresses_reason():
    out = formatters.format_recall(
        _resp_with_reason(), output_mode="compact", verbose=False, show_reason=False,
    )
    assert "reason:" not in out
    assert "breakdown:" not in out


def test_show_reason_none_legacy_verbose_true_still_has_reason():
    out = formatters.format_recall(
        _resp_with_reason(), output_mode="full", verbose=True, show_reason=None,
    )
    assert "reason: dominance artifact detected" in out
    assert "breakdown:" in out
