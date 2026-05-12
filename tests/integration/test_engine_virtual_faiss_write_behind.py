"""Virtual FAISS write-behind: cache.displacement edits (from query
attraction, genesis kicks, dream loop) must reach the on-disk virtual
FAISS index on a periodic cadence. Without this, only compact(rebuild_
faiss=True) or startup-when-missing refreshes virtual FAISS, so other
processes' seed pools stay frozen at the displacement state of the last
explicit compact.
"""
from __future__ import annotations

import asyncio
import hashlib
import os

import numpy as np
import pytest

from gaottt.config import GaOTTTConfig
from gaottt.core.engine import GaOTTTEngine
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


def _make_engine(
    tmp_path,
    *,
    virtual_faiss_save_interval: float,
    virtual_enabled: bool = True,
):
    config = GaOTTTConfig(
        data_dir=str(tmp_path),
        db_path=str(tmp_path / "test.db"),
        faiss_index_path=str(tmp_path / "test.faiss"),
        virtual_faiss_index_path=str(tmp_path / "test.virtual.faiss"),
        virtual_faiss_enabled=virtual_enabled,
        virtual_faiss_save_interval_seconds=virtual_faiss_save_interval,
        faiss_save_interval_seconds=0.0,
        genesis_kick_enabled=False,
        dream_enabled=False,
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
async def test_displacement_edit_persists_to_virtual_faiss_on_disk(tmp_path):
    """set_displacement should flip cache.virtual_faiss_dirty; the loop
    must rebuild + save the virtual index to disk within the interval.
    Verified by spinning up a second engine pointed at the same path and
    confirming the virtual index loads with the expected size.
    """
    engine_a = _make_engine(tmp_path, virtual_faiss_save_interval=0.1)
    await engine_a.startup()
    try:
        ids = await engine_a.index_documents([
            {"content": f"virtual-wb-{i}", "metadata": {"source": "agent"}}
            for i in range(4)
        ])
        # index_documents does not currently touch virtual_faiss_dirty
        # (fresh nodes go directly into virtual_faiss_index via .add).
        # We force a displacement edit to trigger the dirty signal.
        target = ids[0]
        push = np.ones(engine_a.config.embedding_dim, dtype=np.float32) * 0.01
        engine_a.cache.set_displacement(target, push)
        assert engine_a.cache.virtual_faiss_dirty is True

        path = engine_a.config.virtual_faiss_index_path
        saved = False
        for _ in range(60):  # up to 6s
            await asyncio.sleep(0.1)
            if (
                os.path.exists(path) and os.path.getsize(path) > 0
                and not engine_a.cache.virtual_faiss_dirty
            ):
                saved = True
                break
        assert saved, (
            "virtual FAISS was not rebuilt/saved within timeout "
            f"(dirty={engine_a.cache.virtual_faiss_dirty}, "
            f"exists={os.path.exists(path)})"
        )

        # Fresh engine should load the persisted virtual index.
        engine_b = _make_engine(tmp_path, virtual_faiss_save_interval=0.0)
        await engine_b.startup()
        try:
            assert engine_b.virtual_faiss_index.size == len(ids)
            for nid in ids:
                assert nid in engine_b.virtual_faiss_index._id_map
        finally:
            await engine_b.shutdown()
    finally:
        await engine_a.shutdown()


@pytest.mark.asyncio
async def test_virtual_save_interval_zero_disables_loop(tmp_path):
    """virtual_faiss_save_interval_seconds=0 should skip the loop entirely
    but still flush the index on shutdown (existing final-save path).
    """
    engine = _make_engine(tmp_path, virtual_faiss_save_interval=0.0)
    await engine.startup()
    try:
        assert engine._virtual_faiss_save_task is None
        ids = await engine.index_documents([
            {"content": "zero-interval-virt-doc", "metadata": {"source": "agent"}},
        ])
        # Mutating displacement still flips the cache flag (the loop just
        # never reads it). Final-save on shutdown saves the index anyway.
        push = np.ones(engine.config.embedding_dim, dtype=np.float32) * 0.01
        engine.cache.set_displacement(ids[0], push)
        assert engine.cache.virtual_faiss_dirty is True
    finally:
        await engine.shutdown()
    assert os.path.exists(engine.config.virtual_faiss_index_path)


@pytest.mark.asyncio
async def test_virtual_faiss_disabled_skips_loop(tmp_path):
    """virtual_faiss_enabled=False — no virtual index, no loop, no save."""
    engine = _make_engine(
        tmp_path,
        virtual_faiss_save_interval=0.1,
        virtual_enabled=False,
    )
    await engine.startup()
    try:
        assert engine.virtual_faiss_index is None
        assert engine._virtual_faiss_save_task is None
    finally:
        await engine.shutdown()
