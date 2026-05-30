"""Unit tests for Phase Q — Orbital Mechanics (rosette orbits around own anchor).

Covers the three Stage 1 pieces:
  1. ``_perpendicular_unit`` — deterministic orthogonal basis for tangential seed
  2. ``compute_gravity_kick`` tangential seeding — α=0 bit-exact legacy (L=0,
     displacement ∥ velocity); α>0 produces non-collinear (d, v) → L ≠ 0
  3. velocity-Verlet integration — a seeded harmonic oscillator traces a closed
     ellipse (|d| stays bounded away from 0), with angular momentum conserved
     much better than the straight-line (radial-only) case collapses to 0.

See docs/wiki/Plans-Phase-Q-Orbital-Mechanics.md.
"""

from __future__ import annotations

import math

import numpy as np

from gaottt.config import GaOTTTConfig
from gaottt.core.gravity import (
    _perpendicular_unit,
    compute_gravity_kick,
    update_orbital_state,
)


def _config(**overrides) -> GaOTTTConfig:
    base = dict(
        gravity_G=0.01,
        gravity_eta=0.005,
        orbital_max_velocity=0.05,
        max_displacement_norm=1e6,
        embedding_dim=8,
        orbital_anchor_strength=0.02,
    )
    base.update(overrides)
    return GaOTTTConfig(**base)


# ---------------------------------------------------------------------------
# 1. _perpendicular_unit
# ---------------------------------------------------------------------------

def test_perpendicular_unit_is_orthogonal_and_unit():
    rng = np.random.default_rng(0)
    for _ in range(20):
        g = rng.standard_normal(8).astype(np.float32)
        t = _perpendicular_unit(g)
        assert abs(float(np.dot(t, g))) < 1e-5      # orthogonal
        assert abs(float(np.linalg.norm(t)) - 1.0) < 1e-5  # unit


def test_perpendicular_unit_is_deterministic():
    g = np.array([0.3, -0.7, 0.1, 0.0, 0.5, -0.2, 0.9, 0.4], dtype=np.float32)
    a = _perpendicular_unit(g)
    b = _perpendicular_unit(g)
    assert np.array_equal(a, b)  # no RNG — reproducible


def test_perpendicular_unit_zero_vector_returns_zero():
    g = np.zeros(8, dtype=np.float32)
    t = _perpendicular_unit(g)
    assert float(np.linalg.norm(t)) == 0.0


# ---------------------------------------------------------------------------
# 2. compute_gravity_kick tangential seeding
# ---------------------------------------------------------------------------

def _kick_setup():
    # New node at origin-ish; a single heavy neighbor pulls it along +x.
    new_pos = np.zeros(8, dtype=np.float32)
    neighbor = np.zeros(8, dtype=np.float32)
    neighbor[0] = 0.5
    neighbors = [(neighbor, 5.0)]
    return new_pos, neighbors


def test_kick_alpha_zero_is_legacy_collinear():
    """α=0: displacement ∥ velocity (the legacy genesis behaviour) → L=0."""
    new_pos, neighbors = _kick_setup()
    cfg = _config(orbital_tangential_alpha=0.0)
    disp, vel, _boost = compute_gravity_kick(new_pos, neighbors, cfg)
    # displacement == velocity (clamped the same) → exactly parallel
    assert np.allclose(disp, vel, atol=1e-7)
    # cross-term (component of vel orthogonal to disp) is ~0
    d_hat = disp / (np.linalg.norm(disp) + 1e-12)
    perp = vel - float(np.dot(vel, d_hat)) * d_hat
    assert float(np.linalg.norm(perp)) < 1e-6


def test_kick_alpha_positive_gives_non_collinear_dv():
    """α>0: velocity gains a tangential component → (d, v) non-collinear → L≠0."""
    new_pos, neighbors = _kick_setup()
    cfg = _config(orbital_tangential_alpha=1.0)
    disp, vel, _boost = compute_gravity_kick(new_pos, neighbors, cfg)
    # displacement is still purely radial (∥ +x)
    assert disp[0] > 0
    d_hat = disp / (np.linalg.norm(disp) + 1e-12)
    perp = vel - float(np.dot(vel, d_hat)) * d_hat
    # the orthogonal (tangential) part of the velocity is now substantial
    assert float(np.linalg.norm(perp)) > 0.3 * float(np.linalg.norm(vel))


# ---------------------------------------------------------------------------
# 3. velocity-Verlet — closed ellipse vs line oscillation
# ---------------------------------------------------------------------------

def _harmonic_config(integrator: str) -> GaOTTTConfig:
    # Isolate the Hooke anchor as the sole central force:
    #   gravity_G=0  → no neighbor / mass-BH gravity
    #   friction=0   → conservative (test angular-momentum conservation)
    #   no clamps    → free orbit
    return _config(
        gravity_G=0.0,
        orbital_friction=0.0,
        orbital_friction_age_factor=0.0,
        orbital_max_velocity=1e6,
        max_displacement_norm=1e6,
        orbital_anchor_strength=0.02,
        orbital_integrator=integrator,
        query_kick_enabled=False,
        mass_bh_enabled=False,
    )


