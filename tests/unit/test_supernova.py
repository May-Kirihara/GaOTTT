"""Phase K Stage 1 — Stellar supernova cohort (unit tests).

The cohort math:
  - N≥min_size → N×(N-1)/2 edges
  - Outward velocity = α × (embedding - centroid), clamped
  - Below min_size or with α≤0 → no-op
  - With enabled=False → no-op
"""
from __future__ import annotations

import numpy as np

from gaottt.config import GaOTTTConfig
from gaottt.core.supernova import (
    compute_supernova_velocities,
    form_supernova_edges,
)


# ---------------------------------------------------------------------------
# form_supernova_edges
# ---------------------------------------------------------------------------

def test_edges_form_all_pairs_for_n4():
    config = GaOTTTConfig(supernova_enabled=True, supernova_min_cohort_size=2,
                          supernova_initial_weight=1.0)
    ids = ["a", "b", "c", "d"]
    edges = form_supernova_edges(ids, config)
    # 4 choose 2 = 6 pairs
    assert len(edges) == 6
    pairs = {(src, dst) for src, dst, _ in edges}
    expected = {("a", "b"), ("a", "c"), ("a", "d"),
                ("b", "c"), ("b", "d"), ("c", "d")}
    assert pairs == expected


def test_edges_use_initial_weight():
    config = GaOTTTConfig(supernova_enabled=True, supernova_min_cohort_size=2,
                          supernova_initial_weight=2.5)
    edges = form_supernova_edges(["a", "b", "c"], config)
    assert all(weight == 2.5 for _, _, weight in edges)


def test_edges_skipped_below_min_cohort_size():
    config = GaOTTTConfig(supernova_enabled=True, supernova_min_cohort_size=3,
                          supernova_initial_weight=1.0)
    # Only 2 ids — below min_size=3
    assert form_supernova_edges(["a", "b"], config) == []
    # 1 id — also below
    assert form_supernova_edges(["a"], config) == []


def test_edges_disabled_when_enabled_false():
    config = GaOTTTConfig(supernova_enabled=False, supernova_min_cohort_size=2,
                          supernova_initial_weight=1.0)
    assert form_supernova_edges(["a", "b", "c"], config) == []


def test_edges_disabled_when_weight_zero():
    config = GaOTTTConfig(supernova_enabled=True, supernova_min_cohort_size=2,
                          supernova_initial_weight=0.0)
    assert form_supernova_edges(["a", "b", "c"], config) == []


# ---------------------------------------------------------------------------
# compute_supernova_velocities
# ---------------------------------------------------------------------------

def test_velocity_points_outward_from_centroid_n2():
    """For a 2-node cohort, each node's velocity points away from the other."""
    config = GaOTTTConfig(
        supernova_enabled=True, supernova_min_cohort_size=2,
        supernova_velocity_alpha=0.03, orbital_max_velocity=0.05,
    )
    e1 = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    e2 = np.array([0.0, 1.0, 0.0], dtype=np.float32)
    embs = np.stack([e1, e2])
    velocities = compute_supernova_velocities(["a", "b"], embs, config)

    # Reciprocal directions
    va = velocities["a"]
    vb = velocities["b"]
    # va should point away from e2 (toward e1 from centroid); reciprocally for vb
    centroid = (e1 + e2) / 2
    expected_a_dir = e1 - centroid
    expected_b_dir = e2 - centroid
    cos_a = float(np.dot(va, expected_a_dir)) / (
        float(np.linalg.norm(va)) * float(np.linalg.norm(expected_a_dir)) + 1e-12
    )
    cos_b = float(np.dot(vb, expected_b_dir)) / (
        float(np.linalg.norm(vb)) * float(np.linalg.norm(expected_b_dir)) + 1e-12
    )
    assert cos_a > 0.99
    assert cos_b > 0.99


def test_velocity_clamped_to_max():
    """Even with a huge α, velocity norm cannot exceed orbital_max_velocity."""
    config = GaOTTTConfig(
        supernova_enabled=True, supernova_min_cohort_size=2,
        supernova_velocity_alpha=10.0,  # absurdly large
        orbital_max_velocity=0.05,
    )
    e1 = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    e2 = np.array([-1.0, 0.0, 0.0], dtype=np.float32)
    embs = np.stack([e1, e2])
    velocities = compute_supernova_velocities(["a", "b"], embs, config)
    for v in velocities.values():
        assert float(np.linalg.norm(v)) <= 0.05 + 1e-6


def test_velocity_zero_when_below_min_cohort_size():
    config = GaOTTTConfig(supernova_enabled=True, supernova_min_cohort_size=3,
                          supernova_velocity_alpha=0.03)
    embs = np.array([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32)
    assert compute_supernova_velocities(["a", "b"], embs, config) == {}


def test_velocity_zero_when_disabled():
    config = GaOTTTConfig(supernova_enabled=False, supernova_min_cohort_size=2,
                          supernova_velocity_alpha=0.03)
    embs = np.array([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32)
    assert compute_supernova_velocities(["a", "b"], embs, config) == {}


def test_velocity_zero_when_alpha_zero():
    config = GaOTTTConfig(supernova_enabled=True, supernova_min_cohort_size=2,
                          supernova_velocity_alpha=0.0)
    embs = np.array([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32)
    assert compute_supernova_velocities(["a", "b"], embs, config) == {}


def test_velocity_radial_for_n4_cohort():
    """Each node in a 4-node cohort gets a velocity along (emb - centroid)."""
    config = GaOTTTConfig(
        supernova_enabled=True, supernova_min_cohort_size=2,
        supernova_velocity_alpha=0.03, orbital_max_velocity=1.0,  # avoid clamp
    )
    embs = np.array([
        [2.0, 0.0],
        [0.0, 2.0],
        [-2.0, 0.0],
        [0.0, -2.0],
    ], dtype=np.float32)
    ids = ["n", "e", "s", "w"]
    velocities = compute_supernova_velocities(ids, embs, config)

    centroid = embs.mean(axis=0)  # roughly origin
    for i, nid in enumerate(ids):
        expected_dir = embs[i] - centroid
        v = velocities[nid]
        cos = float(np.dot(v, expected_dir)) / (
            float(np.linalg.norm(v)) * float(np.linalg.norm(expected_dir)) + 1e-12
        )
        assert cos > 0.999, f"node {nid} velocity not radial: cos={cos}"
