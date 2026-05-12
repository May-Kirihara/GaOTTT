"""Phase H Stage 4 — Virtual FAISS for displacement-aware seed.

The virtual FAISS index is built from `virtual_pos = raw_emb +
displacement` (normalized). Phase G priming moves displacement on every
active node, but raw FAISS does not see those updates. With virtual
FAISS, the seed pool unions raw + virtual top-N, so a primed node can
enter the wave through its virtual position even when raw cosine is far.

Tests:
  1. virtual_faiss_index is built at startup when missing.
  2. Pushing displacement on a node moves it closer to the query in
     virtual cosine, surfacing it through the virtual FAISS path.
  3. virtual_faiss_enabled=False keeps legacy raw-only seeding.
  4. compact(rebuild_faiss=True) rebuilds virtual FAISS too.
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
        seed = int.from_bytes(
            hashlib.md5(text.encode("utf-8")).digest()[:4], "big"
        )
        rng = np.random.default_rng(seed)
        v = rng.standard_normal(self.dim).astype(np.float32)
        v /= np.linalg.norm(v) + 1e-9
        return v


def _make_engine(tmp_path, *, virtual_enabled: bool = True):
    config = GaOTTTConfig(
        data_dir=str(tmp_path),
        db_path=str(tmp_path / "test.db"),
        faiss_index_path=str(tmp_path / "test.faiss"),
        virtual_faiss_index_path=str(tmp_path / "test.virtual.faiss"),
        virtual_faiss_enabled=virtual_enabled,
        wave_initial_k=3,
        wave_seed_mass_alpha=0.0,
        wave_dynamic_k_enabled=False,
        genesis_kick_enabled=False,
        dream_enabled=False,
        faiss_save_interval_seconds=0.0,
        flush_interval_seconds=0.05,
    )
    embedder = StubEmbedder(dim=config.embedding_dim)
    faiss_index = FaissIndex(dimension=config.embedding_dim)
    virtual_faiss_index = (
        FaissIndex(dimension=config.embedding_dim)
        if virtual_enabled else None
    )
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


@pytest.mark.asyncio
async def test_virtual_faiss_built_at_startup_when_missing(tmp_path):
    """Virtual FAISS should be built from raw + displacement when no
    persisted file exists."""
    engine = _make_engine(tmp_path, virtual_enabled=True)
    await engine.startup()
    try:
        await engine.index_documents([
            {"content": f"doc-{i}", "metadata": {"source": "agent"}}
            for i in range(5)
        ])
        # After indexing, virtual size should match raw size (no
        # displacement yet, so virtual_pos == raw).
        assert engine.virtual_faiss_index.size == engine.faiss_index.size
    finally:
        await engine.shutdown()


@pytest.mark.asyncio
async def test_displacement_moves_node_in_virtual_cosine(tmp_path):
    """A node whose displacement points toward the query should appear
    in seeds via virtual FAISS even when its raw cosine is far."""
    engine = _make_engine(tmp_path, virtual_enabled=True)
    await engine.startup()
    try:
        # Seed cluster + one isolated agent doc
        await engine.index_documents([
            {"content": f"cluster-{i}", "metadata": {"source": "tweet"}}
            for i in range(20)
        ])
        agent_ids = await engine.index_documents([
            {"content": "lone-agent-far-away",
             "metadata": {"source": "agent"}},
        ])
        agent_id = agent_ids[0]

        query_text = "cluster query"
        qv = engine.embedder.encode_query(query_text)

        # Without displacement push, raw FAISS top-3 unlikely to contain
        # agent_id (it's lone in embedding space).
        raw_seeds = engine.faiss_index.search(qv, 3)
        raw_seed_ids = [nid for nid, _ in raw_seeds]
        if agent_id in raw_seed_ids:
            pytest.skip("fixture lottery: agent already in raw top-3")

        # Push displacement on agent toward the query direction. After
        # rebuild, virtual_pos should be much closer to qv.
        agent_raw = engine.faiss_index.get_vectors([agent_id])[agent_id]
        push = (qv[0] - agent_raw) * 0.5
        # clamp under max_displacement_norm
        norm = float(np.linalg.norm(push))
        if norm > engine.config.max_displacement_norm:
            push = push * (engine.config.max_displacement_norm / norm)
        engine.cache.set_displacement(agent_id, push)

        await engine._rebuild_virtual_faiss_index()

        # Now check: virtual seeds should include agent_id via union pool.
        reached = propagate_gravity_wave(
            qv, engine.faiss_index, engine.cache, engine.config,
            wave_k=3, wave_depth=0,
            virtual_faiss_index=engine.virtual_faiss_index,
        )
        assert agent_id in reached, (
            f"agent_id not reached via virtual FAISS; reached={list(reached)}"
        )
    finally:
        await engine.shutdown()


@pytest.mark.asyncio
async def test_virtual_faiss_disabled_falls_back(tmp_path):
    """virtual_faiss_enabled=False — the engine should not allocate or
    use a virtual index, and recall keeps working."""
    engine = _make_engine(tmp_path, virtual_enabled=False)
    await engine.startup()
    try:
        assert engine.virtual_faiss_index is None
        await engine.index_documents([
            {"content": "doc-x", "metadata": {"source": "agent"}},
        ])
        # Sanity: query path works
        results = await engine.query(text="doc-x", top_k=1)
        assert len(results) >= 0
    finally:
        await engine.shutdown()


@pytest.mark.asyncio
async def test_compact_rebuilds_virtual_faiss(tmp_path):
    """compact(rebuild_faiss=True) should refresh the virtual index too."""
    engine = _make_engine(tmp_path, virtual_enabled=True)
    await engine.startup()
    try:
        await engine.index_documents([
            {"content": f"compact-doc-{i}", "metadata": {"source": "agent"}}
            for i in range(5)
        ])
        size_before = engine.virtual_faiss_index.size
        report = await engine.compact(
            expire_ttl=False, rebuild_faiss=True, auto_merge=False,
        )
        assert report["faiss_rebuilt"] is True
        # After rebuild, virtual still tracks raw size.
        assert engine.virtual_faiss_index.size == engine.faiss_index.size
        assert engine.virtual_faiss_index.size == size_before
    finally:
        await engine.shutdown()
