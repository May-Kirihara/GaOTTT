"""Gravitational dynamics: displacement, velocity, orbital mechanics.

Documents attract each other in embedding space through Newtonian gravity.
Velocity vectors give nodes inertia, enabling orbits, cometary trajectories,
and gravitational slingshots.
"""

from __future__ import annotations

import logging
import math
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from gaottt.index.bm25_index import BM25Index
    from gaottt.index.faiss_index import FaissIndex
    from gaottt.store.cache import CacheLayer

from gaottt.config import GaOTTTConfig

logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------
# Virtual position
# -----------------------------------------------------------------------

def compute_virtual_position(
    original_emb: np.ndarray,
    displacement: np.ndarray | None,
    temperature: float = 0.0,
) -> np.ndarray:
    """Compute virtual position = normalize(original + displacement + thermal noise)."""
    pos = original_emb.copy()
    if displacement is not None:
        pos = pos + displacement
    if temperature > 0.001:
        noise = np.random.randn(*pos.shape).astype(np.float32) * temperature
        pos = pos + noise
    norm = np.linalg.norm(pos)
    if norm > 0:
        pos = pos / norm
    return pos


def clamp_vector(vec: np.ndarray, max_norm: float) -> np.ndarray:
    """Clamp vector to maximum L2 norm."""
    norm = float(np.linalg.norm(vec))
    if norm > max_norm:
        return (vec * (max_norm / norm)).astype(np.float32)
    return vec


# Legacy alias
clamp_displacement = clamp_vector


# -----------------------------------------------------------------------
# Orbital mechanics (Stage 1-2-3)
# -----------------------------------------------------------------------

def compute_bh_acceleration(
    pos_i: np.ndarray,
    node_id: str,
    temperature_i: float,
    cache: "CacheLayer",
    all_positions: dict[str, np.ndarray],
    config: GaOTTTConfig,
) -> np.ndarray:
    """Compute gravitational acceleration from co-occurrence cluster black hole.

    The BH is located at the weighted centroid of co-occurrence neighbors.
    Its mass is proportional to log(1 + total_edge_weight).

    Two dampening mechanisms:
    - Presentation saturation: neighbors returned often to LLM contribute less to BH mass
    - Thermal escape: high-temperature nodes resist BH capture
    """
    neighbors = cache.get_neighbors(node_id)
    if not neighbors:
        return np.zeros_like(pos_i)

    total_weight = 0.0
    centroid = np.zeros_like(pos_i)
    for neighbor_id, weight in neighbors.items():
        pos_j = all_positions.get(neighbor_id)
        if pos_j is None:
            continue
        # Saturation: neighbors returned often contribute less to BH
        neighbor_state = cache.get_node(neighbor_id)
        rc = neighbor_state.return_count if neighbor_state else 0.0
        saturation = 1.0 / (1.0 + rc * config.saturation_rate)
        effective_weight = weight * saturation

        centroid = centroid + effective_weight * pos_j
        total_weight += effective_weight

    if total_weight < 1e-8:
        return np.zeros_like(pos_i)

    centroid = centroid / total_weight
    bh_mass = config.bh_mass_scale * math.log(1.0 + total_weight)

    diff = centroid - pos_i
    distance_sq = float(np.dot(diff, diff)) + config.gravity_epsilon
    distance = math.sqrt(distance_sq)
    G = config.bh_gravity_G if config.bh_gravity_G > 0 else config.gravity_G
    magnitude = G * bh_mass / distance_sq
    direction = diff / distance

    # Thermal escape: high temperature nodes resist BH capture
    escape_factor = 1.0 / (1.0 + temperature_i * config.thermal_escape_scale)

    return (magnitude * direction * escape_factor).astype(np.float32)


