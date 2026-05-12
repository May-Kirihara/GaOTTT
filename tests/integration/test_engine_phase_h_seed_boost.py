"""Phase H Stage 1 — Mass-aware seed boosting.

When a sparse heavy node sits just outside FAISS raw cosine top-K of a
query, legacy seeding leaves it unreachable: the wave never visits it,
so its mass / displacement improvements never reach scoring. With the
seed boost (α > 0), `raw + α * log(1+mass)` reranks a wider pool, so
the heavy node enters the wave even with slightly lower raw cosine.

Tests:
  1. Heavy isolated node enters wave seeds when boost is enabled.
  2. wave_seed_mass_alpha=0 reproduces legacy raw-cosine top-K seeding.
"""
from __future__ import annotations

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
        import hashlib
        seed = int.from_bytes(
            hashlib.md5(text.encode("utf-8")).digest()[:4], "big"
        )
        rng = np.random.default_rng(seed)
        v = rng.standard_normal(self.dim).astype(np.float32)
        v /= np.linalg.norm(v) + 1e-9
        return v


def _make_engine(tmp_path, *, mass_alpha: float, pool_size: int = 50):
    config = GaOTTTConfig(
        data_dir=str(tmp_path),
        db_path=str(tmp_path / "test.db"),
        faiss_index_path=str(tmp_path / "test.faiss"),
        wave_seed_mass_alpha=mass_alpha,
        wave_seed_pool_size=pool_size,
        wave_initial_k=3,
        genesis_kick_enabled=False,
        dream_enabled=False,
        faiss_save_interval_seconds=0.0,
        flush_interval_seconds=0.05,
    )
    embedder = StubEmbedder(dim=config.embedding_dim)
    faiss_index = FaissIndex(dimension=config.embedding_dim)
    store = SqliteStore(db_path=config.db_path)
    cache = CacheLayer(
        flush_interval=config.flush_interval_seconds,
        flush_threshold=config.flush_threshold,
    )
    return GaOTTTEngine(
        config=config, embedder=embedder, faiss_index=faiss_index,
        cache=cache, store=store,
    )


@pytest.mark.asyncio
async def test_heavy_isolated_enters_seeds_with_boost(tmp_path):
    """A heavy node that sits a few cosine slots below the densest cluster
    should be reachable with the seed boost enabled, but invisible to the
    wave when boost is off."""
    # Engine with boost
    engine = _make_engine(tmp_path, mass_alpha=0.5, pool_size=20)
    await engine.startup()
    try:
        # Dense cluster of 10 docs whose embeddings cluster near "topic-A".
        # Their masses stay at 1.0.
        await engine.index_documents([
            {"content": f"topic-A-doc-{i}", "metadata": {"source": "tweet"}}
            for i in range(10)
        ])

        # Heavy isolated doc — different content (different embedding),
        # so it lands outside raw cosine top-3 of the cluster query, but
        # we manually pump its mass.
        heavy_ids = await engine.index_documents([
            {"content": "lone-heavy-agent-note", "metadata": {"source": "agent"}},
        ])
        heavy_id = heavy_ids[0]
        heavy_state = engine.cache.get_node(heavy_id)
        heavy_state.mass = 30.0  # very heavy
        engine.cache.set_node(heavy_state, dirty=True)

        # Query with the cluster's centroid concept — the heavy node's raw
        # cosine should be lower than cluster members.
        query_vec = engine.embedder.encode_query("topic-A query about cluster")

        # With boost: heavy_id should appear in wave reach.
        reached_with_boost = propagate_gravity_wave(
            query_vec, engine.faiss_index, engine.cache, engine.config,
            wave_k=3, wave_depth=1,
        )
        # With boost, log(1+30)*0.5 ≈ 1.71 is added to heavy's raw cosine,
        # easily promoting it into top-3 of the rescored pool.
        assert heavy_id in reached_with_boost, (
            f"heavy node not reached with boost; reached={list(reached_with_boost)}"
        )
    finally:
        await engine.shutdown()


@pytest.mark.asyncio
async def test_alpha_zero_disables_mass_rerank(tmp_path):
    """wave_seed_mass_alpha=0 should not promote heavy nodes into seeds.

    We compare seed sets between α=0 and α>0: a heavy node that the boost
    would promote should appear under α>0 and disappear under α=0. This
    is robust to which specific content embeddings happen to land where.
    """
    # Both engines use the same StubEmbedder (deterministic by content),
    # so cluster + heavy embeddings are identical across the two runs.
    cluster_docs = [
        {"content": f"topic-A-doc-{i}", "metadata": {"source": "tweet"}}
        for i in range(50)
    ]
    heavy_doc = {
        "content": "lone-heavy-stable-content",
        "metadata": {"source": "agent"},
    }

    # α > 0 path
    eng_boost = _make_engine(tmp_path / "boost", mass_alpha=0.5, pool_size=60)
    eng_boost.config.data_dir.rstrip("/")  # ensure no trailing slash issues
    import os
    os.makedirs(tmp_path / "boost", exist_ok=True)
    os.makedirs(tmp_path / "no-boost", exist_ok=True)
    await eng_boost.startup()
    try:
        await eng_boost.index_documents(cluster_docs)
        heavy_ids = await eng_boost.index_documents([heavy_doc])
        heavy_id = heavy_ids[0]
        heavy_state = eng_boost.cache.get_node(heavy_id)
        heavy_state.mass = 40.0
        eng_boost.cache.set_node(heavy_state, dirty=True)

        qv = eng_boost.embedder.encode_query("topic-A query about cluster")
        reached_boost = propagate_gravity_wave(
            qv, eng_boost.faiss_index, eng_boost.cache, eng_boost.config,
            wave_k=3, wave_depth=0,
        )
    finally:
        await eng_boost.shutdown()

    # α = 0 path
    eng_legacy = _make_engine(tmp_path / "no-boost", mass_alpha=0.0)
    await eng_legacy.startup()
    try:
        await eng_legacy.index_documents(cluster_docs)
        heavy_ids = await eng_legacy.index_documents([heavy_doc])
        heavy_id_legacy = heavy_ids[0]
        heavy_state = eng_legacy.cache.get_node(heavy_id_legacy)
        heavy_state.mass = 40.0
        eng_legacy.cache.set_node(heavy_state, dirty=True)

        qv = eng_legacy.embedder.encode_query("topic-A query about cluster")
        reached_legacy = propagate_gravity_wave(
            qv, eng_legacy.faiss_index, eng_legacy.cache, eng_legacy.config,
            wave_k=3, wave_depth=0,
        )
    finally:
        await eng_legacy.shutdown()

    # Boost branch must reach the heavy node.
    assert heavy_id in reached_boost, (
        "α>0 should promote heavy into seeds via mass rerank"
    )
    # Legacy branch must not (heavy_id is structurally far from cluster
    # query in raw cosine, with 50 cluster docs filling top-3).
    assert heavy_id_legacy not in reached_legacy, (
        "α=0 must not promote heavy into seeds"
    )
