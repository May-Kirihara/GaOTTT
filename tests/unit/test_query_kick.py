"""Phase I Stage 2 — Implicit query-aware displacement kick (unit tests).

`compute_acceleration` gains a 4th component:
    F_query = α · score · gate · (q - pos);  a_query = F_query / m
    gate = tanh(m / θ)   if θ > 0
    gate = 1.0           if θ = 0  (Stage 2 legacy)

These tests pin down the properties that make the kick safe and
TTT-consistent:
  1. Direction: kick points from pos toward query_anchor.
  2. Score weighting: doubling the score doubles the kick magnitude.
  3. Mass damping: with gate disabled (θ=0), doubling the mass halves the
     kick magnitude (F=ma).
  4. Off-switches: kick is suppressed when α=0, when query_kick_enabled is
     False, or when any of mass_i / query_anchor / query_score is missing.
  5. Stage 3 gating: low-mass nodes get a damped kick (tanh(m/θ)); mature
     nodes get the full kick; θ=0 is identical to Stage 2.
"""
from __future__ import annotations

import math

import numpy as np

from gaottt.config import GaOTTTConfig
from gaottt.core.gravity import compute_acceleration


def _baseline_acc(pos, disp, config):
    """Acceleration with no query kick — just Hooke (neighbors=[], no cache)."""
    return compute_acceleration(
        pos_i=pos, original_pos_i=pos, displacement_i=disp,
        neighbors=[], config=config,
    )


def _kicked_acc(pos, disp, config, *, mass, query, score):
    return compute_acceleration(
        pos_i=pos, original_pos_i=pos, displacement_i=disp,
        neighbors=[], config=config,
        mass_i=mass, query_anchor=query, query_score=score,
    )


def test_query_kick_direction_points_toward_query():
    """The kick component should point from pos toward query_anchor."""
    config = GaOTTTConfig(query_kick_strength=1.0, query_kick_enabled=True)
    dim = config.embedding_dim
    pos = np.zeros(dim, dtype=np.float32)
    pos[0] = 1.0
    query = np.zeros(dim, dtype=np.float32)
    query[1] = 1.0  # along a different axis

    disp = np.zeros(dim, dtype=np.float32)
    base = _baseline_acc(pos, disp, config)
    kicked = _kicked_acc(pos, disp, config, mass=1.0, query=query, score=1.0)

    delta = kicked - base
    expected_dir = (query - pos)
    expected_dir /= np.linalg.norm(expected_dir)
    actual_dir = delta / (np.linalg.norm(delta) + 1e-12)
    assert np.dot(actual_dir, expected_dir) > 0.999


def test_query_kick_scales_linearly_with_score():
    config = GaOTTTConfig(query_kick_strength=1.0, query_kick_enabled=True)
    dim = config.embedding_dim
    pos = np.zeros(dim, dtype=np.float32)
    pos[0] = 1.0
    query = np.zeros(dim, dtype=np.float32)
    query[1] = 1.0
    disp = np.zeros(dim, dtype=np.float32)

    base = _baseline_acc(pos, disp, config)
    a1 = _kicked_acc(pos, disp, config, mass=1.0, query=query, score=0.5) - base
    a2 = _kicked_acc(pos, disp, config, mass=1.0, query=query, score=1.0) - base

    n1 = float(np.linalg.norm(a1))
    n2 = float(np.linalg.norm(a2))
    assert n2 > 0
    assert abs(n2 / n1 - 2.0) < 1e-4


def test_query_kick_mass_damping_F_equals_ma():
    """With Stage 3 gate disabled (θ=0), doubling mass halves a (a = F/m)."""
    config = GaOTTTConfig(
        query_kick_strength=1.0,
        query_kick_enabled=True,
        mass_anchor_threshold=0.0,  # disable Stage 3 gate → pure F=ma
    )
    dim = config.embedding_dim
    pos = np.zeros(dim, dtype=np.float32)
    pos[0] = 1.0
    query = np.zeros(dim, dtype=np.float32)
    query[1] = 1.0
    disp = np.zeros(dim, dtype=np.float32)

    base = _baseline_acc(pos, disp, config)
    a_light = _kicked_acc(pos, disp, config, mass=1.0, query=query, score=1.0) - base
    a_heavy = _kicked_acc(pos, disp, config, mass=10.0, query=query, score=1.0) - base

    n_light = float(np.linalg.norm(a_light))
    n_heavy = float(np.linalg.norm(a_heavy))
    assert n_light > 0
    assert abs(n_heavy / n_light - 0.1) < 1e-4


def test_query_kick_disabled_when_alpha_zero():
    config = GaOTTTConfig(query_kick_strength=0.0, query_kick_enabled=True)
    dim = config.embedding_dim
    pos = np.zeros(dim, dtype=np.float32)
    pos[0] = 1.0
    query = np.zeros(dim, dtype=np.float32)
    query[1] = 1.0
    disp = np.zeros(dim, dtype=np.float32)

    base = _baseline_acc(pos, disp, config)
    kicked = _kicked_acc(pos, disp, config, mass=1.0, query=query, score=1.0)
    assert np.allclose(base, kicked, atol=1e-7)


def test_query_kick_disabled_by_enabled_flag():
    config = GaOTTTConfig(query_kick_strength=1.0, query_kick_enabled=False)
    dim = config.embedding_dim
    pos = np.zeros(dim, dtype=np.float32)
    pos[0] = 1.0
    query = np.zeros(dim, dtype=np.float32)
    query[1] = 1.0
    disp = np.zeros(dim, dtype=np.float32)

    base = _baseline_acc(pos, disp, config)
    kicked = _kicked_acc(pos, disp, config, mass=1.0, query=query, score=1.0)
    assert np.allclose(base, kicked, atol=1e-7)


