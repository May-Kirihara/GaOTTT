"""Phase G — Dream Consolidation (Stage 2): a background loop revisits quiet
nodes with synthetic recalls so co-occurrence edges and gravity-field state
accumulate without user query (hippocampal-replay analog).

Tests:
  1. Loop builds co-occurrence edges over time on a fast cadence.
  2. dream_enabled=False keeps the engine functional but skips the loop.
  3. _is_synthetic=True does not increment return_count.
"""
from __future__ import annotations

import asyncio

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


def _make_engine(
    tmp_path,
    *,
    dream_enabled: bool = True,
    dream_interval_seconds: float = 0.1,
    dream_min_idle_seconds: float = 0.0,
    dream_mass_ceiling: float = 1.5,
    genesis_kick_enabled: bool = False,  # isolate dream behaviour
):
    config = GaOTTTConfig(
        data_dir=str(tmp_path),
        db_path=str(tmp_path / "test.db"),
        faiss_index_path=str(tmp_path / "test.faiss"),
        dream_enabled=dream_enabled,
        dream_interval_seconds=dream_interval_seconds,
        dream_batch_size=3,
        dream_mass_ceiling=dream_mass_ceiling,
        dream_min_idle_seconds=dream_min_idle_seconds,
        dream_top_k=5,
        genesis_kick_enabled=genesis_kick_enabled,
        # Phase K (supernova cohort) writes mutual edges at index time,
        # which would confound the dream-loop baseline ("no pre-existing
        # edges"). Dream loop's job is orthogonal — synthetic recalls
        # build edges via Phase B accumulation — so we disable Phase K
        # here to keep the test focused.
        supernova_enabled=False,
        faiss_save_interval_seconds=0.0,
        flush_interval_seconds=0.05,
        edge_threshold=1,  # let edges form quickly in fast tests
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
async def test_dream_loop_builds_cooccurrence_over_time(tmp_path):
    """Quiet nodes revisited by dream ticks should accumulate co-occurrence
    edges. With genesis kick disabled and no user queries, any edges that
    appear must come from the dream loop's synthetic recalls."""
    engine = _make_engine(tmp_path, dream_interval_seconds=0.1)
    await engine.startup()
    try:
        await engine.index_documents([
            {"content": f"dream-corpus-doc-{i}", "metadata": {"source": "agent"}}
            for i in range(8)
        ])
        edges_before = engine.cache.get_all_edges()
        assert len(edges_before) == 0, "fixture failed: pre-dream edges exist"

        # Wait long enough for several dream ticks (~5–10 ticks at 0.1s).
        await asyncio.sleep(1.0)

        edges_after = engine.cache.get_all_edges()
        assert len(edges_after) > 0, (
            "dream loop did not build any co-occurrence edges"
        )
    finally:
        await engine.shutdown()


@pytest.mark.asyncio
async def test_dream_disabled_skips_loop(tmp_path):
    """dream_enabled=False keeps the engine usable but never spawns the
    dream task."""
    engine = _make_engine(tmp_path, dream_enabled=False)
    await engine.startup()
    try:
        assert engine._dream_task is None
        await engine.index_documents([
            {"content": "no-dream-doc", "metadata": {"source": "agent"}},
        ])
    finally:
        await engine.shutdown()


@pytest.mark.asyncio
async def test_synthetic_recall_does_not_increment_return_count(tmp_path):
    """_is_synthetic=True must skip return_count bumps so background
    revisits don't trip presentation saturation."""
    engine = _make_engine(
        tmp_path, dream_enabled=False, genesis_kick_enabled=False,
    )
    await engine.startup()
    try:
        ids = await engine.index_documents([
            {"content": "alpha-doc", "metadata": {"source": "agent"}},
            {"content": "beta-doc", "metadata": {"source": "agent"}},
            {"content": "gamma-doc", "metadata": {"source": "agent"}},
        ])
        # Normal recall — return_count should rise for hits (then decay
        # slightly via habituation recovery within the same call, so
        # ~0.99 after one bump).
        await engine.query(text="alpha-doc", top_k=3)
        rc_after_user = {
            nid: engine.cache.get_node(nid).return_count for nid in ids
        }
        assert max(rc_after_user.values()) > 0.5, (
            "fixture failed: no return_count rise after a real recall"
        )

        # Synthetic recall — return_count should NOT rise further
        await engine._query_internal(
            text="alpha-doc", top_k=3, wave_depth=None, wave_k=None,
            _is_synthetic=True,
        )
        rc_after_synthetic = {
            nid: engine.cache.get_node(nid).return_count for nid in ids
        }
        for nid in ids:
            # Habituation recovery may shave off ~1% per tick; allow tiny slack.
            assert rc_after_synthetic[nid] <= rc_after_user[nid] + 1e-6, (
                f"_is_synthetic=True increased return_count for {nid}: "
                f"{rc_after_user[nid]} -> {rc_after_synthetic[nid]}"
            )
    finally:
        await engine.shutdown()