def compute_acceleration(
    pos_i: np.ndarray,
    original_pos_i: np.ndarray,
    displacement_i: np.ndarray,
    neighbors: list[tuple[np.ndarray, float]],
    config: GaOTTTConfig,
    node_id: str | None = None,
    cache: "CacheLayer | None" = None,
    all_positions: dict[str, np.ndarray] | None = None,
    mass_i: float | None = None,
    query_anchor: np.ndarray | None = None,
    query_score: float | None = None,
) -> np.ndarray:
    """Compute total gravitational acceleration on node i.

    Four components:
    1. Neighbor gravity: a = Σ_j [ G * m_j / (r² + ε) * direction(i→j) ]
    2. Anchor restoring force: a = -k * displacement (Hooke's law)
    3. Co-occurrence BH gravity: attraction toward cluster centroid
    4. Query attraction (Phase I Stage 2 + Stage 3 mass-gating):
       a = (α · score · gate / m_i) · (q - pos), gate = tanh(m_i / θ)
       Transient mass-damped force toward the query embedding. Acts as the
       Hebbian gradient term in the TTT reading — repeated retrievals for a
       given query gradually pull the node toward that direction. The
       Stage 3 gate protects brand-new (low-mass) nodes from being
       one-shot pulled into the "near every query" position by anchor
       (Hooke component 2); mature nodes (mass ≫ θ) receive ~full kick.
       Active iff config.query_kick_enabled, config.query_kick_strength > 0,
       and the caller passes mass_i + query_anchor + query_score.
       θ = config.mass_anchor_threshold; θ=0 forces gate=1.0 (Stage 2
       legacy behaviour).
    """
    acc = np.zeros_like(pos_i)

    # 1. Neighbor gravitational acceleration
    for pos_j, mass_j in neighbors:
        diff = pos_j - pos_i
        distance_sq = float(np.dot(diff, diff)) + config.gravity_epsilon
        distance = math.sqrt(distance_sq)
        magnitude = config.gravity_G * mass_j / distance_sq
        direction = diff / distance
        acc = acc + magnitude * direction

    # 2. Anchor restoring force (Hooke's law)
    acc = acc - config.orbital_anchor_strength * displacement_i

    # 3. Co-occurrence black hole gravity (with saturation + thermal escape)
    if node_id is not None and cache is not None and all_positions is not None:
        node_state = cache.get_node(node_id)
        temp_i = node_state.temperature if node_state else 0.0
        acc = acc + compute_bh_acceleration(pos_i, node_id, temp_i, cache, all_positions, config)

    # 4. Query attraction (Phase I Stage 2 + Stage 3 mass-gating)
    if (
        config.query_kick_enabled
        and config.query_kick_strength > 0.0
        and query_anchor is not None
        and query_score is not None
        and mass_i is not None
        and mass_i > 0.0
    ):
        diff_q = query_anchor - pos_i
        # Stage 3 — Mass-gated query attraction:
        # gate = tanh(m_i / θ). Brand-new nodes (mass≈1) are protected by
        # anchor (Hooke) — kick is damped to ~32% at θ=3. Mature nodes
        # (mass≫θ) receive full kick. θ=0 forces gate=1.0 (Stage 2 legacy).
        if config.mass_anchor_threshold > 0.0:
            gate = math.tanh(float(mass_i) / config.mass_anchor_threshold)
        else:
            gate = 1.0
        kick = (config.query_kick_strength * float(query_score) * gate / float(mass_i)) * diff_q
        acc = acc + kick

    return acc.astype(np.float32)


def update_velocity(
    velocity: np.ndarray,
    acceleration: np.ndarray,
    last_access: float,
    now: float,
    config: GaOTTTConfig,
) -> np.ndarray:
    """Update velocity: v += a*dt, apply friction, clamp.

    Two friction sources:
    - Constant: v *= (1 - friction)
    - Age-based: older nodes get additional friction
    """
    # Stage 2a: Apply acceleration (dt = 1.0 per query step)
    v = velocity + acceleration

    # Stage 2b: Constant friction
    v = v * (1.0 - config.orbital_friction)

    # Stage 2c: Age-based friction (unaccessed nodes slow down more)
    age = now - last_access
    age_friction = config.orbital_friction_age_factor * (1.0 - math.exp(-config.displacement_age_delta * age))
    v = v * (1.0 - age_friction)

    # Stage 2d: Clamp velocity
    v = clamp_vector(v, config.orbital_max_velocity)

    return v.astype(np.float32)


