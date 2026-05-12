"""Phase H Stage 5 — Wave neighbor expansion via virtual FAISS.

Previously the seed pool unioned raw + virtual but per-frontier
``search_by_id`` queried raw only. That broke "stars attract stars":
the star is the virtual position (raw + cached displacement), not the
raw embedding. This test proves that when a frontier seed pulls in its
neighbors, the neighbor set comes from virtual cosine when virtual FAISS
is available.

Scenario:
  - 3 isolated raw clusters (Q-cluster, A-cluster, B-cluster) so their
    raw cosines are roughly orthogonal.
  - Seed enters via Q-cluster.
  - A-cluster node has displacement pushed *toward* the seed's virtual
    position, so its virtual cosine to the seed is high even though its
    raw cosine is far.
  - B-cluster has no displacement; serves as the raw-only counterpart.

Expected:
  - With ``wave_neighbor_use_virtual=True`` (Phase L default): A reachable
    via wave depth-1 from the seed, B not reachable.
  - With ``wave_neighbor_use_virtual=False`` (legacy): inverse — A not
    reachable through wave (raw cosine too far), B still not reachable
    either (also far), so neither wave path surfaces them. The key claim
    is *only* that A reaches under the new flag and does not under the
    old flag.
"""
from __future__ import annotations

import hashlib

import numpy as np
import pytest

from gaottt.config import GaOTTTConfig
from gaottt.core.engine import GaOTTTEngine
from gaottt.core.gravity import propagate_gravity_wave
from gaottt.index.faiss_index import FaissIndex
from gaottt.store.cache import CacheLayer
from gaottt.store.sqlite_store import SqliteStore


class StubEmbedder:
    def __init__(self, dim: int = 768):
        self.dim = dim

    def encode_documents(self, contents):
        return np.array([self._embed(c) for c in contents], dtype=np.float32)

    def encode_query(self, text):
        return self._embed(text).reshape(1, -1).astype(np.float32)

    def _embed(self, text: str) -> np.ndarray:
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        seed = int.from_bytes(digest[:8], "big") & 0xFFFFFFFF
        rng = np.random.default_rng(seed)
        v = rng.standard_normal(self.dim).astype(np.float32)
        v /= np.linalg.norm(v) + 1e-9
        return v


def _make_engine(tmp_path, *, neighbor_use_virtual: bool):
    config = GaOTTTConfig(
        data_dir=str(tmp_path),
        db_path=str(tmp_path / "test.db"),
        faiss_index_path=str(tmp_path / "test.faiss"),
        virtual_faiss_index_path=str(tmp_path / "test.virtual.faiss"),
        virtual_faiss_enabled=True,
        virtual_faiss_save_interval_seconds=0.0,
        faiss_save_interval_seconds=0.0,
        wave_neighbor_use_virtual=neighbor_use_virtual,
        wave_initial_k=1,
        wave_seed_mass_alpha=0.0,
        wave_dynamic_k_enabled=False,
        genesis_kick_enabled=False,
        dream_enabled=False,
        flush_interval_seconds=0.05,
    )
    embedder = StubEmbedder(dim=config.embedding_dim)
    faiss_index = FaissIndex(dimension=config.embedding_dim)
    virtual_faiss_index = FaissIndex(dimension=config.embedding_dim)
    store = SqliteStore(db_path=config.db_path)
    cache = CacheLayer(
        flush_interval=config.flush_interval_seconds,
        flush_threshold=config.flush_threshold,
    )
    return GaOTTTEngine(
        config=config, embedder=embedder, faiss_index=faiss_index,
        cache=cache, store=store,
        virtual_faiss_index=virtual_faiss_index,
    )


async def _setup_three_clusters(engine):
    """Index a Q-cluster (seed lives here), an A-cluster, and a B-cluster.
    Returns (seed_id, a_id, b_id, query_vec)."""
    # Q-cluster: where the query lands and the seed lives.
    q_ids = await engine.index_documents([
        {"content": f"qcluster-{i}", "metadata": {"source": "agent"}}
        for i in range(5)
    ])
    # A-cluster: far from query in raw space.
    a_ids = await engine.index_documents([
        {"content": f"acluster-{i}", "metadata": {"source": "agent"}}
        for i in range(5)
    ])
    # B-cluster: also far from query in raw space, no displacement.
    b_ids = await engine.index_documents([
        {"content": f"bcluster-{i}", "metadata": {"source": "agent"}}
        for i in range(5)
    ])
    return q_ids, a_ids, b_ids


