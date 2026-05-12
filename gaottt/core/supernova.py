"""Phase K Stage 1 — Stellar supernova cohort formation at index time.

When ``engine.index_documents`` receives a batch of size ≥
``supernova_min_cohort_size``, the new nodes are treated as a single
supernova explosion event:

  (1) Mutual co-occurrence edges form between every pair in the batch
      (N×(N-1)/2 edges, weight = ``supernova_initial_weight``).
  (2) Each node receives an outward initial velocity from the batch
      centroid (``supernova_velocity_alpha × (embedding - centroid)``,
      clamped to ``orbital_max_velocity``).

Applied AFTER Phase G genesis_kick (existing-system binding); Phase K
adds cohort-internal binding + explosion energy. Velocities are added,
not replaced — both physics co-exist.

Why this exists (see docs/wiki/Plans-Phase-K-Stellar-Supernova-Cohort.md):

Phase J Stage 1 acceptance revealed that newly-remembered cohorts have
no mutual gravity, so they can't compete with mature past-session
clusters for FAISS top-K entry. Phase K fixes the physics of memory
creation rather than reranking after the fact.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from gaottt.core.gravity import clamp_vector

if TYPE_CHECKING:
    from gaottt.config import GaOTTTConfig


def compute_supernova_velocities(
    batch_ids: list[str],
    batch_embeddings: np.ndarray,
    config: "GaOTTTConfig",
) -> dict[str, np.ndarray]:
    """Compute outward velocity for each node in the supernova batch.

    velocity(node) = α × (embedding(node) - centroid), clamped to
    orbital_max_velocity. Two-node cohorts get reciprocal velocities
    (each pushes away from the other); larger cohorts radiate outward
    from the batch centroid.

    Returns empty dict if Phase K is disabled, the batch is smaller
    than ``supernova_min_cohort_size``, or α ≤ 0.
    """
    n = len(batch_ids)
    if (
        not config.supernova_enabled
        or n < config.supernova_min_cohort_size
        or config.supernova_velocity_alpha <= 0.0
    ):
        return {}

    centroid = batch_embeddings.mean(axis=0)
    velocities: dict[str, np.ndarray] = {}
    for i, nid in enumerate(batch_ids):
        radial = batch_embeddings[i] - centroid
        velocity = (config.supernova_velocity_alpha * radial).astype(np.float32)
        velocity = clamp_vector(velocity, config.orbital_max_velocity)
        velocities[nid] = velocity
    return velocities


def form_supernova_edges(
    batch_ids: list[str],
    config: "GaOTTTConfig",
) -> list[tuple[str, str, float]]:
    """Return ``[(src, dst, weight), ...]`` for every pair in the cohort.

    Edges are undirected (Phase B co-occurrence semantics); the caller
    (``cache.set_edge``) mirrors both directions in the graph cache.
    All pairs share ``supernova_initial_weight`` — the event itself is
    the source of edge weight, not recall accumulation.
    """
    n = len(batch_ids)
    if (
        not config.supernova_enabled
        or n < config.supernova_min_cohort_size
        or config.supernova_initial_weight <= 0.0
    ):
        return []
    weight = config.supernova_initial_weight
    edges: list[tuple[str, str, float]] = []
    for i in range(n):
        for j in range(i + 1, n):
            edges.append((batch_ids[i], batch_ids[j], weight))
    return edges