def update_orbital_state(
    node_ids: list[str],
    original_embeddings: dict[str, np.ndarray],
    displacements: dict[str, np.ndarray],
    velocities: dict[str, np.ndarray],
    masses: dict[str, float],
    last_accesses: dict[str, float],
    now: float,
    config: GaOTTTConfig,
    cache: "CacheLayer | None" = None,
    query_anchor: np.ndarray | None = None,
    query_scores: dict[str, float] | None = None,
) -> tuple[dict[str, np.ndarray], dict[str, np.ndarray]]:
    """Full orbital mechanics step for all nodes.

    Stage 1: Compute accelerations (neighbor gravity + anchor + co-occurrence BH
             + Phase I Stage 2 query attraction, if query_anchor + query_scores
             are provided)
    Stage 2: Update velocities (+ friction)
    Stage 3: Update displacements (+ clamp)

    Returns: (updated_displacements, updated_velocities)
    """
    dim = config.embedding_dim

    # Gather current virtual positions
    positions: dict[str, np.ndarray] = {}
    for nid in node_ids:
        emb = original_embeddings.get(nid)
        if emb is None:
            continue
        disp = displacements.get(nid, np.zeros(dim, dtype=np.float32))
        positions[nid] = emb + disp

    active_ids = [nid for nid in node_ids if nid in positions]
    if len(active_ids) < 2:
        return displacements, velocities

    # Stage 1: Compute acceleration for each node
    accelerations: dict[str, np.ndarray] = {}
    for nid in active_ids:
        neighbors = [
            (positions[other], masses.get(other, 1.0))
            for other in active_ids
            if other != nid
        ]
        disp = displacements.get(nid, np.zeros(dim, dtype=np.float32))
        q_score = query_scores.get(nid) if query_scores is not None else None
        accelerations[nid] = compute_acceleration(
            positions[nid], original_embeddings[nid], disp, neighbors, config,
            node_id=nid, cache=cache, all_positions=positions,
            mass_i=masses.get(nid, 1.0),
            query_anchor=query_anchor,
            query_score=q_score,
        )

    # Stage 2 & 3: Update velocity then displacement
    new_displacements: dict[str, np.ndarray] = {}
    new_velocities: dict[str, np.ndarray] = {}

    for nid in active_ids:
        old_vel = velocities.get(nid, np.zeros(dim, dtype=np.float32))
        old_disp = displacements.get(nid, np.zeros(dim, dtype=np.float32))
        last_access = last_accesses.get(nid, now)

        # Stage 2: velocity update
        new_vel = update_velocity(old_vel, accelerations[nid], last_access, now, config)

        # Stage 3: position update (displacement += velocity * dt)
        new_disp = old_disp + new_vel  # dt = 1.0
        new_disp = clamp_vector(new_disp, config.max_displacement_norm)

        new_velocities[nid] = new_vel
        new_displacements[nid] = new_disp

    return new_displacements, new_velocities


# -----------------------------------------------------------------------
# Phase G — Genesis kick: initial gravitational binding for brand-new nodes
# -----------------------------------------------------------------------

def compute_gravity_kick(
    new_pos: np.ndarray,
    neighbors: list[tuple[np.ndarray, float]],
    config: GaOTTTConfig,
) -> tuple[np.ndarray, np.ndarray, float]:
    """One-step orbital integration for a freshly-indexed node.

    Treats the new node as starting from displacement=0, velocity=0 at its
    embedding position, then applies one timestep (dt=1) of the same
    Newtonian neighbor-gravity formula used in compute_acceleration's
    inner loop. Returns the resulting (displacement, velocity, mass_boost)
    so engine.index_documents can seed cache state with non-zero values.

    The point is structural correspondence with the existing physics, not
    a separate special-case rule. A new particle, like every other particle,
    feels gravity from its surroundings — we were just forgetting to step
    that first interaction.
    """
    zero = np.zeros_like(new_pos)
    if not neighbors:
        return zero.astype(np.float32), zero.astype(np.float32), 0.0

    acc = np.zeros_like(new_pos)
    for pos_j, mass_j in neighbors:
        diff = pos_j - new_pos
        distance_sq = float(np.dot(diff, diff)) + config.gravity_epsilon
        distance = math.sqrt(distance_sq)
        magnitude = config.gravity_G * mass_j / distance_sq
        direction = diff / distance
        acc = acc + magnitude * direction

    # Verlet step from rest: v_new = v_old + a*dt = a*dt; d_new = d_old + v_new*dt.
    # gravity_eta scales the integration to match the existing legacy step
    # (compute_gravitational_force uses the same factor).
    velocity = config.gravity_eta * acc
    velocity = clamp_vector(velocity, config.orbital_max_velocity)
    displacement = clamp_vector(velocity.copy(), config.max_displacement_norm)

    raw_boost = config.genesis_mass_boost_alpha * float(np.linalg.norm(acc))
    # Cap so a single kick can never make mass leap close to m_max — keeps
    # accretion physically gradual and aligned with the rest of the model.
    mass_boost = min(raw_boost, config.genesis_mass_boost_cap)

    return (
        displacement.astype(np.float32),
        velocity.astype(np.float32),
        mass_boost,
    )


