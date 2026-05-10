"""Phase I Stage 2 — Implicit query-aware displacement kick (unit tests).

`compute_acceleration` gains a 4th component:
    F_query = α · score · (q - pos);  a_query = F_query / m

These tests pin down the four properties that make the kick safe and
TTT-consistent:
  1. Direction: kick points from pos toward query_anchor.
  2. Score weighting: doubling the score doubles the kick magnitude.
  3. Mass damping: doubling the mass halves the kick magnitude (F=ma).
  4. Off-switches: kick is suppressed when α=0, when query_kick_enabled is
     False, or when any of mass_i / query_anchor / query_score is missing.
"""
from __future__ import annotations

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
    """Doubling mass halves the per-step acceleration (a = F/m)."""
    config = GaOTTTConfig(query_kick_strength=1.0, query_kick_enabled=True)
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