def test_query_kick_skipped_without_required_inputs():
    """If any of mass / anchor / score is missing the kick is skipped."""
    config = GaOTTTConfig(query_kick_strength=1.0, query_kick_enabled=True)
    dim = config.embedding_dim
    pos = np.zeros(dim, dtype=np.float32)
    pos[0] = 1.0
    query = np.zeros(dim, dtype=np.float32)
    query[1] = 1.0
    disp = np.zeros(dim, dtype=np.float32)

    base = _baseline_acc(pos, disp, config)

    # Missing query_anchor
    a_no_q = compute_acceleration(
        pos_i=pos, original_pos_i=pos, displacement_i=disp,
        neighbors=[], config=config,
        mass_i=1.0, query_anchor=None, query_score=1.0,
    )
    # Missing query_score
    a_no_s = compute_acceleration(
        pos_i=pos, original_pos_i=pos, displacement_i=disp,
        neighbors=[], config=config,
        mass_i=1.0, query_anchor=query, query_score=None,
    )
    # Missing mass_i (legacy callers that don't pass it)
    a_no_m = compute_acceleration(
        pos_i=pos, original_pos_i=pos, displacement_i=disp,
        neighbors=[], config=config,
        mass_i=None, query_anchor=query, query_score=1.0,
    )
    assert np.allclose(base, a_no_q, atol=1e-7)
    assert np.allclose(base, a_no_s, atol=1e-7)
    assert np.allclose(base, a_no_m, atol=1e-7)


# ---------------------------------------------------------------------------
# Phase I Stage 3 — Mass-gated query attraction
# ---------------------------------------------------------------------------

def test_stage3_kick_gated_by_low_mass():
    """mass=1 with θ=3 damps the kick to tanh(1/3) ≈ 0.32 of the un-gated value."""
    cfg_stage2 = GaOTTTConfig(
        query_kick_strength=1.0, query_kick_enabled=True,
        mass_anchor_threshold=0.0,
    )
    cfg_stage3 = GaOTTTConfig(
        query_kick_strength=1.0, query_kick_enabled=True,
        mass_anchor_threshold=3.0,
    )
    dim = cfg_stage3.embedding_dim
    pos = np.zeros(dim, dtype=np.float32)
    pos[0] = 1.0
    query = np.zeros(dim, dtype=np.float32)
    query[1] = 1.0
    disp = np.zeros(dim, dtype=np.float32)

    base_s2 = _baseline_acc(pos, disp, cfg_stage2)
    base_s3 = _baseline_acc(pos, disp, cfg_stage3)
    kick_s2 = _kicked_acc(pos, disp, cfg_stage2, mass=1.0, query=query, score=1.0) - base_s2
    kick_s3 = _kicked_acc(pos, disp, cfg_stage3, mass=1.0, query=query, score=1.0) - base_s3

    n2 = float(np.linalg.norm(kick_s2))
    n3 = float(np.linalg.norm(kick_s3))
    assert n2 > 0
    expected_ratio = math.tanh(1.0 / 3.0)  # ≈ 0.3215
    assert abs(n3 / n2 - expected_ratio) < 1e-4


def test_stage3_kick_full_at_high_mass():
    """mass=20 with θ=3: gate = tanh(20/3) ≈ 0.9999 — mature node ≈ Stage 2."""
    cfg_stage2 = GaOTTTConfig(
        query_kick_strength=1.0, query_kick_enabled=True,
        mass_anchor_threshold=0.0,
    )
    cfg_stage3 = GaOTTTConfig(
        query_kick_strength=1.0, query_kick_enabled=True,
        mass_anchor_threshold=3.0,
    )
    dim = cfg_stage3.embedding_dim
    pos = np.zeros(dim, dtype=np.float32)
    pos[0] = 1.0
    query = np.zeros(dim, dtype=np.float32)
    query[1] = 1.0
    disp = np.zeros(dim, dtype=np.float32)

    base_s2 = _baseline_acc(pos, disp, cfg_stage2)
    base_s3 = _baseline_acc(pos, disp, cfg_stage3)
    kick_s2 = _kicked_acc(pos, disp, cfg_stage2, mass=20.0, query=query, score=1.0) - base_s2
    kick_s3 = _kicked_acc(pos, disp, cfg_stage3, mass=20.0, query=query, score=1.0) - base_s3

    n2 = float(np.linalg.norm(kick_s2))
    n3 = float(np.linalg.norm(kick_s3))
    assert n2 > 0
    # tanh(20/3) ≈ 0.999994 — well above the threshold below
    assert n3 / n2 >= 0.9999


def test_stage3_threshold_zero_is_legacy_stage2():
    """θ=0 forces gate=1.0 → kick magnitude equals the bare F=ma formula α·s/m·|Δ|."""
    cfg = GaOTTTConfig(
        query_kick_strength=1.0, query_kick_enabled=True,
        mass_anchor_threshold=0.0,
    )
    dim = cfg.embedding_dim
    pos = np.zeros(dim, dtype=np.float32)
    pos[0] = 1.0
    query = np.zeros(dim, dtype=np.float32)
    query[1] = 1.0
    disp = np.zeros(dim, dtype=np.float32)
    score = 0.7

    base = _baseline_acc(pos, disp, cfg)
    for mass in [0.5, 1.0, 2.0, 5.0, 20.0, 50.0]:
        kick = _kicked_acc(pos, disp, cfg, mass=mass, query=query, score=score) - base
        expected = (cfg.query_kick_strength * score / mass) * float(np.linalg.norm(query - pos))
        actual = float(np.linalg.norm(kick))
        assert expected > 0
        assert abs(actual - expected) / expected < 1e-5, (
            f"mass={mass}: expected {expected}, got {actual}"
        )
