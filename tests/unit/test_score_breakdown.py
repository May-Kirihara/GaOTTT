"""Phase O Stage 1 — unit tests for ScoreBreakdown additive decomposition.

The breakdown reproduces final_score within FP tolerance:
    final = (virtual_cosine * decay_factor + wave_score + mass_boost
            + emotion_term + certainty_term) * saturation

Informational fields (raw_cosine, persona_proximity, bm25_contributed,
forced_inclusion) do not enter the sum.
"""
from __future__ import annotations

import math

import pytest

from gaottt.core.types import ScoreBreakdown


def test_breakdown_expected_sum_zero_when_all_zero():
    b = ScoreBreakdown()
    assert b.expected_sum == 0.0


def test_breakdown_reproduces_final_score_typical():
    b = ScoreBreakdown(
        raw_cosine=0.42,           # informational, not in sum
        virtual_cosine=0.50,
        decay_factor=0.95,
        wave_score=0.10,
        mass_boost=0.07,
        emotion_term=0.02,
        certainty_term=0.01,
        saturation=0.80,
    )
    expected = (0.50 * 0.95 + 0.10 + 0.07 + 0.02 + 0.01) * 0.80
    assert math.isclose(b.expected_sum, expected, rel_tol=1e-9)


def test_breakdown_informational_fields_do_not_enter_sum():
    base = ScoreBreakdown(
        virtual_cosine=0.5, decay_factor=1.0, saturation=1.0,
    )
    with_persona = ScoreBreakdown(
        virtual_cosine=0.5, decay_factor=1.0, saturation=1.0,
        persona_proximity=0.9, bm25_contributed=True, forced_inclusion=True,
        raw_cosine=0.7,
    )
    assert math.isclose(base.expected_sum, with_persona.expected_sum)


def test_breakdown_saturation_multiplicative():
    """Saturation < 1 dampens everything, not just additive terms."""
    no_sat = ScoreBreakdown(
        virtual_cosine=1.0, decay_factor=1.0, wave_score=0.5, saturation=1.0,
    )
    half_sat = ScoreBreakdown(
        virtual_cosine=1.0, decay_factor=1.0, wave_score=0.5, saturation=0.5,
    )
    assert math.isclose(half_sat.expected_sum, no_sat.expected_sum * 0.5)


def test_breakdown_decay_applies_only_to_virtual_cosine():
    """Decay multiplies virtual_cosine, but wave/mass/emotion/certainty escape."""
    b = ScoreBreakdown(
        virtual_cosine=1.0, decay_factor=0.0,  # decay kills virtual contribution
        wave_score=0.3, mass_boost=0.2, saturation=1.0,
    )
    assert math.isclose(b.expected_sum, 0.5)  # 0 + 0.3 + 0.2


def test_breakdown_negative_emotion_subtracts():
    """Negative emotion (sadness, anger) reduces final_score."""
    pos = ScoreBreakdown(virtual_cosine=0.5, decay_factor=1.0, emotion_term=0.05, saturation=1.0)
    neg = ScoreBreakdown(virtual_cosine=0.5, decay_factor=1.0, emotion_term=-0.05, saturation=1.0)
    assert pos.expected_sum > neg.expected_sum


def test_breakdown_default_values_correct():
    """Default ScoreBreakdown reproduces 'no result' state cleanly."""
    b = ScoreBreakdown()
    assert b.raw_cosine == 0.0
    assert b.virtual_cosine == 0.0
    assert b.decay_factor == 1.0
    assert b.wave_score == 0.0
    assert b.mass_boost == 0.0
    assert b.emotion_term == 0.0
    assert b.certainty_term == 0.0
    assert b.saturation == 1.0
    assert b.persona_proximity == 0.0
    assert b.bm25_contributed is False
    assert b.forced_inclusion is False


def test_breakdown_serializes_to_dict():
    """Pydantic round-trip preserves all fields."""
    b = ScoreBreakdown(
        raw_cosine=0.42, virtual_cosine=0.5, decay_factor=0.9,
        wave_score=0.1, mass_boost=0.07, emotion_term=0.02,
        certainty_term=0.01, saturation=0.8, persona_proximity=0.3,
        bm25_contributed=True, forced_inclusion=False,
    )
    d = b.model_dump()
    b2 = ScoreBreakdown.model_validate(d)
    assert b2.raw_cosine == pytest.approx(0.42)
    assert b2.bm25_contributed is True
    assert b2.forced_inclusion is False
    assert math.isclose(b.expected_sum, b2.expected_sum)
