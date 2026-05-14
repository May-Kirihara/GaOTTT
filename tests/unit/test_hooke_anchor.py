"""Phase I Stage 4 — Mass-dependent Hooke (unit tests).

The Hooke restoring force in ``compute_acceleration``'s 2nd component now
takes an optional mass amplification:

    k_eff(m) = k · (1 + β · (1 - tanh(m / θ)))

where ``β = config.mass_anchor_extra_strength`` (default 0.0 — legacy) and
``θ = config.mass_anchor_threshold`` (shared with Stage 3).

These tests pin the behaviour expected of the dual to Stage 3:
  1. β=0 ⇒ Stage 1-3 legacy (constant-k Hooke), bit-for-bit
  2. β>0, low mass ⇒ effective k is multiplied by (1 + β·(1-tanh(m/θ))) > 1
  3. β>0, high mass ⇒ factor → 1 (mature node unchanged)
  4. mass_i=None ⇒ legacy path (no mass to gate against)
  5. θ=0 with β>0 ⇒ falls back to θ_eff=1 (factor still well-defined,
     low-mass amplification continues to work without divide-by-zero)
"""
from __future__ import annotations

import math

import numpy as np

from gaottt.config import GaOTTTConfig
from gaottt.core.gravity import compute_acceleration


def _hooke_only_acc(mass, *, beta, theta=3.0, disp_axis_value=0.1):
    """Acceleration with only the Hooke term active (no neighbors, no kick).

    The kick path needs query_anchor/query_score — by leaving them None
    we isolate component 2 of compute_acceleration. neighbors=[] zeroes
    component 1 + 3 too.
    """
    config = GaOTTTConfig(
        # Stage 4
        mass_anchor_extra_strength=beta,
        mass_anchor_threshold=theta,
        # Disable Stage 2/3 kick entirely so we only see Hooke
        query_kick_strength=0.0,
        query_kick_enabled=False,
        # Disable mass-BH so no neighbors-zero path produces it anyway
        mass_bh_enabled=False,
    )
    dim = config.embedding_dim
    pos = np.zeros(dim, dtype=np.float32)
    pos[0] = 1.0
    disp = np.zeros(dim, dtype=np.float32)
    disp[1] = disp_axis_value  # non-zero so Hooke contributes
    return compute_acceleration(
        pos_i=pos,
        original_pos_i=pos,
        displacement_i=disp,
        neighbors=[],
        config=config,
        mass_i=mass,
    ), config, disp


def test_stage4_beta_zero_is_legacy_constant_k():
    """β=0 ⇒ acceleration equals the legacy -k * displacement, regardless of mass."""
    masses = [0.5, 1.0, 3.0, 10.0, 50.0]
    accs = []
    config_ref = None
    disp_ref = None
    for m in masses:
        acc, config, disp = _hooke_only_acc(m, beta=0.0)
        if config_ref is None:
            config_ref = config
            disp_ref = disp
        accs.append(acc)
    expected = -config_ref.orbital_anchor_strength * disp_ref
    for m, a in zip(masses, accs):
        assert np.allclose(a, expected, atol=1e-7), f"mass={m} drifted from legacy"


def test_stage4_low_mass_amplifies_restoring_force():
    """β=1, mass=1, θ=3 ⇒ k_eff = k · (1 + tanh(2/3))·... no — re-derive:
    1 + β·(1 - tanh(m/θ)) = 1 + 1·(1 - tanh(1/3)) ≈ 1 + (1 - 0.3215) ≈ 1.6785.
    """
    acc_off, config, disp = _hooke_only_acc(1.0, beta=0.0)
    acc_on, _, _ = _hooke_only_acc(1.0, beta=1.0)

    expected_factor = 1.0 + (1.0 - math.tanh(1.0 / 3.0))
    legacy = -config.orbital_anchor_strength * disp
    stage4 = legacy * expected_factor

    assert np.allclose(acc_off, legacy, atol=1e-7)
    assert np.allclose(acc_on, stage4, atol=1e-7)


def test_stage4_high_mass_recovers_legacy():
    """mass=50 with β=1, θ=3 ⇒ tanh(50/3) ≈ 1 ⇒ factor ≈ 1 + 0 ≈ 1."""
    acc_off, config, disp = _hooke_only_acc(50.0, beta=0.0)
    acc_on, _, _ = _hooke_only_acc(50.0, beta=1.0)

    # Mature: factor is within 1e-6 of 1.0 (1 - tanh(50/3) ≈ 4e-15)
    assert np.allclose(acc_off, acc_on, atol=1e-6)


def test_stage4_monotone_decreasing_in_mass():
    """Anchor factor must be monotonically non-increasing in mass."""
    beta = 1.0
    masses = [0.1, 0.5, 1.0, 2.0, 3.0, 5.0, 10.0, 30.0, 50.0]
    norms = []
    for m in masses:
        acc, _, _ = _hooke_only_acc(m, beta=beta)
        norms.append(float(np.linalg.norm(acc)))
    for i in range(1, len(norms)):
        assert norms[i] <= norms[i - 1] + 1e-7, (
            f"non-monotone: mass={masses[i-1]} → {norms[i-1]}, mass={masses[i]} → {norms[i]}"
        )


