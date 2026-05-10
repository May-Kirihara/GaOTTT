"""Phase H Stage 3 — Density-aware dynamic wave_k.

The seed step looks at top-N raw cosine scores. If they fall off sharply
(sparse region), we expand effective_k up to wave_initial_k_max so the
wave can reach further. If they stay tightly packed (dense cluster),
initial_k is enough.

Tests:
  1. Sparse query landscape expands seeds beyond initial_k.
  2. Dense query landscape keeps seeds at initial_k.
  3. dynamic_k_enabled=False keeps the previous Stage 1/legacy behaviour.
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
    """Deterministic content-based embedder.

    For tokens prefixed `cluster-` we collapse to a shared anchor vector
    plus tiny perturbation, producing tightly packed cosine. For
    `scatter-` tokens we use full hash randomness, giving a sparse top-N
    drop-off when the query lands among them.
    """

    def __init__(self, dim: int = 768):
        self.dim = dim

    def encode_documents(self, contents):
        return np.array([self._embed(c) for c in contents], dtype=np.float32)

    def encode_query(self, text):
        return self._embed(text).reshape(1, -1).astype(np.float32)

    def _embed(self, text: str) -> np.ndarray:
        if text.startswith("cluster-"):
            anchor_seed = int.from_bytes(
                hashlib.md5(b"cluster-anchor").digest()[:4], "big"
            )
            anchor_rng = np.random.default_rng(anchor_seed)
            anchor = anchor_rng.standard_normal(self.dim).astype(np.float32)
            perturb_seed = int.from_bytes(
                hashlib.md5(text.encode()).digest()[:4], "big"
            )
            perturb_rng = np.random.default_rng(perturb_seed)
            v = anchor + 0.02 * perturb_rng.standard_normal(self.dim).astype(np.float32)
        else:
            seed = int.from_bytes(
                hashlib.md5(text.encode()).digest()[:4], "big"
            )
            rng = np.random.default_rng(seed)
            v = rng.standard_normal(self.dim).astype(np.float32)
        v /= np.linalg.norm(v) + 1e-9
        return v.astype(np.float32)


def _make_engine(tmp_path, *, dynamic: bool):
    config = GaOTTTConfig(
        data_dir=str(tmp_path),
        db_path=str(tmp_path / "test.db"),
        faiss_index_path=str(tmp_path / "test.faiss"),
        wave_initial_k=3,
        wave_seed_mass_alpha=0.1,
        wave_seed_pool_size=50,
        wave_dynamic_k_enabled=dynamic,
        wave_density_window=10,
        wave_density_threshold=0.95,
        wave_initial_k_max=30,
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
async def test_sparse_landscape_expands_seeds(tmp_path):
    """When the top-N cosine scores fall off sharply, dynamic wave_k
    should expand the seed count above initial_k."""
    engine = _make_engine(tmp_path, dynamic=True)
    await engine.startup()
    try:
        # 50 randomly-scattered docs. Query against an unrelated string
        # → top-1 may be moderate but top-N falls off (sparse).
        await engine.index_documents([
            {"content": f"scatter-doc-{i}", "metadata": {"source": "agent"}}
            for i in range(50)
        ])
        qv = engine.embedder.encode_query("scatter-query-far-from-everything")
        reached = propagate_gravity_wave(
            qv, engine.faiss_index, engine.cache, engine.config,
            wave_k=3, wave_depth=0,
        )
        # initial_k=3 would have returned exactly 3. Dynamic expansion
        # should have grown that beyond initial_k.
        assert len(reached) > 3, (
            f"sparse landscape did not expand seeds; reached={len(reached)}"
        )
    finally:
        await engine.shutdown()


@pytest.mark.asyncio
async def test_dense_landscape_keeps_initial_k(tmp_path):
    """When top-N cosine scores are tightly packed (cluster), dynamic
    expansion should stay at initial_k."""
    engine = _make_engine(tmp_path, dynamic=True)
    await engine.startup()
    try:
        # 50 cluster docs all packed near a shared anchor.
        await engine.index_documents([
            {"content": f"cluster-doc-{i}", "metadata": {"source": "agent"}}
            for i in range(50)
        ])
        qv = engine.embedder.encode_query("cluster-query-near-anchor")
        reached = propagate_gravity_wave(
            qv, engine.faiss_index, engine.cache, engine.config,
            wave_k=3, wave_depth=0,
        )
        # depth=0, initial_k=3, dense → exactly 3
        assert len(reached) == 3, (
            f"dense landscape unexpectedly expanded; reached={len(reached)}"
        )
    finally:
        await engine.shutdown()


@pytest.mark.asyncio
async def test_dynamic_disabled_keeps_initial_k(tmp_path):
    """wave_dynamic_k_enabled=False should never expand beyond initial_k,
    matching pre-Stage-3 behaviour even on sparse landscapes."""
    engine = _make_engine(tmp_path, dynamic=False)
    await engine.startup()
    try:
        await engine.index_documents([
            {"content": f"scatter-doc-{i}", "metadata": {"source": "agent"}}
            for i in range(50)
        ])
        qv = engine.embedder.encode_query("scatter-query-far-from-everything")
        reached = propagate_gravity_wave(
            qv, engine.faiss_index, engine.cache, engine.config,
            wave_k=3, wave_depth=0,
        )
        assert len(reached) == 3, (
            f"dynamic_k_enabled=False should not expand; reached={len(reached)}"
        )
    finally:
        await engine.shutdown()
