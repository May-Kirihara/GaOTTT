"""Tier 5 integrity — BM25 size invariant.

Unlike FAISS (which is rebuilt only via ``compact(rebuild_faiss=True)``),
the engine maintains BM25 actively: every ``remember`` adds, every
``forget`` removes, every ``merge`` removes the absorbed nodes,
``restore`` re-admits. The invariant therefore holds **without** a
compact pass:

    bm25.size == count(active documents in SQLite)
"""
from __future__ import annotations

import pytest

from tests.perf._helpers import active_doc_count, make_engine


async def _bm25_active_match(eng) -> tuple[int, int]:
    await eng.cache.flush_to_store(eng.store)
    return eng.bm25_index.size, await active_doc_count(eng)


@pytest.mark.asyncio
async def test_bm25_tracks_remember(tmp_path):
    eng = make_engine(tmp_path)
    await eng.startup()
    try:
        assert eng.bm25_index is not None
        assert eng.bm25_index.size == 0
        await eng.index_documents([{"content": f"bm25 grow {i}"} for i in range(4)])
        b, s = await _bm25_active_match(eng)
        assert b == s == 4
    finally:
        await eng.shutdown()


@pytest.mark.asyncio
async def test_bm25_tracks_forget_and_restore(tmp_path):
    eng = make_engine(tmp_path)
    await eng.startup()
    try:
        ids = await eng.index_documents(
            [{"content": f"bm25 forget {i}"} for i in range(6)]
        )
        b, s = await _bm25_active_match(eng)
        assert b == s == 6

        await eng.forget(ids[:2], hard=False)
        b, s = await _bm25_active_match(eng)
        assert b == s == 4, f"BM25 did not drop archived docs: bm25={b} sqlite={s}"

        await eng.restore(ids[:2])
        b, s = await _bm25_active_match(eng)
        assert b == s == 6, f"BM25 did not re-admit restored docs: bm25={b} sqlite={s}"

        await eng.forget(ids[-1:], hard=True)
        b, s = await _bm25_active_match(eng)
        assert b == s == 5, f"BM25 did not drop hard-deleted docs: bm25={b} sqlite={s}"
    finally:
        await eng.shutdown()


@pytest.mark.asyncio
async def test_bm25_tracks_merge(tmp_path):
    eng = make_engine(tmp_path)
    await eng.startup()
    try:
        ids = await eng.index_documents([
            {"content": "merge target A"},
            {"content": "merge target B"},
            {"content": "merge unrelated control"},
        ])
        b, s = await _bm25_active_match(eng)
        assert b == s == 3

        await eng.merge([ids[0], ids[1]])
        b, s = await _bm25_active_match(eng)
        assert b == s == 2, f"BM25 did not drop merge-absorbed doc: bm25={b} sqlite={s}"
    finally:
        await eng.shutdown()


@pytest.mark.asyncio
async def test_bm25_tracks_compact_rebuild(tmp_path):
    """compact(rebuild_faiss=True) also rebuilds BM25 — assert no drift."""
    eng = make_engine(tmp_path)
    await eng.startup()
    try:
        ids = await eng.index_documents(
            [{"content": f"compact rebuild {i}"} for i in range(8)]
        )
        await eng.forget(ids[:2], hard=False)
        b_before, s_before = await _bm25_active_match(eng)
        assert b_before == s_before == 6

        await eng.compact(rebuild_faiss=True)
        b_after, s_after = await _bm25_active_match(eng)
        assert b_after == s_after == 6, (
            f"compact drift: bm25={b_after} sqlite={s_after}"
        )
    finally:
        await eng.shutdown()