def test_stage4_no_mass_is_legacy():
    """Callers that don't supply mass_i must get the legacy constant-k path even with β>0."""
    config = GaOTTTConfig(
        mass_anchor_extra_strength=1.0,
        mass_anchor_threshold=3.0,
        query_kick_strength=0.0,
        query_kick_enabled=False,
        mass_bh_enabled=False,
    )
    dim = config.embedding_dim
    pos = np.zeros(dim, dtype=np.float32)
    pos[0] = 1.0
    disp = np.zeros(dim, dtype=np.float32)
    disp[1] = 0.1
    acc = compute_acceleration(
        pos_i=pos, original_pos_i=pos, displacement_i=disp,
        neighbors=[], config=config,
        mass_i=None,
    )
    expected = -config.orbital_anchor_strength * disp
    assert np.allclose(acc, expected, atol=1e-7)


def test_stage4_theta_zero_uses_safe_fallback():
    """θ=0 with β>0 falls back to θ_eff=1 (no divide-by-zero). The factor at
    mass=1, θ_eff=1, β=1 is 1 + (1 - tanh(1)) ≈ 1.238 — strictly between
    legacy (1.0) and the θ=3 case (1.68).
    """
    config_on = GaOTTTConfig(
        mass_anchor_extra_strength=1.0,
        mass_anchor_threshold=0.0,  # explicit θ=0 — Stage 3 rollback
        query_kick_strength=0.0,
        query_kick_enabled=False,
        mass_bh_enabled=False,
    )
    config_off = GaOTTTConfig(
        mass_anchor_extra_strength=0.0,
        mass_anchor_threshold=0.0,
        query_kick_strength=0.0,
        query_kick_enabled=False,
        mass_bh_enabled=False,
    )
    dim = config_on.embedding_dim
    pos = np.zeros(dim, dtype=np.float32)
    pos[0] = 1.0
    disp = np.zeros(dim, dtype=np.float32)
    disp[1] = 0.1

    acc_on = compute_acceleration(
        pos_i=pos, original_pos_i=pos, displacement_i=disp,
        neighbors=[], config=config_on, mass_i=1.0,
    )
    acc_off = compute_acceleration(
        pos_i=pos, original_pos_i=pos, displacement_i=disp,
        neighbors=[], config=config_off, mass_i=1.0,
    )
    legacy_norm = float(np.linalg.norm(acc_off))
    on_norm = float(np.linalg.norm(acc_on))
    expected_factor = 1.0 + (1.0 - math.tanh(1.0))  # θ_eff=1 fallback
    assert legacy_norm > 0
    assert abs(on_norm / legacy_norm - expected_factor) < 1e-5


def test_stage4_symmetric_pair_with_stage3():
    """Sanity: at the gate point (mass=θ), Stage 3 kick scales by tanh(1)≈0.76
    and Stage 4 Hooke scales by 1 + β·(1 - tanh(1))≈1 + 0.24β. The two halves
    track the same underlying gate; this test pins that shared dependence.
    """
    theta = 3.0
    config = GaOTTTConfig(
        query_kick_strength=1.0, query_kick_enabled=True,
        mass_anchor_threshold=theta,
        mass_anchor_extra_strength=1.0,
        mass_bh_enabled=False,
    )
    dim = config.embedding_dim
    pos = np.zeros(dim, dtype=np.float32)
    pos[0] = 1.0
    query = np.zeros(dim, dtype=np.float32)
    query[1] = 1.0
    disp = np.zeros(dim, dtype=np.float32)
    disp[2] = 0.1  # orthogonal to query so the two terms add linearly

    acc = compute_acceleration(
        pos_i=pos, original_pos_i=pos, displacement_i=disp,
        neighbors=[], config=config,
        mass_i=theta, query_anchor=query, query_score=1.0,
    )

    # Extract Hooke component along disp axis (axis 2)
    hooke_axis = float(acc[2])
    expected_factor_hooke = 1.0 + (1.0 - math.tanh(theta / theta))  # mass=θ
    expected_hooke = -config.orbital_anchor_strength * expected_factor_hooke * 0.1
    assert abs(hooke_axis - expected_hooke) < 1e-6

    # Extract kick component along query axis (axis 1)
    kick_axis = float(acc[1])
    gate_kick = math.tanh(theta / theta)  # = tanh(1) ≈ 0.7616
    diff_axis = float(query[1] - pos[1])  # = 1.0
    expected_kick = (config.query_kick_strength * 1.0 * gate_kick / theta) * diff_axis
    assert abs(kick_axis - expected_kick) < 1e-6
