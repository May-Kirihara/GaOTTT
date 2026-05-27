"""Phase P Stage 1 — Langevin Temperature (P-β) unit tests.

Pin the literal behavior of the SGLD-shaped Brownian kick on the
position-update step. Force computation (acceleration, mass update) is
NOT touched by Stage 1; the only physics change is one term added to
``new_disp`` AFTER the deterministic velocity step.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from gaottt.config import GaOTTTConfig
from gaottt.core.gravity import update_orbital_state


# ----- helpers --------------------------------------------------------------

def _make_state(dim: int = 16, n: int = 4):
    """Build a minimal node fixture: 4 nodes at unit-norm random positions,
    zero velocity, mass 1.0, last_access at t=0."""
    rng = np.random.default_rng(seed=1)
    ids = [f"n{i}" for i in range(n)]
    embeddings = {}
    for nid in ids:
        v = rng.standard_normal(dim).astype(np.float32)
        v /= np.linalg.norm(v) + 1e-9
        embeddings[nid] = v
    displacements = {nid: np.zeros(dim, dtype=np.float32) for nid in ids}
    velocities = {nid: np.zeros(dim, dtype=np.float32) for nid in ids}
    masses = {nid: 1.0 for nid in ids}
    last_accesses = {nid: 0.0 for nid in ids}
    return ids, embeddings, displacements, velocities, masses, last_accesses


def _cfg(**overrides) -> GaOTTTConfig:
    base = dict(
        embedding_dim=16,
        # tame other physics so the test isolates the noise term
        gravity_G=0.0,
        orbital_anchor_strength=0.0,
        orbital_friction=0.0,
        query_kick_enabled=False,
        mass_bh_enabled=False,
        mass_conservation_enabled=False,
    )
    base.update(overrides)
    return GaOTTTConfig(**base)


# ----- core behavior --------------------------------------------------------

def test_langevin_disabled_is_bit_exact_legacy() -> None:
    """When the flag is off, displacement equals the pre-Phase-P legacy path
    (no noise added). Stage 1 must be a true no-op under default config."""
    ids, embs, disps, vels, masses, las = _make_state()
    cfg = _cfg(langevin_temperature_enabled=False)

    # Run twice with no shared RNG — bit-exact equal because the noise
    # branch is gated.
    d1, v1 = update_orbital_state(ids, embs, disps, vels, masses, las, 1.0, cfg)
    d2, v2 = update_orbital_state(ids, embs, disps, vels, masses, las, 1.0, cfg)
    for nid in ids:
        assert np.array_equal(d1[nid], d2[nid])
        assert np.array_equal(v1[nid], v2[nid])


def test_langevin_t0_zero_is_bit_exact_legacy() -> None:
    """T₀ = 0 should also be a no-op even with the flag on (sigma=0)."""
    ids, embs, disps, vels, masses, las = _make_state()
    cfg_off = _cfg(langevin_temperature_enabled=False)
    cfg_on_zero_t = _cfg(
        langevin_temperature_enabled=True, langevin_temperature_t0=0.0,
    )
    d_off, _ = update_orbital_state(ids, embs, disps, vels, masses, las, 1.0, cfg_off)
    d_on, _ = update_orbital_state(ids, embs, disps, vels, masses, las, 1.0, cfg_on_zero_t)
    for nid in ids:
        assert np.array_equal(d_off[nid], d_on[nid])


def test_langevin_enabled_adds_noise_with_expected_scale() -> None:
    """With T₀=0.001 and seeded RNG, σ should be √(2·T₀) and the per-node
    L2 of the noise step should match that scale (within tolerance for a
    16-dim Gaussian: E[||ξ||₂²] = dim → E[||ξ||₂] ≈ √dim)."""
    ids, embs, disps, vels, masses, las = _make_state()
    cfg = _cfg(
        langevin_temperature_enabled=True,
        langevin_temperature_t0=0.001,
    )

    rng = np.random.default_rng(seed=42)
    d_noisy, _ = update_orbital_state(
        ids, embs, disps, vels, masses, las, 1.0, cfg, rng=rng,
    )

    # The deterministic path (no flag, no RNG used) produces no displacement.
    cfg_off = _cfg(langevin_temperature_enabled=False)
    d_clean, _ = update_orbital_state(
        ids, embs, disps, vels, masses, las, 1.0, cfg_off,
    )

    expected_sigma = math.sqrt(2.0 * 0.001)  # ≈ 0.0447
    expected_norm = expected_sigma * math.sqrt(16)  # ≈ 0.179
    for nid in ids:
        delta = d_noisy[nid] - d_clean[nid]
        actual_norm = float(np.linalg.norm(delta))
        # Concentration of measure for χ-dim 16 — be generous on bounds.
        assert 0.05 < actual_norm < 0.40, (
            f"node {nid}: |Δ|={actual_norm:.3f} not within expected σ band "
            f"(target ~{expected_norm:.3f})"
        )


def test_langevin_seeded_rng_is_reproducible() -> None:
    """Two calls with the same seed yield bit-exact noise (D6 contract)."""
    ids, embs, disps, vels, masses, las = _make_state()
    cfg = _cfg(
        langevin_temperature_enabled=True, langevin_temperature_t0=0.001,
    )
    rng1 = np.random.default_rng(seed=123)
    rng2 = np.random.default_rng(seed=123)
    d1, _ = update_orbital_state(ids, embs, disps, vels, masses, las, 1.0, cfg, rng=rng1)
    d2, _ = update_orbital_state(ids, embs, disps, vels, masses, las, 1.0, cfg, rng=rng2)
    for nid in ids:
        assert np.array_equal(d1[nid], d2[nid])


def test_langevin_different_seeds_diverge() -> None:
    """Different seeds → different displacement (noise is actually random)."""
    ids, embs, disps, vels, masses, las = _make_state()
    cfg = _cfg(
        langevin_temperature_enabled=True, langevin_temperature_t0=0.001,
    )
    d1, _ = update_orbital_state(
        ids, embs, disps, vels, masses, las, 1.0, cfg,
        rng=np.random.default_rng(seed=1),
    )
    d2, _ = update_orbital_state(
        ids, embs, disps, vels, masses, las, 1.0, cfg,
        rng=np.random.default_rng(seed=2),
    )
    diverged = any(not np.array_equal(d1[nid], d2[nid]) for nid in ids)
    assert diverged, "different seeds should produce different noise"


def test_langevin_respects_displacement_clamp() -> None:
    """Even with huge T₀, ||new_disp|| stays within max_displacement_norm."""
    ids, embs, disps, vels, masses, las = _make_state()
    cfg = _cfg(
        langevin_temperature_enabled=True,
        langevin_temperature_t0=10.0,            # comically hot
        max_displacement_norm=0.5,              # tight clamp
    )
    d_hot, _ = update_orbital_state(
        ids, embs, disps, vels, masses, las, 1.0, cfg,
        rng=np.random.default_rng(seed=99),
    )
    for nid in ids:
        assert float(np.linalg.norm(d_hot[nid])) <= 0.5 + 1e-6


@pytest.mark.parametrize("seed", [7, 11, 13])
def test_langevin_velocity_is_unchanged(seed: int) -> None:
    """Stage 1 only touches POSITION update — velocity must be identical
    between off and on (the deterministic accel + velocity step is unchanged
    when the rest of the physics is held fixed)."""
    ids, embs, disps, vels, masses, las = _make_state()
    cfg_off = _cfg(langevin_temperature_enabled=False)
    cfg_on = _cfg(
        langevin_temperature_enabled=True, langevin_temperature_t0=0.001,
    )
    _, v_off = update_orbital_state(ids, embs, disps, vels, masses, las, 1.0, cfg_off)
    _, v_on = update_orbital_state(
        ids, embs, disps, vels, masses, las, 1.0, cfg_on,
        rng=np.random.default_rng(seed=seed),
    )
    for nid in ids:
        assert np.array_equal(v_off[nid], v_on[nid]), (
            f"velocity drifted for node {nid} — Langevin should only touch position"
        )