# -----------------------------------------------------------------------
# Legacy functions (kept for backward compatibility)
# -----------------------------------------------------------------------

def compute_gravitational_force(
    pos_i: np.ndarray, pos_j: np.ndarray,
    mass_i: float, mass_j: float, config: GaOTTTConfig,
) -> np.ndarray:
    """Legacy: compute force vector (used by old displacement-only model)."""
    diff = pos_j - pos_i
    distance_sq = float(np.dot(diff, diff)) + config.gravity_epsilon
    distance = math.sqrt(distance_sq)
    force_magnitude = config.gravity_G * mass_i * mass_j / distance_sq
    direction = diff / distance
    delta = config.gravity_eta * force_magnitude * direction
    return delta.astype(np.float32)


def apply_displacement_decay(
    displacement: np.ndarray, displacement_decay: float,
    last_access: float, now: float, age_delta: float,
) -> np.ndarray:
    """Legacy: direct displacement decay (replaced by friction in orbital model)."""
    age_factor = math.exp(-age_delta * (now - last_access))
    return (displacement * displacement_decay * age_factor).astype(np.float32)


# -----------------------------------------------------------------------
# Gravity Wave Propagation (unchanged)
# -----------------------------------------------------------------------

def _rrf_fusion(
    pools: list[list[tuple[str, float]]],
    rrf_k: int,
) -> list[tuple[str, float]]:
    """Reciprocal Rank Fusion across multiple ranked lists.

    Each doc's fused score is ``Σ over pools containing it: 1 / (rrf_k + rank_1based)``.
    Documents absent from a pool contribute 0 for that pool. The original
    per-pool scores are dropped — RRF is rank-only by design (scale-invariant).
    Returns the fused list sorted descending by fused score; scores are RRF
    sums (typically in the [0, n_pools/(rrf_k+1)] range).

    Cormack et al. 2009 (SIGIR) introduces RRF as a robust scale-invariant
    fusion suited for combining heterogeneous-metric retrievers (e.g.,
    cosine + BM25).
    """
    scores: dict[str, float] = {}
    for pool in pools:
        for rank, (nid, _raw) in enumerate(pool, start=1):
            scores[nid] = scores.get(nid, 0.0) + 1.0 / (rrf_k + rank)
    fused = sorted(scores.items(), key=lambda t: t[1], reverse=True)
    return fused


def _weighted_sum_fusion(
    pool_cosine: list[tuple[str, float]],
    pool_bm25: list[tuple[str, float]],
    bm25_alpha: float,
) -> list[tuple[str, float]]:
    """Fallback fusion: min-max normalize BM25 then linear combine with cosine.

    ``fused = cosine_score * (1 - α) + bm25_norm * α``. A doc present in
    only one pool contributes 0 from the missing side. Used when
    ``bm25_score_mode == "weighted_sum"`` (D1 decision: default is "rrf",
    this stays as an opt-in flag).
    """
    bm25_dict = dict(pool_bm25)
    if bm25_dict:
        vals = list(bm25_dict.values())
        b_min, b_max = min(vals), max(vals)
        b_range = (b_max - b_min) if b_max > b_min else 1.0
        bm25_norm = {nid: (s - b_min) / b_range for nid, s in bm25_dict.items()}
    else:
        bm25_norm = {}
    cosine_dict = dict(pool_cosine)
    all_ids = set(cosine_dict.keys()) | set(bm25_norm.keys())
    fused: list[tuple[str, float]] = []
    for nid in all_ids:
        c = cosine_dict.get(nid, 0.0)
        b = bm25_norm.get(nid, 0.0)
        score = c * (1.0 - bm25_alpha) + b * bm25_alpha
        fused.append((nid, score))
    fused.sort(key=lambda t: t[1], reverse=True)
    return fused


