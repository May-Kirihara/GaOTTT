"""Unit tests for Phase Q2 — anchor-referenced neighbour-gravity governor.

The governor caps the *attractive* neighbour force (neighbour gravity + mass-BH)
per node to ``α × k_eff × max(|d|, d_floor)`` so a dense, coherent neighbourhood
cannot dominate the anchor. Direction is preserved; anchor / query / Λ are not
capped. Default OFF = legacy. See docs/wiki/Plans-Phase-Q2-Gravitational-Scale.md.
"""
from __future__ import annotations

import numpy as np

from gaottt.config import GaOTTTConfig
from gaottt.core.gravity import compute_acceleration


def _cfg(**ov) -> GaOTTTConfig:
    base = dict(
        embedding_dim=8, gravity_G=0.01, orbital_anchor_strength=0.02,
        mass_anchor_extra_strength=0.0, mass_anchor_threshold=3.0,
        mass_bh_enabled=False, query_kick_enabled=False,
        cosmological_lambda_enabled=False,
        gravity_neighbor_governor_alpha=0.2,
        gravity_neighbor_governor_disp_floor=0.1,
    )
    base.update(ov)
    return GaOTTTConfig(**base)


def _dense(dim=8):
    """A coherent dense cluster: 20 heavy neighbours all pulling ~+x."""
    pos_i = np.zeros(dim, dtype=np.float32)
    disp_i = np.zeros(dim, dtype=np.float32)
    disp_i[0] = 0.3                       # anchor force = k_eff · 0.3
    neighbors = []
    for j in range(20):
        p = np.zeros(dim, dtype=np.float32)
        p[0] = 0.5 + 0.01 * j
        p[1] = 0.02 * j
        neighbors.append((p, 5.0))
    return pos_i, disp_i, neighbors


def _attractive(acc, cfg, disp_i, anchor_factor=1.0):
    """Remove the anchor term to isolate neighbour gravity + mass-BH."""
    return acc + cfg.orbital_anchor_strength * anchor_factor * disp_i


def _ref(cfg, disp_i, anchor_factor=1.0):
    k_eff = cfg.orbital_anchor_strength * anchor_factor
    return cfg.gravity_neighbor_governor_alpha * k_eff * max(
        float(np.linalg.norm(disp_i)), cfg.gravity_neighbor_governor_disp_floor
    )


def test_governor_off_leaves_dense_pull_uncapped():
    cfg = _cfg(gravity_neighbor_governor_enabled=False)
    pos_i, disp_i, neigh = _dense()
    acc = compute_acceleration(pos_i, pos_i, disp_i, neigh, cfg, mass_i=1.0)
    attr = float(np.linalg.norm(_attractive(acc, cfg, disp_i)))
    # the coherent dense pull is orders of magnitude above the governor ref
    assert attr > 50 * _ref(cfg, disp_i)


def test_governor_on_caps_dense_pull_to_alpha_anchor():
    cfg = _cfg(gravity_neighbor_governor_enabled=True)
    pos_i, disp_i, neigh = _dense()
    acc = compute_acceleration(pos_i, pos_i, disp_i, neigh, cfg, mass_i=1.0)
    attr = float(np.linalg.norm(_attractive(acc, cfg, disp_i)))
    ref = _ref(cfg, disp_i)
    assert attr <= ref + 1e-6, f"attractive {attr} exceeds cap {ref}"
    # and it is actually near the cap (the cap is load-bearing on a dense cluster)
    assert attr > 0.5 * ref


def test_governor_preserves_direction():
    pos_i, disp_i, neigh = _dense()
    on = compute_acceleration(pos_i, pos_i, disp_i, neigh, _cfg(gravity_neighbor_governor_enabled=True), mass_i=1.0)
    off = compute_acceleration(pos_i, pos_i, disp_i, neigh, _cfg(gravity_neighbor_governor_enabled=False), mass_i=1.0)
    a_on = _attractive(on, _cfg(), disp_i)
    a_off = _attractive(off, _cfg(), disp_i)
    cos = float(np.dot(a_on, a_off) / (np.linalg.norm(a_on) * np.linalg.norm(a_off)))
    assert cos > 0.999  # governor scales magnitude, never rotates


def test_governor_leaves_sparse_pull_unchanged():
    """A single distant light neighbour produces |acc_neigh| < ref → g=1 →
    governor on is identical to off."""
    cfg_on = _cfg(gravity_neighbor_governor_enabled=True)
    cfg_off = _cfg(gravity_neighbor_governor_enabled=False)
    dim = 8
    pos_i = np.zeros(dim, dtype=np.float32)
    disp_i = np.zeros(dim, dtype=np.float32)
    disp_i[0] = 0.3
    far = np.zeros(dim, dtype=np.float32)
    far[0] = 2.0
    neigh = [(far, 0.1)]   # per-pair ~ 0.01*0.1/4 = 2.5e-4 < ref 1.2e-3
    on = compute_acceleration(pos_i, pos_i, disp_i, neigh, cfg_on, mass_i=1.0)
    off = compute_acceleration(pos_i, pos_i, disp_i, neigh, cfg_off, mass_i=1.0)
    assert np.allclose(on, off, atol=1e-9)


def test_governor_caps_include_mass_bh():
    """The cap covers the mass-BH term too (it is part of the attractive pull)."""
    cfg = _cfg(gravity_neighbor_governor_enabled=True, mass_bh_enabled=True,
               mass_bh_theta=3.0, mass_bh_sigma=1.5)
    pos_i, disp_i, neigh = _dense()
    neigh = [(p, 20.0) for p, _ in neigh]   # heavy → mass-BH active
    acc = compute_acceleration(pos_i, pos_i, disp_i, neigh, cfg, mass_i=1.0)
    attr = float(np.linalg.norm(_attractive(acc, cfg, disp_i)))
    assert attr <= _ref(cfg, disp_i) + 1e-6


def test_governor_default_is_off():
    c = GaOTTTConfig(embedding_dim=8)
    assert c.gravity_neighbor_governor_enabled is False
    assert c.gravity_neighbor_governor_alpha == 0.2
    assert c.gravity_neighbor_governor_disp_floor == 0.1
