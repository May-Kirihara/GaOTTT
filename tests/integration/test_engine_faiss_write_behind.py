"""FAISS write-behind: new vectors persist on a periodic cadence so other
processes' startup() can see them without the writing process having to
shutdown() first. This guards against the multi-process invisibility bug
discovered when MCP servers ran indefinitely without saving.
"""
from __future__ import annotations

import asyncio
import os

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


def _ids_line_count(ids_path: str) -> int:
    """Non-empty line count of a FAISS ``.ids`` sidecar (0 if absent).

    ``save()`` os.replace()s the ``.faiss`` index file *before* the ``.ids``
    sidecar (with an fsync between), so a reader that gates only on the
    ``.faiss`` file can observe a half-published pair — ``.faiss`` committed,
    ``.ids`` not yet — and ``FaissIndex.load()``'s id-map/ntotal mismatch guard
    then resets the index to empty. Tests poll on a *matching* ``.ids`` to
    close that window. ``os.replace`` is atomic, so this reads either the
    absent/old file or the fully-written new one, never a partial line.
    """
    if not os.path.exists(ids_path):
        return 0
    with open(ids_path) as f:
        return sum(1 for line in f if line.strip())


def _make_engine(tmp_path, faiss_save_interval: float):
    config = GaOTTTConfig(
        data_dir=str(tmp_path),
        db_path=str(tmp_path / "test.db"),
        faiss_index_path=str(tmp_path / "test.faiss"),
        faiss_save_interval_seconds=faiss_save_interval,
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
async def test_faiss_save_loop_persists_new_documents(tmp_path):
    """Documents indexed via engine A become visible to a fresh engine B's
    startup() without engine A being shut down first.
    """
    engine_a = _make_engine(tmp_path, faiss_save_interval=0.1)
    await engine_a.startup()
    try:
        ids = await engine_a.index_documents([
            {
                "content": "write-behind-test-doc-alpha",
                "metadata": {"source": "agent"},
            },
            {
                "content": "write-behind-test-doc-beta",
                "metadata": {"source": "agent"},
            },
        ])
        assert len(ids) == 2
        assert engine_a._faiss_dirty is True

        # Wait for the periodic loop to persist the index to disk. File
        # existence + non-empty size is the canonical signal — the dirty
        # flag flips False *before* save completes by design (claim-then-
        # save) so other adds during the save aren't lost.
        path = engine_a.config.faiss_index_path
        ids_path = path + ".ids"
        saved = False
        for _ in range(60):  # up to 6s
            await asyncio.sleep(0.1)
            # Gate on the index file AND a matching .ids sidecar — not the
            # .faiss file alone. save() commits .faiss before .ids, so a
            # .faiss-only gate races the second os.replace: engine_b would
            # load a torn pair and the H4 guard would reset it to empty.
            if (
                os.path.exists(path) and os.path.getsize(path) > 0
                and _ids_line_count(ids_path) == len(ids)
            ):
                saved = True
                break
        assert saved, "FAISS index (+ matching .ids sidecar) was not saved within timeout"

        # Spin up a fresh engine pointing at the same files.
        engine_b = _make_engine(tmp_path, faiss_save_interval=0.0)
        await engine_b.startup()
        try:
            for nid in ids:
                assert nid in engine_b.faiss_index._id_map, (
                    f"id {nid} not visible to engine B's FAISS index"
                )
        finally:
            await engine_b.shutdown()
    finally:
        await engine_a.shutdown()


@pytest.mark.asyncio
async def test_faiss_save_interval_zero_disables_loop(tmp_path):
    """faiss_save_interval_seconds=0 should keep the engine functional but
    skip the background save task entirely (legacy behaviour, opt-in).
    """
    engine = _make_engine(tmp_path, faiss_save_interval=0.0)
    await engine.startup()
    try:
        assert engine._faiss_save_task is None
        # Index a doc and confirm shutdown still flushes synchronously.
        ids = await engine.index_documents([
            {"content": "zero-interval-doc", "metadata": {"source": "agent"}},
        ])
        assert len(ids) == 1
    finally:
        await engine.shutdown()
    # Disk file should exist after shutdown's final synchronous save.
    assert os.path.exists(engine.config.faiss_index_path)
