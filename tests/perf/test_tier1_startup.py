"""Tier 1 smoke — engine startup integrity.

Three assertions, each catching a real failure mode observed in the
field (cf. memory id=55579286, 2026-05-14):

  1. Empty data_dir → boot to a healthy zero-state, no exception.
  2. Boot, index a few docs, shutdown, boot again → state survives
     (FAISS + BM25 + SQLite content all reload).
  3. Repeated startup on the same dir is idempotent (catches the
     "FAISS index file present but empty" failure where reload
     silently leaves ntotal=0 with non-empty SQLite).
"""
from __future__ import annotations

import pytest

from tests.perf._helpers import active_doc_count, make_engine


@pytest.mark.asyncio
async def test_startup_from_empty_dir(tmp_path):
    """Engine boots cleanly with no prior persisted state."""
    eng = make_engine(tmp_path)
    await eng.startup()
    try:
        assert eng.faiss_index.size == 0
        if eng.bm25_index is not None:
            assert eng.bm25_index.size == 0
        if eng.virtual_faiss_index is not None:
            assert eng.virtual_faiss_index.size == 0
        assert await active_doc_count(eng) == 0
    finally:
        await eng.shutdown()


@pytest.mark.asyncio
async def test_startup_round_trip_preserves_state(tmp_path):
    """index → shutdown → re-boot reconstructs FAISS + BM25 + SQLite."""
    docs = [
        {"content": "Eleventy Pipeline configuration"},
        {"content": "Sicily naval landing operation"},
        {"content": "Random noise alpha beta gamma"},
        {"content": "Cooking recipe carbonara pasta"},
    ]

    eng1 = make_engine(tmp_path)
    await eng1.startup()
    try:
        ids = await eng1.index_documents(docs)
        assert len(ids) == len(docs)
        assert eng1.faiss_index.size == len(docs)
        await eng1.cache.flush_to_store(eng1.store)
    finally:
        await eng1.shutdown()

    eng2 = make_engine(tmp_path)
    await eng2.startup()
    try:
        assert eng2.faiss_index.size == len(docs), (
            f"FAISS reload lost vectors: {eng2.faiss_index.size} vs {len(docs)}"
        )
        if eng2.bm25_index is not None:
            assert eng2.bm25_index.size == len(docs), (
                "BM25 rebuild from SQLite did not pick up all docs"
            )
        assert await active_doc_count(eng2) == len(docs)
    finally:
        await eng2.shutdown()


@pytest.mark.asyncio
async def test_startup_is_idempotent(tmp_path):
    """Booting twice without changes preserves all index sizes.

    Catches the silent-empty-FAISS failure: a reload that swallows an
    IO error and leaves ``ntotal=0`` while SQLite still has documents.
    """
    eng1 = make_engine(tmp_path)
    await eng1.startup()
    try:
        await eng1.index_documents([{"content": f"document {i}"} for i in range(6)])
        await eng1.cache.flush_to_store(eng1.store)
    finally:
        await eng1.shutdown()

    sizes = []
    for _ in range(3):
        eng = make_engine(tmp_path)
        await eng.startup()
        try:
            sizes.append((
                eng.faiss_index.size,
                eng.bm25_index.size if eng.bm25_index is not None else None,
                await active_doc_count(eng),
            ))
        finally:
            await eng.shutdown()

    first = sizes[0]
    assert all(s == first for s in sizes), f"Startup not idempotent: {sizes}"
    faiss_size, bm25_size, sqlite_active = first
    assert faiss_size == sqlite_active, (
        f"FAISS ({faiss_size}) ≠ active SQLite ({sqlite_active}) after reboot"
    )
    if bm25_size is not None:
        assert bm25_size == sqlite_active, (
            f"BM25 ({bm25_size}) ≠ active SQLite ({sqlite_active}) after reboot"
        )