def _union_pool(
    qv: np.ndarray,
    raw_index: "FaissIndex",
    virtual_index: "FaissIndex | None",
    pool_size: int,
    query_text: str | None = None,
    bm25_index: "BM25Index | None" = None,
    bm25_score_mode: str = "rrf",
    bm25_score_alpha: float = 0.5,
    rrf_k: int = 60,
) -> list[tuple[str, float]]:
    """Take top-N from raw FAISS, optionally union with virtual FAISS (Phase H
    Stage 4) and BM25 (Phase L Stage 1), deduplicate by id.

    The semantic stack (raw + virtual cosine) and the lexical stack (BM25)
    are independent metric tensors — surface-form matches BM25 catches
    that embedder cosine misses. RRF fusion combines ranks scale-invariantly
    across whichever indexes are available; ``weighted_sum`` mode is
    available as a flag and falls back to the Phase H Stage 4 max-merge
    when BM25 is absent.

    When neither virtual nor BM25 is supplied (legacy callers), this
    returns the raw FAISS top-N unchanged.
    """
    pool_raw = raw_index.search(qv.reshape(1, -1), pool_size)
    pool_virtual: list[tuple[str, float]] = []
    if virtual_index is not None and virtual_index.size > 0:
        pool_virtual = virtual_index.search(qv.reshape(1, -1), pool_size)
    pool_bm25: list[tuple[str, float]] = []
    if (
        bm25_index is not None
        and bm25_index.size > 0
        and query_text
    ):
        pool_bm25 = bm25_index.search(query_text, pool_size)

    if not pool_virtual and not pool_bm25:
        return pool_raw

    # Phase L Stage 1: RRF fires only when BM25 is actually contributing.
    # Without BM25, the two semantic pools (raw + virtual) share a scale
    # (cosine [-1, 1]) so we keep the Phase H Stage 4 max-merge — switching
    # to RRF there would erase the score continuity Phase H tests rely on.
    if pool_bm25 and bm25_score_mode == "rrf":
        pools: list[list[tuple[str, float]]] = [pool_raw]
        if pool_virtual:
            pools.append(pool_virtual)
        pools.append(pool_bm25)
        return _rrf_fusion(pools, rrf_k=rrf_k)

    # Phase H Stage 4 max-merge of raw + virtual (cosine same scale).
    semantic: dict[str, float] = {}
    for nid, score in pool_raw:
        prev = semantic.get(nid)
        if prev is None or score > prev:
            semantic[nid] = score
    for nid, score in pool_virtual:
        prev = semantic.get(nid)
        if prev is None or score > prev:
            semantic[nid] = score
    semantic_list = sorted(semantic.items(), key=lambda t: t[1], reverse=True)

    # Phase L Stage 1 weighted_sum mode: blend BM25 into the semantic merge.
    if pool_bm25 and bm25_score_mode == "weighted_sum":
        return _weighted_sum_fusion(semantic_list, pool_bm25, bm25_alpha=bm25_score_alpha)
    return semantic_list


def _seed_boost(
    nid: str,
    raw: float,
    cache: "CacheLayer",
    config: GaOTTTConfig,
    persona_proximities: dict[str, float] | None,
) -> float:
    """Combine raw cosine with mass-aware (Phase H Stage 1) and persona-aware
    (Phase J Stage 1) boosts. Each component is gated by its own config knob
    so any subset can be disabled independently.
    """
    score = raw
    if config.wave_seed_mass_alpha > 0.0:
        state = cache.get_node(nid)
        mass = state.mass if state is not None else 1.0
        score += config.wave_seed_mass_alpha * math.log(1.0 + mass)
    if persona_proximities is not None and config.persona_boost_alpha > 0.0:
        proximity = persona_proximities.get(nid, 0.0)
        if proximity > 0.0:
            score += config.persona_boost_alpha * proximity
    return score