@pytest.mark.asyncio
async def test_neighbor_via_virtual_pulls_displaced_into_wave(tmp_path):
    """A node whose virtual position is close to the seed's virtual
    position should be reachable through wave neighbor expansion when
    Phase H Stage 5 is enabled — even though its raw cosine is far."""
    engine = _make_engine(tmp_path, neighbor_use_virtual=True)
    await engine.startup()
    try:
        q_ids, a_ids, b_ids = await _setup_three_clusters(engine)

        # Seed = top of Q-cluster relative to a chosen query.
        query_text = "qcluster-0"
        qv = engine.embedder.encode_query(query_text)
        seeds = engine.faiss_index.search(qv, 1)
        assert seeds, "no seed found in raw FAISS"
        seed_id = seeds[0][0]
        assert seed_id in q_ids, "seed did not come from Q-cluster"

        # Compute seed's raw embedding so we can aim A's displacement
        # towards it (no other node should reach this virtual coord).
        seed_raw = engine.faiss_index.get_vectors([seed_id])[seed_id]

        # Push the FIRST A-cluster node's displacement to land at seed_raw
        # in virtual space, so a_target's virtual_pos ~ seed_raw. With
        # mass=1 and normal config, the wave's min_sim threshold should
        # be easily cleared by ~0.99 virtual cosine.
        a_target = a_ids[0]
        a_raw = engine.faiss_index.get_vectors([a_target])[a_target]
        push = (seed_raw - a_raw) * 0.95
        norm = float(np.linalg.norm(push))
        if norm > engine.config.max_displacement_norm:
            push = push * (engine.config.max_displacement_norm / norm)
        engine.cache.set_displacement(a_target, push)

        await engine._rebuild_virtual_faiss_index()

        # Wave starts from a single Q-seed, expands depth-1 via virtual
        # cosine. a_target should appear in the reached set because its
        # virtual_pos ~ seed's virtual_pos.
        reached = propagate_gravity_wave(
            qv, engine.faiss_index, engine.cache, engine.config,
            wave_k=1, wave_depth=1,
            virtual_faiss_index=engine.virtual_faiss_index,
        )
        assert seed_id in reached, "seed itself missing from reached"
        assert a_target in reached, (
            f"displaced a_target {a_target[:8]} not reached via virtual "
            f"neighbor expansion; reached_ids={[r[:8] for r in reached]}"
        )
    finally:
        await engine.shutdown()


@pytest.mark.asyncio
async def test_legacy_raw_neighbor_misses_displaced_target(tmp_path):
    """The same scenario with wave_neighbor_use_virtual=False (legacy):
    the displaced a_target should NOT be reached, because raw cosine
    between seed and a_target is still far (displacement is invisible
    to raw FAISS)."""
    engine = _make_engine(tmp_path, neighbor_use_virtual=False)
    await engine.startup()
    try:
        q_ids, a_ids, b_ids = await _setup_three_clusters(engine)

        query_text = "qcluster-0"
        qv = engine.embedder.encode_query(query_text)
        seeds = engine.faiss_index.search(qv, 1)
        seed_id = seeds[0][0]
        seed_raw = engine.faiss_index.get_vectors([seed_id])[seed_id]

        a_target = a_ids[0]
        a_raw = engine.faiss_index.get_vectors([a_target])[a_target]
        push = (seed_raw - a_raw) * 0.95
        norm = float(np.linalg.norm(push))
        if norm > engine.config.max_displacement_norm:
            push = push * (engine.config.max_displacement_norm / norm)
        engine.cache.set_displacement(a_target, push)

        await engine._rebuild_virtual_faiss_index()

        reached = propagate_gravity_wave(
            qv, engine.faiss_index, engine.cache, engine.config,
            wave_k=1, wave_depth=1,
            virtual_faiss_index=engine.virtual_faiss_index,
        )
        # a_target's RAW cosine to the seed is unchanged by displacement,
        # so legacy raw neighbor search should not pull it in.
        assert a_target not in reached, (
            f"legacy mode should not reach a_target via raw neighbor, "
            f"but reached={[r[:8] for r in reached]}"
        )
    finally:
        await engine.shutdown()


@pytest.mark.asyncio
async def test_virtual_neighbor_falls_back_when_index_none(tmp_path):
    """When virtual_faiss_index is None, propagate_gravity_wave must
    silently fall back to raw neighbor search (no AttributeError)."""
    config = GaOTTTConfig(
        data_dir=str(tmp_path),
        db_path=str(tmp_path / "test.db"),
        faiss_index_path=str(tmp_path / "test.faiss"),
        virtual_faiss_enabled=False,
        virtual_faiss_save_interval_seconds=0.0,
        faiss_save_interval_seconds=0.0,
        wave_neighbor_use_virtual=True,  # On, but no virtual index given.
        genesis_kick_enabled=False,
        dream_enabled=False,
        flush_interval_seconds=0.05,
    )
    embedder = StubEmbedder(dim=config.embedding_dim)
    faiss_index = FaissIndex(dimension=config.embedding_dim)
    store = SqliteStore(db_path=config.db_path)
    cache = CacheLayer(
        flush_interval=config.flush_interval_seconds,
        flush_threshold=config.flush_threshold,
    )
    engine = GaOTTTEngine(
        config=config, embedder=embedder, faiss_index=faiss_index,
        cache=cache, store=store,
        virtual_faiss_index=None,
    )
    await engine.startup()
    try:
        await engine.index_documents([
            {"content": f"fallback-doc-{i}", "metadata": {"source": "agent"}}
            for i in range(3)
        ])
        qv = engine.embedder.encode_query("fallback-doc-0")
        # No exception is the main assertion; reach set is non-trivial.
        reached = propagate_gravity_wave(
            qv, engine.faiss_index, engine.cache, engine.config,
            wave_k=1, wave_depth=1,
            virtual_faiss_index=None,
        )
        assert len(reached) >= 1, "raw fallback wave should reach at least seed"
    finally:
        await engine.shutdown()
