"""Restore must route displacement/velocity through cache setters so that
virtual_faiss_dirty and dirty_displacements / dirty_velocities are set
correctly (the setters maintain those flags; direct dict assignment bypassed
them, making the manual virtual_faiss_dirty = True compensaton fragile).
"""
from __future__ import annotations

import hashlib

import numpy as np
import pytest

from gaottt.config import GaOTTTConfig
from gaottt.core.engine import GaOTTTEngine
from gaottt.index.faiss_index import FaissIndex
from gaottt.store.cache import CacheLayer
from gaottt.store.sqlite_store import SqliteStore


class StubEmbedder:
    def __init__(self, dimension: int = 32):
        self._dimension = dimension
        self._token_cache: dict[str, np.ndarray] = {}

    @property
    def dimension(self) -> int:
        return self._dimension

    def _token_vec(self, token: str) -> np.ndarray:
        cached = self._token_cache.get(token)
        if cached is not None:
            return cached
        seed = int.from_bytes(hashlib.md5(token.encode()).digest()[:8], "big")
        rng = np.random.default_rng(seed)
        v = rng.standard_normal(self._dimension).astype(np.float32)
        v /= np.linalg.norm(v) + 1e-9
        self._token_cache[token] = v
        return v

    def _embed(self, text: str) -> np.ndarray:
        tokens = [t.lower() for t in text.split() if t.strip()]
        if not tokens:
            return np.zeros(self._dimension, dtype=np.float32)
        v = sum(self._token_vec(t) for t in tokens)
        norm = np.linalg.norm(v)
        return (v / norm).astype(np.float32) if norm > 0 else v.astype(np.float32)

    def encode_documents(self, texts: list[str]) -> np.ndarray:
        return np.stack([self._embed(t) for t in texts])

    def encode_query(self, text: str) -> np.ndarray:
        return self._embed(text).reshape(1, -1)


@pytest.fixture
async def engine(tmp_path):
    cfg = GaOTTTConfig(
        embedding_dim=32,
        data_dir=str(tmp_path),
        db_path=str(tmp_path / "test.db"),
        faiss_index_path=str(tmp_path / "test.faiss"),
        virtual_faiss_index_path=str(tmp_path / "test.virtual.faiss"),
        virtual_faiss_enabled=True,
        virtual_faiss_save_interval_seconds=0.0,
        flush_interval_seconds=999.0,
        wave_initial_k=3,
        wave_max_depth=1,
    )
    eng = GaOTTTEngine(
        config=cfg,
        embedder=StubEmbedder(dimension=32),
        faiss_index=FaissIndex(dimension=32),
        cache=CacheLayer(flush_interval=999.0),
        store=SqliteStore(db_path=cfg.db_path),
        virtual_faiss_index=FaissIndex(dimension=32),
    )
    await eng.startup()
    try:
        yield eng
    finally:
        await eng.shutdown()


@pytest.mark.asyncio
async def test_restore_sets_virtual_faiss_dirty(engine):
    ids = await engine.index_documents([
        {"content": "restore dirty check node", "metadata": {"source": "user"}},
    ])
    assert len(ids) == 1
    nid = ids[0]

    # Give the node a displacement so restore has something to reload.
    disp = np.ones(32, dtype=np.float32) * 0.05
    engine.cache.set_displacement(nid, disp)
    # Flush to store so restore can reload from there.
    await engine.cache.flush_to_store(engine.store)

    # Archive → clears from cache.
    await engine.archive([nid])
    assert engine.cache.get_displacement(nid) is None
    engine.cache.virtual_faiss_dirty = False

    # Restore → should go through setters → sets dirty flags.
    affected = await engine.restore([nid])
    assert affected == 1
    assert engine.cache.virtual_faiss_dirty is True
    assert nid in engine.cache.dirty_displacements


@pytest.mark.asyncio
async def test_restore_sets_dirty_velocity(engine):
    ids = await engine.index_documents([
        {"content": "restore velocity check", "metadata": {"source": "user"}},
    ])
    nid = ids[0]

    vel = np.ones(32, dtype=np.float32) * 0.02
    engine.cache.set_velocity(nid, vel)
    await engine.cache.flush_to_store(engine.store)

    await engine.archive([nid])
    assert engine.cache.get_velocity(nid) is None

    affected = await engine.restore([nid])
    assert affected == 1
    assert nid in engine.cache.dirty_velocities
