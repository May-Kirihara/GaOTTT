"""Hardening Stage 1 — concurrency regression suite (C3 / C4).

The pre-existing test suite is all single-process and serial, so the
concurrency / persistence bugs found in the 2026-05-18 code review never
surfaced. This file is the regression base the doc
(Plans-Hardening-Concurrency-Persistence) refers to.

  C3 — explore() must not monkey-patch the shared config.gamma across an
       await; a concurrent recall reading config.gamma during that await
       (the synchronous _update_simulation temperature step) would compute
       its field with the inflated value, and concurrent explores could
       leave gamma permanently drifted. This is a real cross-recall
       corruption (verified). Fix: per-call gamma_override.
  C4 — engine.reset() must invalidate the prefetch cache (and mark virtual
       FAISS dirty), like every other destructive op.

  C2 (NOT a defect — no test): the original review claimed concurrent
  recalls lose/double mass gradient steps. Investigation showed the recall
  mutation phase (_update_simulation + _update_cooccurrence, both sync `def`
  with zero `await`) runs atomically under asyncio's cooperative scheduler
  and re-reads each NodeState fresh, so concurrent recalls cannot lose or
  double a gradient step. A guarding test passed identically with and
  without a lock — confirming there is nothing to fix. No lock was added
  (it would only serialize recall DB I/O on the hot path for no benefit).
"""
from __future__ import annotations

import asyncio
import hashlib

import numpy as np
import pytest

from gaottt.config import GaOTTTConfig
from gaottt.core.engine import GaOTTTEngine
from gaottt.index.faiss_index import FaissIndex
from gaottt.services.memory import explore as explore_service
from gaottt.store.cache import CacheLayer
from gaottt.store.sqlite_store import SqliteStore


class StubEmbedder:
    """Deterministic embeddings — no GPU/network.

    Stable cross-process seed (hashlib, not builtin ``hash`` which is
    PYTHONHASHSEED-salted) so the suite is reproducible run-to-run. These
    tests don't assert on wave geometry, so a shared base component isn't
    needed (cf. test_engine_query_kick.py), only determinism.
    """

    def __init__(self, dim: int = 768):
        self.dim = dim

    def encode_documents(self, contents):
        return np.array([self._embed(c) for c in contents], dtype=np.float32)

    def encode_query(self, text):
        return self._embed(text).reshape(1, -1).astype(np.float32)

    def _embed(self, text: str) -> np.ndarray:
        seed = int.from_bytes(hashlib.sha256(text.encode()).digest()[:8], "big")
        rng = np.random.default_rng(seed)
        v = rng.standard_normal(self.dim).astype(np.float32)
        v /= np.linalg.norm(v) + 1e-9
        return v


def _make_engine(tmp_path) -> GaOTTTEngine:
    tmp_path.mkdir(parents=True, exist_ok=True)
    config = GaOTTTConfig(
        data_dir=str(tmp_path),
        db_path=str(tmp_path / "test.db"),
        faiss_index_path=str(tmp_path / "test.faiss"),
        # Make the gradient step observable and suppress background noise so
        # the only thing moving mass is the recalls under test.
        query_kick_enabled=True,
        query_kick_strength=0.02,
        genesis_kick_enabled=False,
        dream_enabled=False,
        faiss_save_interval_seconds=0.0,
        virtual_faiss_save_interval_seconds=0.0,
        flush_interval_seconds=0.05,
    )
    embedder = StubEmbedder(dim=config.embedding_dim)
    return GaOTTTEngine(
        config=config,
        embedder=embedder,
        faiss_index=FaissIndex(dimension=config.embedding_dim),
        cache=CacheLayer(
            flush_interval=config.flush_interval_seconds,
            flush_threshold=config.flush_threshold,
        ),
        store=SqliteStore(db_path=config.db_path),
    )


async def _seed(engine: GaOTTTEngine, n: int = 6) -> None:
    await engine.index_documents(
        [{"content": f"doc-{i}", "metadata": {"source": "agent"}} for i in range(n)]
    )


@pytest.mark.asyncio
async def test_c3_explore_does_not_mutate_shared_gamma(tmp_path):
    """Concurrent explore + recall must leave config.gamma untouched.
    The old code monkey-patched config.gamma across an await; an interleaved
    coroutine could read or 'restore' the inflated value, permanently
    corrupting it.
    """
    engine = _make_engine(tmp_path)
    await engine.startup()
    try:
        await _seed(engine)
        original_gamma = engine.config.gamma

        async def _explore():
            return await explore_service(
                engine, query="doc-2", diversity=0.7, top_k=3, auto_route=False
            )

        async def _recall():
            return await engine.query(text="doc-3", top_k=3)

        results = await asyncio.gather(
            _explore(), _recall(), _explore(), _recall(), _explore()
        )

        assert engine.config.gamma == original_gamma, (
            "explore mutated the shared config.gamma (C3 regression)"
        )
        # explore still works and returns its widened-temperature results
        assert results[0].count >= 1
    finally:
        await engine.shutdown()


