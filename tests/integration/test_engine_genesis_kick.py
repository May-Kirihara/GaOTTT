"""Phase G — Genesis kick: brand-new nodes enter the gravity field with
non-zero orbital state derived from a one-step Newtonian interaction with
their heaviest neighbors. Without this they would land "naked" (mass=1,
displacement=0, velocity=0) and lose recall ranking to established clusters.

These tests verify:
  1. Cache state for a fresh node is seeded when neighbors exist.
  2. genesis_kick_enabled=False preserves the legacy zero-state behaviour.
  3. The first-ever document in an empty DB does not crash the kick path.
"""
from __future__ import annotations

import numpy as np
import pytest

from gaottt.config import GaOTTTConfig
from gaottt.core.engine import GaOTTTEngine
from gaottt.index.faiss_index import FaissIndex
from gaottt.store.cache import CacheLayer
from gaottt.store.sqlite_store import SqliteStore


class StubEmbedder:
    """Deterministic token-based embeddings — no GPU/network."""

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


def _make_engine(tmp_path, *, kick_enabled: bool):
    config = GaOTTTConfig(
        data_dir=str(tmp_path),
        db_path=str(tmp_path / "test.db"),
        faiss_index_path=str(tmp_path / "test.faiss"),
        genesis_kick_enabled=kick_enabled,
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
async def test_genesis_kick_seeds_displacement_velocity_mass(tmp_path):
    """A freshly-indexed node should have non-zero displacement, velocity,
    and mass > 1.0 after index_documents() when heavy neighbors exist."""
    engine = _make_engine(tmp_path, kick_enabled=True)
    await engine.startup()
    try:
        cluster_ids = await engine.index_documents([
            {"content": f"cluster-doc-{i}", "metadata": {"source": "agent"}}
            for i in range(10)
        ])
        # Pump masses by recalling repeatedly so the cluster has > 1 mass.
        for _ in range(5):
            await engine.query(text="cluster-doc-0", top_k=10)
        max_cluster_mass = max(
            engine.cache.get_node(cid).mass for cid in cluster_ids
        )
        assert max_cluster_mass > 1.0, (
            "fixture failed: cluster did not accumulate mass"
        )

        new_ids = await engine.index_documents([
            {"content": "fresh-genesis-doc", "metadata": {"source": "agent"}},
        ])
        assert len(new_ids) == 1
        new_id = new_ids[0]

        disp = engine.cache.get_displacement(new_id)
        vel = engine.cache.get_velocity(new_id)
        state = engine.cache.get_node(new_id)

        assert disp is not None
        assert float(np.linalg.norm(disp)) > 0.0, (
            "genesis kick did not seed displacement"
        )
        assert vel is not None
        assert float(np.linalg.norm(vel)) > 0.0, (
            "genesis kick did not seed velocity"
        )
        assert state is not None and state.mass > 1.0, (
            f"genesis kick did not boost mass (mass={state.mass if state else None})"
        )
    finally:
        await engine.shutdown()


@pytest.mark.asyncio
async def test_genesis_kick_disabled_keeps_legacy_zero_state(tmp_path):
    """With genesis_kick_enabled=False, fresh nodes retain zero displacement /
    velocity and mass=1.0, matching pre-Phase-G behavior."""
    engine = _make_engine(tmp_path, kick_enabled=False)
    await engine.startup()
    try:
        await engine.index_documents([
            {"content": f"cluster-{i}", "metadata": {"source": "agent"}}
            for i in range(5)
        ])
        new_ids = await engine.index_documents([
            {"content": "fresh-no-kick", "metadata": {"source": "agent"}},
        ])
        new_id = new_ids[0]

        disp = engine.cache.get_displacement(new_id)
        vel = engine.cache.get_velocity(new_id)
        state = engine.cache.get_node(new_id)

        # Legacy: cache may not even hold displacement / velocity entries.
        assert disp is None or float(np.linalg.norm(disp)) == 0.0
        assert vel is None or float(np.linalg.norm(vel)) == 0.0
        assert state is not None and state.mass == 1.0
    finally:
        await engine.shutdown()


@pytest.mark.asyncio
async def test_genesis_kick_empty_db_safe(tmp_path):
    """First-ever document in an empty DB has no neighbors; the kick path
    must not crash and should leave the new node in a sensible state."""
    engine = _make_engine(tmp_path, kick_enabled=True)
    await engine.startup()
    try:
        new_ids = await engine.index_documents([
            {"content": "very-first-doc", "metadata": {"source": "agent"}},
        ])
        assert len(new_ids) == 1
        new_id = new_ids[0]
        state = engine.cache.get_node(new_id)
        assert state is not None
        # No neighbors → no kick → mass stays at 1.0
        assert state.mass == 1.0
    finally:
        await engine.shutdown()
