"""Phase H Stage 2 — Source-aware seed filtering.

When ``source_filter`` is set, the wave seed step pulls a wider FAISS pool
and keeps only members whose ``cache.source_by_id`` matches. This is the
only way sparse classes (agent / value / commitment) reliably enter the
wave on corpus-heavy DBs where they lose every raw cosine contest to
dense Twitter / book clusters.

Tests:
  1. agent doc that's far in raw cosine still becomes a seed under
     source_filter=["agent"] thanks to the wider pool + filter.
  2. source_filter=None falls back to legacy / Stage 1 behaviour.
  3. cache.source_by_id is populated by index_documents.
  4. cache.source_by_id is populated by load_from_store on engine restart.
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
        seed = abs(hash(text)) & 0xFFFFFFFF
        rng = np.random.default_rng(seed)
        v = rng.standard_normal(self.dim).astype(np.float32)
        v /= np.linalg.norm(v) + 1e-9
        return v


def _make_engine(tmp_path):
    config = GaOTTTConfig(
        data_dir=str(tmp_path),
        db_path=str(tmp_path / "test.db"),
        faiss_index_path=str(tmp_path / "test.faiss"),
        wave_initial_k=3,
        wave_k_with_filter=50,
        wave_seed_mass_alpha=0.0,  # isolate the source-filter path
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
async def test_source_filter_pulls_sparse_agent_into_seeds(tmp_path):
    """An agent doc that loses raw cosine top-3 to a dense tweet cluster
    should still be reachable via source_filter=['agent']."""
    engine = _make_engine(tmp_path)
    await engine.startup()
    try:
        await engine.index_documents([
            {"content": f"dense-tweet-cluster-{i}",
             "metadata": {"source": "tweet"}}
            for i in range(20)
        ])
        agent_ids = await engine.index_documents([
            {"content": "lone-agent-note-far-from-cluster",
             "metadata": {"source": "agent"}},
        ])
        agent_id = agent_ids[0]

        query_vec = engine.embedder.encode_query("dense-tweet-cluster query")

        # Without source_filter, agent_id is unlikely to be in top-3.
        # With source_filter=['agent'], it must be reachable: it is the
        # only agent node in the entire index.
        reached_with_sf = propagate_gravity_wave(
            query_vec, engine.faiss_index, engine.cache, engine.config,
            wave_k=3, wave_depth=0,
            source_filter=["agent"],
        )
        assert agent_id in reached_with_sf, (
            f"agent doc not reached with source_filter; "
            f"reached={list(reached_with_sf)}"
        )
    finally:
        await engine.shutdown()


@pytest.mark.asyncio
async def test_source_filter_none_keeps_legacy_behaviour(tmp_path):
    """source_filter=None should not invoke the source-aware path."""
    engine = _make_engine(tmp_path)
    await engine.startup()
    try:
        await engine.index_documents([
            {"content": f"doc-{i}", "metadata": {"source": "agent"}}
            for i in range(5)
        ])
        query_vec = engine.embedder.encode_query("doc-0")

        # With α=0, no source_filter, this hits the legacy raw cosine top-K
        # branch and returns whatever FAISS gives.
        reached_legacy = propagate_gravity_wave(
            query_vec, engine.faiss_index, engine.cache, engine.config,
            wave_k=3, wave_depth=0,
        )
        assert len(reached_legacy) <= 3
    finally:
        await engine.shutdown()


@pytest.mark.asyncio
async def test_index_documents_populates_source_by_id(tmp_path):
    """The cache map gets the source set when documents are indexed."""
    engine = _make_engine(tmp_path)
    await engine.startup()
    try:
        ids = await engine.index_documents([
            {"content": "with-source", "metadata": {"source": "agent"}},
            {"content": "without-source", "metadata": {}},
            {"content": "no-metadata"},
        ])
        assert engine.cache.get_source(ids[0]) == "agent"
        assert engine.cache.get_source(ids[1]) is None
        assert engine.cache.get_source(ids[2]) is None
    finally:
        await engine.shutdown()


@pytest.mark.asyncio
async def test_source_by_id_survives_engine_restart(tmp_path):
    """A fresh engine started against the same DB should re-populate
    source_by_id from the persisted documents."""
    engine_a = _make_engine(tmp_path)
    await engine_a.startup()
    try:
        ids = await engine_a.index_documents([
            {"content": "persisted-agent", "metadata": {"source": "agent"}},
            {"content": "persisted-tweet", "metadata": {"source": "tweet"}},
        ])
    finally:
        await engine_a.shutdown()

    engine_b = _make_engine(tmp_path)
    await engine_b.startup()
    try:
        assert engine_b.cache.get_source(ids[0]) == "agent"
        assert engine_b.cache.get_source(ids[1]) == "tweet"
    finally:
        await engine_b.shutdown()