@pytest.mark.asyncio
async def test_c4_reset_invalidates_prefetch_cache(tmp_path):
    """engine.reset() must clear the prefetch cache and mark virtual FAISS
    dirty — otherwise a cached (text, k) recall keeps serving the pre-reset
    ranked list for up to prefetch_ttl_seconds."""
    engine = _make_engine(tmp_path)
    await engine.startup()
    try:
        await _seed(engine)
        q = "doc-1"

        # Populate the prefetch cache via the use_cache=True write path.
        await engine.query(text=q, top_k=3, use_cache=True)
        assert engine.prefetch_cache.get(q, 3) is not None, (
            "test setup: query(use_cache=True) should populate the cache"
        )

        engine.cache.virtual_faiss_dirty = False  # isolate the reset's effect
        await engine.reset()

        assert engine.prefetch_cache.get(q, 3) is None, (
            "reset() did not invalidate the prefetch cache (C4 regression)"
        )
        assert engine.cache.virtual_faiss_dirty is True, (
            "reset() did not mark virtual FAISS dirty (C4 regression)"
        )
    finally:
        await engine.shutdown()


@pytest.mark.asyncio
async def test_h1_compact_rebuild_swaps_index_atomically(tmp_path):
    """_rebuild_faiss_index must build a fresh index and swap the
    reference in one atomic assignment — never mutate the live index to
    empty. A concurrent recall that already captured the old reference
    still searches a full, valid index, so there is no ntotal==0 window.
    Under the old reset()+add() the *same* object was emptied mid-rebuild,
    so any recall in that window got a silent empty seed pool.
    """
    engine = _make_engine(tmp_path)
    await engine.startup()
    try:
        await _seed(engine, n=8)
        old = engine.faiss_index
        old_size = old.size
        assert old_size == 8

        await engine._rebuild_faiss_index()

        assert engine.faiss_index is not old, (
            "rebuild must swap a fresh index, not mutate in place (H1)"
        )
        assert old.size == old_size, (
            "old index was emptied mid-rebuild — a concurrent recall "
            "holding it would have seen an empty seed pool (H1 regression)"
        )
        assert engine.faiss_index.size == old_size, "new index not fully populated"
        res = await engine.query(text="doc-1", top_k=3)
        assert len(res) >= 1, "recall must work against the swapped-in index"
    finally:
        await engine.shutdown()


@pytest.mark.asyncio
async def test_concurrent_nonpassive_recalls_no_corruption(tmp_path):
    """Concurrent non-passive recalls each apply their gradient step without
    corrupting shared state. Formalizes the C2 finding (mutation phase is
    atomic under cooperative scheduling) + C3 (shared gamma untouched) as a
    live guard for the 2026-06-01 concurrency hardening.
    """
    engine = _make_engine(tmp_path)
    await engine.startup()
    try:
        await _seed(engine, n=8)
        original_gamma = engine.config.gamma

        results = await asyncio.gather(
            engine.query(text="doc-1", top_k=3),
            engine.query(text="doc-2", top_k=3),
            engine.query(text="doc-1", top_k=3),
            engine.query(text="doc-3", top_k=3),
        )

        assert all(len(r) >= 1 for r in results), "every concurrent recall returns"
        assert engine.config.gamma == original_gamma, "shared gamma must be untouched"
        # No NaN/inf mass from interleaved gradient updates.
        for state in engine.cache.node_cache.values():
            assert np.isfinite(state.mass) and state.mass > 0
    finally:
        await engine.shutdown()


@pytest.mark.asyncio
async def test_concurrent_recall_plus_writer(tmp_path):
    """A writer (index_documents) running concurrently with recalls must
    leave the index consistent and the recalls valid — exercises add() on
    the event loop racing the recall read path."""
    engine = _make_engine(tmp_path)
    await engine.startup()
    try:
        await _seed(engine, n=6)
        before = engine.faiss_index.size

        results = await asyncio.gather(
            engine.query(text="doc-1", top_k=3),
            engine.index_documents(
                [{"content": f"new-{i}", "metadata": {"source": "agent"}}
                 for i in range(4)]
            ),
            engine.query(text="doc-2", top_k=3),
        )

        assert engine.faiss_index.size == before + 4, "writer added all 4 vectors"
        assert len(results[0]) >= 1 and len(results[2]) >= 1, "recalls still valid"
    finally:
        await engine.shutdown()


@pytest.mark.asyncio
async def test_faiss_save_during_add_no_corruption(tmp_path):
    """The FaissIndex threading.Lock must keep a to_thread save (worker
    thread) from racing a synchronous add() on the event loop — the one
    genuine cross-thread race an asyncio lock cannot cover. After hammering
    both concurrently the on-disk index must reload cleanly with a
    consistent id-map (the H4 invariant: ntotal == len(id_map)).
    """
    engine = _make_engine(tmp_path)
    await engine.startup()
    try:
        await _seed(engine, n=10)
        path = engine.config.faiss_index_path

        for r in range(5):
            await asyncio.gather(
                asyncio.to_thread(engine.faiss_index.save, path),
                engine.index_documents(
                    [{"content": f"x-{r}-{j}", "metadata": {"source": "agent"}}
                     for j in range(3)]
                ),
            )

        reloaded = FaissIndex(dimension=engine.config.embedding_dim)
        reloaded.load(path)
        assert reloaded.size > 0, "on-disk index must be non-empty + loadable"
        assert reloaded.size == len(reloaded._id_map), (
            "index/id-map size mismatch — save raced a concurrent add()"
        )
    finally:
        await engine.shutdown()
