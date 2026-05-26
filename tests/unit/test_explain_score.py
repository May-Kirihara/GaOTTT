"""Observation Apparatus Refinement Stage 1 — explain_score() unit tests.

These tests pin the reason-line text format so MCP formatter substring
assertions downstream stay stable.
"""

from __future__ import annotations

from gaottt.core.explain import explain_score
from gaottt.core.types import ScoreBreakdown


def test_dormant_surface_wins_outright() -> None:
    """A dormant_percentile signal short-circuits everything else."""
    b = ScoreBreakdown(
        virtual_cosine=0.95,           # would otherwise look like a semantic match
        node_mass=5.0,                  # would otherwise trigger dominance hint
        bm25_score=2.0,                 # would otherwise trigger bm25 match
        dormant_percentile=8.0,
    )
    reason = explain_score(b)
    assert reason is not None
    assert reason.startswith("dormant surface")
    assert "percentile=8" in reason
    assert "mass=5.00" in reason
    assert "counter-importance sampling" in reason


def test_lensing_pick_wins_when_no_dormant() -> None:
    """Lensing-gap signal wins over mass/bm25 (gravity-lensing slot identity)."""
    b = ScoreBreakdown(
        virtual_cosine=0.40,
        node_mass=3.0,
        bm25_score=1.5,
        lensing_gap=0.07,
    )
    reason = explain_score(b)
    assert reason is not None
    assert reason.startswith("lensing pick")
    assert "gap=+0.07" in reason
    assert "semantically distant" in reason


def test_high_mass_low_cosine_flags_dominance() -> None:
    """The canonical Heavy Persona Dominance pattern (mass=2.82, cos=0.42)."""
    b = ScoreBreakdown(
        virtual_cosine=0.42,
        node_mass=2.82,
    )
    reason = explain_score(b)
    assert reason is not None
    assert "high mass persona proximity" in reason
    assert "mass=2.82" in reason
    assert "possible dominance artifact" in reason


def test_high_mass_with_high_cosine_does_not_flag_dominance() -> None:
    """High mass + high cosine is legitimate — no artifact hint."""
    b = ScoreBreakdown(
        virtual_cosine=0.85,
        node_mass=3.0,
    )
    reason = explain_score(b)
    # Falls through to semantic-match fallback, NOT dominance flag
    assert reason is not None
    assert "possible dominance artifact" not in reason
    assert "semantic match" in reason


def test_bm25_strong_match() -> None:
    """BM25 score above strong threshold gets a strong-match label."""
    b = ScoreBreakdown(
        virtual_cosine=0.3,
        bm25_score=0.71,
        bm25_contributed=True,
    )
    reason = explain_score(b)
    assert reason is not None
    assert "bm25 strong lexical match" in reason
    assert "0.71" in reason


def test_bm25_weak_assist() -> None:
    """BM25 contributed but below strong threshold → assist label."""
    b = ScoreBreakdown(
        virtual_cosine=0.55,
        bm25_score=0.15,
        bm25_contributed=True,
    )
    reason = explain_score(b)
    assert reason is not None
    assert "bm25 lexical assist" in reason
    assert "0.15" in reason


def test_dominance_and_bm25_stack() -> None:
    """Both signals fire — they should be joined with ' + '."""
    b = ScoreBreakdown(
        virtual_cosine=0.45,
        node_mass=2.5,
        bm25_score=0.6,
        bm25_contributed=True,
    )
    reason = explain_score(b)
    assert reason is not None
    assert "high mass persona proximity" in reason
    assert "bm25 strong lexical match" in reason
    assert " + " in reason
    assert "possible dominance artifact" in reason


def test_forced_inclusion_is_informational_prefix() -> None:
    b = ScoreBreakdown(
        virtual_cosine=0.5,
        forced_inclusion=True,
        bm25_score=0.6,
        bm25_contributed=True,
    )
    reason = explain_score(b)
    assert reason is not None
    assert "forced via tag/persona_context" in reason
    assert "bm25" in reason


def test_cold_breakdown_returns_none() -> None:
    """An all-zero breakdown has nothing meaningful to say."""
    b = ScoreBreakdown()
    assert explain_score(b) is None


def test_pure_semantic_fallback() -> None:
    """Mid-range cosine with no other signals → semantic-match fallback."""
    b = ScoreBreakdown(virtual_cosine=0.62)
    reason = explain_score(b)
    assert reason is not None
    assert "semantic match" in reason
    assert "0.62" in reason


def test_threshold_overrides_take_effect() -> None:
    """Caller-supplied thresholds change what fires."""
    b = ScoreBreakdown(virtual_cosine=0.4, node_mass=1.5)
    # Default 2.0 threshold — no dominance flag
    assert "high mass" not in (explain_score(b) or "")
    # Lower threshold to 1.0 — dominance flag fires
    assert "high mass" in (
        explain_score(b, mass_dominance_threshold=1.0) or ""
    )


def test_reason_line_length_is_reasonable() -> None:
    """Reason lines stay under ~150 chars for caller readability."""
    b = ScoreBreakdown(
        virtual_cosine=0.45,
        node_mass=2.82,
        bm25_score=0.71,
        bm25_contributed=True,
        forced_inclusion=True,
    )
    reason = explain_score(b)
    assert reason is not None
    assert len(reason) <= 200, f"reason line too long: {len(reason)} chars: {reason!r}"