def _inject_into_pool(
    pool: list[tuple[str, float]],
    injected_ids: set[str],
    qv: np.ndarray,
    faiss_index: "FaissIndex",
) -> list[tuple[str, float]]:
    """Phase J Stage 2 — add ``injected_ids`` to ``pool`` (additive injection),
    computing each id's raw cosine against ``qv`` from FAISS embeddings.

    De-duplicates by id (keeping the existing pool entry when overlapping).
    Returns a re-sorted (desc by raw cosine) pool. Ids whose embedding is
    missing from FAISS are silently skipped.
    """
    if not injected_ids:
        return pool
    pool_ids = {nid for nid, _ in pool}
    missing = [nid for nid in injected_ids if nid not in pool_ids]
    if not missing:
        return pool
    vec_map = faiss_index.get_vectors(missing)
    if not vec_map:
        return pool
    qv_norm = float(np.linalg.norm(qv)) + 1e-12
    for nid, emb in vec_map.items():
        emb_norm = float(np.linalg.norm(emb)) + 1e-12
        raw = float(np.dot(qv, emb)) / (qv_norm * emb_norm)
        pool.append((nid, raw))
    pool.sort(key=lambda t: t[1], reverse=True)
    return pool


def propagate_gravity_wave(
    query_vector: np.ndarray,
    faiss_index: "FaissIndex",
    cache: "CacheLayer",
    config: GaOTTTConfig,
    wave_k: int | None = None,
    wave_depth: int | None = None,
    source_filter: list[str] | None = None,
    virtual_faiss_index: "FaissIndex | None" = None,
    persona_proximities: dict[str, float] | None = None,
    injected_ids: set[str] | None = None,
    query_text: str | None = None,
    bm25_index: "BM25Index | None" = None,
) -> dict[str, float]:
    """Propagate gravity wave recursively through embedding space.

    Phase H Stage 1 — Mass-aware seed boosting: when ``wave_seed_mass_alpha
    > 0``, the seed step takes a wider FAISS pool than ``initial_k`` and
    reranks by ``raw_cosine + α * log(1+mass)``. Heavy nodes that sit just
    outside raw cosine top-K still enter the wave.

    Phase H Stage 2 — Source-aware seed filtering: when ``source_filter``
    is set, the seed step pulls a wide pool (``wave_k_with_filter``) and
    keeps only members whose ``cache.source_by_id`` matches one of the
    requested sources. This is the only way sparse classes (agent / value
    / commitment) reliably enter the wave on corpus-heavy DBs where they
    lose every raw-cosine contest to dense Twitter / book clusters. Mass
    boosting is still applied to the post-filter set if α > 0.

    Phase H Stage 4 — Virtual FAISS: when ``virtual_faiss_index`` is
    provided and non-empty, the seed pool is the union of top-N from raw
    and from virtual indexes. Phase G priming moves displacement on every
    active node, which raw FAISS does not see; virtual FAISS does, so
    primed nodes can still enter the seed pool through it.

    Phase H Stage 5 — Virtual FAISS also drives neighbor expansion: per-
    frontier ``search_by_id`` queries the virtual index instead of raw
    when ``config.wave_neighbor_use_virtual`` is True (default) and a
    non-empty virtual index is supplied. The "star" in this model is the
    virtual position (raw + cached displacement), so star-to-star gravity
    is best expressed by neighbor search against virtual cosine. Falls
    back to raw when virtual is unavailable or opted out.

    Phase J Stage 1 — Persona-anchored seed boosting: when
    ``persona_proximities`` is provided (typically from
    ``persona_gravity.compute_persona_proximities``) and
    ``persona_boost_alpha > 0``, the seed score adds
    ``α_persona × proximity(nid)``. Nodes within N hops of a declared
    value / intention / commitment via fulfills / derived_from edges
    are preferentially admitted to the seed pool — the persona layer
    bends retrieval geometry. Caller is responsible for computing
    proximities (engine.query does this once per recall).

    Phase J Stage 2 — Additive pool injection: when ``injected_ids`` is
    provided (typically the union of nodes matching the caller's
    ``tag_filter`` and ``persona_context`` arguments), those ids are
    union-merged into the FAISS top-K pool with their true raw cosine,
    *bypassing* ``source_filter`` restrictions. This solves the Stage 1
    pool-entry pathology: when query embedding is far from a sparse
    cohort, neither mass nor persona reranking can rescue it because
    the cohort never enters the pool. Explicit injection guarantees
    entry; subsequent rerank still applies the usual boosts.

    Set ``config.wave_seed_mass_alpha=0``, ``config.persona_boost_alpha=0``
    and pass no ``source_filter`` / ``virtual_faiss_index`` /
    ``persona_proximities`` / ``injected_ids`` to recover legacy
    raw-cosine top-K seeding.
    """
    initial_k = wave_k if wave_k is not None else config.wave_initial_k
    max_depth = wave_depth if wave_depth is not None else config.wave_max_depth

    qv = query_vector[0] if query_vector.ndim == 2 else query_vector

    # Any boost path is active if at least one of (mass α, persona α) is on,
    # OR if explicit injection is requested.
    has_seed_boost = (
        config.wave_seed_mass_alpha > 0.0
        or (persona_proximities is not None and config.persona_boost_alpha > 0.0)
    )
    has_injection = bool(injected_ids)

    # Phase L Stage 1: globally disable BM25 contribution when the config
    # flag is off. The flag is the single rollback knob (decision in Plans
    # — set hybrid_bm25_enabled=False to fully revert to Phase H Stage 4).
    bm25_effective = bm25_index if config.hybrid_bm25_enabled else None

    if source_filter:
        sf_set = set(source_filter)
        pool_size = max(initial_k, config.wave_k_with_filter)
        pool = _union_pool(
            qv, faiss_index, virtual_faiss_index, pool_size,
            query_text=query_text,
            bm25_index=bm25_effective,
            bm25_score_mode=config.bm25_score_mode,
            bm25_score_alpha=config.bm25_score_alpha,
            rrf_k=config.rrf_k,
        )
        if has_injection:
            pool = _inject_into_pool(pool, injected_ids, qv, faiss_index)
        if not pool:
            return {}
        candidates: list[tuple[str, float, float]] = []
        for nid, raw in pool:
            # Phase J Stage 2: injected ids bypass source_filter restrictions.
            # Caller explicitly asked for them; respect that signal.
            if nid not in (injected_ids or set()):
                src = cache.get_source(nid)
                if src not in sf_set:
                    continue
            boosted = _seed_boost(nid, raw, cache, config, persona_proximities)
            candidates.append((nid, boosted, raw))
        candidates.sort(key=lambda t: t[1], reverse=True)
        # Phase J Stage 2: also force-include injected ids in the seed set
        # on this restrictive path (same reasoning as the boost path below).
        # When more nodes are injected than ``initial_k``, take the top
        # ``initial_k`` of *the injected set itself* — otherwise we'd blow
        # past the requested seed budget and the wave would explode.
        if has_injection:
            inject_set = set(injected_ids)
            forced = [(nid, raw) for nid, _, raw in candidates if nid in inject_set]
            others = [(nid, raw) for nid, _, raw in candidates if nid not in inject_set]
            if len(forced) >= initial_k:
                seeds = forced[:initial_k]
            else:
                seeds = forced + others[: initial_k - len(forced)]
        else:
            seeds = [(nid, raw) for nid, _, raw in candidates[:initial_k]]
    elif has_seed_boost or has_injection:
        pool_size = max(initial_k, config.wave_seed_pool_size)
        pool = _union_pool(
            qv, faiss_index, virtual_faiss_index, pool_size,
            query_text=query_text,
            bm25_index=bm25_effective,
            bm25_score_mode=config.bm25_score_mode,
            bm25_score_alpha=config.bm25_score_alpha,
            rrf_k=config.rrf_k,
        )
        if has_injection:
            pool = _inject_into_pool(pool, injected_ids, qv, faiss_index)
        if not pool:
            return {}

        # Phase H Stage 3: density-aware dynamic wave_k. If the top-N raw
        # cosine scores are tightly packed ("dense" cluster), keep
        # initial_k seeds. If they fall off sharply ("sparse" region), the
        # query lacks close neighbors — expand seed count up to
        # wave_initial_k_max so the wave reaches further before scoring
        # narrows it.
        effective_k = initial_k
        if config.wave_dynamic_k_enabled and len(pool) >= 2:
            top_score = pool[0][1]
            window = min(config.wave_density_window, len(pool)) - 1
            tail_score = pool[window][1]
            if top_score > 1e-9:
                density_ratio = tail_score / top_score
                if density_ratio < config.wave_density_threshold:
                    effective_k = min(config.wave_initial_k_max, len(pool))

        rescored: list[tuple[str, float, float]] = []
        for nid, raw in pool:
            boosted = _seed_boost(nid, raw, cache, config, persona_proximities)
            rescored.append((nid, boosted, raw))
        rescored.sort(key=lambda t: t[1], reverse=True)

        # Phase J Stage 2: injected ids are *forced* into the seed set
        # regardless of rerank position. The caller explicitly asked for
        # them, so rerank order shouldn't be able to evict them. When the
        # injected set is larger than ``effective_k`` we cap at
        # ``effective_k`` of the injected (top by raw cosine) — otherwise
        # the seed pool would blow past its budget and the wave would
        # explode into hundreds of reached nodes.
        if has_injection:
            inject_set = set(injected_ids)
            forced = [(nid, raw) for nid, _, raw in rescored if nid in inject_set]
            others = [(nid, raw) for nid, _, raw in rescored if nid not in inject_set]
            if len(forced) >= effective_k:
                seeds = forced[:effective_k]
            else:
                seeds = forced + others[: effective_k - len(forced)]
        else:
            seeds = [(nid, raw) for nid, _, raw in rescored[:effective_k]]
    else:
        seeds = _union_pool(
            qv, faiss_index, virtual_faiss_index, initial_k,
            query_text=query_text,
            bm25_index=bm25_effective,
            bm25_score_mode=config.bm25_score_mode,
            bm25_score_alpha=config.bm25_score_alpha,
            rrf_k=config.rrf_k,
        )
    if not seeds:
        return {}

    reached: dict[str, float] = {}
    frontier: list[tuple[str, float]] = [(nid, 1.0) for nid, _ in seeds]

    for nid, force in frontier:
        reached[nid] = max(reached.get(nid, 0.0), force)

    # Phase H Stage 5 — Neighbor search index selection. The "star"
    # in this model is the virtual position (raw + cached displacement),
    # so star-to-star gravity is most faithfully expressed by neighbor
    # search against the virtual index. Raw FAISS is the static sky and
    # cannot see displacement updates. When virtual is unavailable
    # (None / empty / opt-out), fall back to raw — the old behaviour.
    use_virtual_neighbors = (
        config.wave_neighbor_use_virtual
        and virtual_faiss_index is not None
        and virtual_faiss_index.size > 0
    )
    neighbor_index = virtual_faiss_index if use_virtual_neighbors else faiss_index

    for depth in range(1, max_depth + 1):
        next_frontier: list[tuple[str, float]] = []

        for node_id, parent_force in frontier:
            state = cache.get_node(node_id)
            mass = state.mass if state else 1.0

            node_k = config.compute_node_top_k(mass)
            attenuation = config.compute_effective_attenuation(mass)
            child_force = parent_force * attenuation

            if child_force < 0.001:
                continue

            min_sim = config.compute_gravity_radius(mass)
            neighbors = neighbor_index.search_by_id(node_id, node_k + 1)

            for neighbor_id, sim_score in neighbors:
                if neighbor_id == node_id:
                    continue
                if sim_score < min_sim:
                    continue

                old_force = reached.get(neighbor_id, 0.0)
                new_force = old_force + child_force
                reached[neighbor_id] = new_force

                if old_force == 0.0:
                    next_frontier.append((neighbor_id, child_force))

        frontier = next_frontier

    # Phase J Stage 2 fix: injected_ids that were cut from seeds due to
    # the initial_k cap never enter the wave and are absent from `reached`.
    # Force-include them with force=1.0 (same as a direct seed) so they
    # participate in scoring via their own embedding, not silently dropped.
    if injected_ids:
        for nid in injected_ids:
            if nid not in reached:
                reached[nid] = 1.0

    return reached
