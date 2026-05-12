"""Phase L Stage 1 — BM25 union seed integration tests.

The seed pool now unions raw FAISS (semantic) + virtual FAISS (semantic +
history) + BM25 (lexical). Lexical and semantic are independent metric
tensors, so a doc the embedder cosine-ranks far from a query can still
enter the wave through BM25 surface-form match.

Scenarios covered:
  1. BM25 catches a lexical match the embedder misses (Phase L Stage 1
     core motivation: "Eleventy Pipeline" → .eleventy.js).
  2. ``hybrid_bm25_enabled=False`` is a clean rollback to the Phase H
     Stage 4 behaviour.
  3. ``archive`` immediately drops a doc from BM25 search.
  4. ``compact(rebuild_faiss=True)`` rebuilds BM25 from SQLite, recovering
     a doc that was added without the engine being aware of it.
"""
from __future__ import annotations

import hashlib

import numpy as np
import pytest

from gaottt.config import GaOTTTConfig
from gaottt.core.engine import GaOTTTEngine
from gaottt.index.bm25_index import BM25Index
from gaottt.index.faiss_index import FaissIndex
from gaottt.store.cache import CacheLayer
from gaottt.store.sqlite_store import SqliteStore


class StubEmbedder:
    """Deterministic random embeddings keyed on md5 of text. Cosine
    similarity has no relationship to lexical overlap, so BM25's
    contribution is testable in isolation."""

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


def _make_engine(tmp_path, *, bm25_enabled: bool = True):
    config = GaOTTTConfig(
        data_dir=str(tmp_path),
        db_path=str(tmp_path / "test.db"),
        faiss_index_path=str(tmp_path / "test.faiss"),
        virtual_faiss_index_path=str(tmp_path / "test.virtual.faiss"),
        virtual_faiss_enabled=True,
        hybrid_bm25_enabled=bm25_enabled,
        wave_initial_k=3,
        wave_seed_mass_alpha=0.0,
        wave_dynamic_k_enabled=False,
        genesis_kick_enabled=False,
        supernova_enabled=False,
        dream_enabled=False,
        faiss_save_interval_seconds=0.0,
        virtual_faiss_save_interval_seconds=0.0,
        flush_interval_seconds=0.05,
        persona_boost_enabled=False,
    )
    embedder = StubEmbedder(dim=config.embedding_dim)
    faiss_index = FaissIndex(dimension=config.embedding_dim)
    virtual_faiss_index = FaissIndex(dimension=config.embedding_dim)
    bm25_index = (
        BM25Index(
            k1=config.bm25_k1, b=config.bm25_b, tokenizer=config.bm25_tokenizer,
        ) if bm25_enabled else None
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
        bm25_index=bm25_index,
    )


@pytest.mark.asyncio
async def test_bm25_catches_lexical_match_embedder_misses(tmp_path):
    """The literal Stage 1 promise: a doc with a surface-form match for
    the query enters the seed pool even when the embedder ranks it far.
    """
    eng = _make_engine(tmp_path, bm25_enabled=True)
    await eng.startup()
    try:
        await eng.index_documents([
            {"content": "Eleventy Pipeline configuration responsibility"},
            {"content": "Sicily naval landing operation history"},
            {"content": "Random noise alpha beta gamma"},
            {"content": "Another unrelated document about cooking"},
            {"content": "Yet another distractor on totally different topic"},
        ])

        results = await eng.query(text="Eleventy Pipeline", top_k=3)
        contents_top = [r.content for r in results]
        # The lexical match must be present in the top results.
        assert any("Eleventy Pipeline" in c for c in contents_top), (
            f"BM25 union did not surface lexical match. Got: {contents_top}"
        )
    finally:
        await eng.shutdown()


@pytest.mark.asyncio
async def test_rollback_flag_disables_bm25_contribution(tmp_path):
    """With hybrid_bm25_enabled=False, BM25 contributes nothing — search
    behaviour matches Phase H Stage 4 exactly. We do not assert the
    embedder fails to find the lexical match (that's randomness-dependent),
    only that the rollback path produces a result without crashing.
    """
    eng = _make_engine(tmp_path, bm25_enabled=False)
    await eng.startup()
    try:
        # bm25_index is not wired when the flag is off.
        assert eng.bm25_index is None
        await eng.index_documents([
            {"content": "Some doc"}, {"content": "Other doc"},
        ])
        results = await eng.query(text="anything", top_k=2)
        # Should complete without errors and return at most top_k.
        assert len(results) <= 2
    finally:
        await eng.shutdown()


@pytest.mark.asyncio
async def test_archive_drops_doc_from_bm25_immediately(tmp_path):
    """After archive, the doc must stop surfacing in lexical search even
    before the next compact."""
    eng = _make_engine(tmp_path, bm25_enabled=True)
    await eng.startup()
    try:
        ids = await eng.index_documents([
            {"content": "Unique trigram zzqwerty target"},
            {"content": "Padding doc one"},
            {"content": "Padding doc two"},
        ])
        target_id = ids[0]

        # Pre-archive: target surfaces.
        pre = await eng.query(text="zzqwerty", top_k=3)
        assert target_id in {r.id for r in pre}, (
            f"Pre-archive, target should surface but got {[r.id for r in pre]}"
        )

        # Archive then re-query.
        await eng.archive([target_id])
        post = await eng.query(text="zzqwerty", top_k=3)
        assert target_id not in {r.id for r in post}, (
            "Archived doc must not surface in BM25 search"
        )
    finally:
        await eng.shutdown()


@pytest.mark.asyncio
async def test_compact_rebuild_resyncs_bm25_from_store(tmp_path):
    """compact(rebuild_faiss=True) rebuilds BM25 from SQLite, picking up
    any divergence (simulated here by manually wiping in-memory state).
    """
    eng = _make_engine(tmp_path, bm25_enabled=True)
    await eng.startup()
    try:
        await eng.index_documents([
            {"content": "Synchronization marker abcxyzdef payload"},
            {"content": "Random filler one"},
            {"content": "Random filler two"},
        ])

        # Wipe the in-memory BM25 without touching SQLite — simulates a
        # process that loaded a stale index or a divergence from another
        # process's write.
        assert eng.bm25_index is not None
        eng.bm25_index.reset()
        assert eng.bm25_index.size == 0

        # compact must rebuild from SQLite.
        report = await eng.compact(rebuild_faiss=True)
        assert report["faiss_rebuilt"] is True
        assert eng.bm25_index.size == 3

        results = await eng.query(text="abcxyzdef", top_k=3)
        assert any("abcxyzdef" in r.content for r in results), (
            "compact-rebuild did not restore BM25 sync"
        )
    finally:
        await eng.shutdown()