def _run_orbit(cfg, d0, v0, steps):
    dim = cfg.embedding_dim
    # Two nodes so update_orbital_state's len>=2 guard passes; node B sits far
    # away and with gravity_G=0 exerts no force, so node A is a pure harmonic
    # oscillator about its own anchor.
    embA = np.zeros(dim, dtype=np.float32)
    embB = np.full(dim, 10.0, dtype=np.float32)
    original = {"A": embA, "B": embB}
    disps = {"A": d0.astype(np.float32), "B": np.zeros(dim, dtype=np.float32)}
    vels = {"A": v0.astype(np.float32), "B": np.zeros(dim, dtype=np.float32)}
    masses = {"A": 1.0, "B": 1.0}
    last = {"A": 0.0, "B": 0.0}

    traj_d = []
    traj_v = []
    for _ in range(steps):
        disps, vels = update_orbital_state(
            ["A", "B"], original, disps, vels, masses, last, now=0.0, config=cfg,
        )
        traj_d.append(disps["A"].copy())
        traj_v.append(vels["A"].copy())
    return np.array(traj_d), np.array(traj_v)


def test_verlet_tangential_seed_traces_closed_ellipse():
    """Off-axis tangential start → |d| oscillates between r_min>0 and r_max
    (an ellipse around the anchor), never collapsing through the origin."""
    cfg = _harmonic_config("verlet")
    omega = math.sqrt(cfg.orbital_anchor_strength)
    r = 0.4
    vt = 0.3 * omega   # tangential speed → semi-minor = vt/omega = 0.3
    d0 = np.zeros(8, dtype=np.float32)
    d0[0] = r
    v0 = np.zeros(8, dtype=np.float32)
    v0[1] = vt   # perpendicular to d0
    period = 2 * math.pi / omega
    steps = int(period * 1.2)

    traj_d, _ = _run_orbit(cfg, d0, v0, steps)
    norms = np.linalg.norm(traj_d, axis=1)
    # ellipse: min radius stays well above 0 (semi-minor ≈ 0.3)
    assert norms.min() > 0.15
    # bounded: max radius stays near the semi-major (≈ 0.4)
    assert norms.max() < 0.6


def test_verlet_radial_seed_is_line_through_origin():
    """Purely radial start (L=0) → straight-line oscillation that passes
    through the anchor → min |d| ≈ 0. This is the degenerate case Phase Q
    avoids by seeding tangential velocity."""
    cfg = _harmonic_config("verlet")
    omega = math.sqrt(cfg.orbital_anchor_strength)
    d0 = np.zeros(8, dtype=np.float32)
    d0[0] = 0.4
    v0 = np.zeros(8, dtype=np.float32)  # start from rest → pure line
    period = 2 * math.pi / omega
    traj_d, _ = _run_orbit(cfg, d0, v0, int(period * 1.2))
    norms = np.linalg.norm(traj_d, axis=1)
    assert norms.min() < 0.05  # passes (nearly) through the origin


def test_verlet_conserves_energy_over_multiple_periods():
    """velocity-Verlet is a valid symplectic integrator for the harmonic well:
    the measured energy E = ½|v|² + ½k|d|² stays tightly bounded over several
    orbits (no secular drift). This is the conservation property that makes a
    seeded orbit a *persistent* ellipse rather than a decaying spiral.

    (Note: for an isotropic harmonic central force, semi-implicit Euler already
    conserves angular momentum to machine precision — L is *not* what
    distinguishes the integrators, so we assert the energy bound instead.)
    """
    k = 0.02
    omega = math.sqrt(k)
    r = 0.4
    vt = 0.3 * omega
    d0 = np.zeros(8, dtype=np.float32)
    d0[0] = r
    v0 = np.zeros(8, dtype=np.float32)
    v0[1] = vt
    period = 2 * math.pi / omega
    steps = int(period * 3)

    cfg = _harmonic_config("verlet")
    td, tv = _run_orbit(cfg, d0, v0, steps)
    energy = 0.5 * np.sum(tv ** 2, axis=1) + 0.5 * k * np.sum(td ** 2, axis=1)
    rel_spread = float(np.std(energy) / (abs(np.mean(energy)) + 1e-12))
    # Energy stays bounded with no secular drift (a decaying spiral or an
    # unstable integrator would blow this past O(1)). Loose bound: the point
    # is "bounded, conservative" not a precise figure.
    assert rel_spread < 0.05
    assert energy.max() / energy.min() < 1.1   # no runaway / no collapse

    # angular momentum is conserved (sanity: the seeded orbit really is planar
    # and rotating, not collapsing) — both integrators do this well.
    lz = td[:, 0] * tv[:, 1] - td[:, 1] * tv[:, 0]
    assert float(np.std(lz) / (abs(np.mean(lz)) + 1e-9)) < 0.02


def test_orbital_integrator_default_is_euler():
    assert GaOTTTConfig(embedding_dim=8).orbital_integrator == "euler"
    assert GaOTTTConfig(embedding_dim=8).orbital_tangential_alpha == 0.0
