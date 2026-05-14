"""Tier 1 smoke — BM25 in-memory index builds + serves queries.

Catches a regression where ``hybrid_bm25_enabled=True`` is set in config
but the index silently stays empty (e.g. ``_build_bm25_from_store``
broken, tokenizer error, or schema migration dropped content).

Three checks:
  1. Index size matches the active document count after ingest.
  2. A lexical-only query (whose embedding sits far from any doc) still
     surfaces the expected document via BM25.
  3. Engine rebuild from SQLite (``compact(rebuild_faiss=True)``)
     reconstructs the BM25 index correctly.
"""
from __future__ import annotations

import pytest

from tests.perf._helpers import active_doc_count, make_engine


@pytest.mark.asyncio
async def test_bm25_size_matches_active_count(tmp_path):
    eng = make_engine(tmp_path)
    await eng.startup()
    try:
        assert eng.bm25_index is not None, "BM25 should be enabled by default"
        assert eng.bm25_index.size == 0

        docs = [
            {"content": "Eleventy Pipeline static-site generator config"},
            {"content": "Sicily naval landing operation history"},
            {"content": "Random noise alpha beta gamma"},
            {"content": "Cooking recipe carbonara pasta egg cheese"},
            {"content": "Astrocyte gravity TTT correspondence note"},
        ]
        await eng.index_documents(docs)
        active = await active_doc_count(eng)
        assert active == len(docs)
        assert eng.bm25_index.size == active, (
            f"BM25 size {eng.bm25_index.size} ≠ active doc count {active}"
        )
    finally:
        await eng.shutdown()


@pytest.mark.asyncio
async def test_bm25_search_returns_lexical_match(tmp_path):
    """A query with a rare token should surface the document containing it,
    regardless of the random-embedding cosine ranking."""
    eng = make_engine(tmp_path)
    await eng.startup()
    try:
        ids = await eng.index_documents([
            {"content": "Eleventy Pipeline static-site generator config"},
            {"content": "Sicily naval landing operation history"},
            {"content": "Random noise alpha beta gamma"},
            {"content": "Cooking recipe carbonara pasta egg cheese"},
            {"content": "Astrocyte gravity TTT correspondence note"},
        ])
        eleventy_id = ids[0]

        results = eng.bm25_index.search("Eleventy Pipeline", top_k=3)
        assert results, "BM25 returned no results for a known lexical match"
        top_ids = [doc_id for doc_id, _ in results]
        assert eleventy_id in top_ids, (
            f"Eleventy doc {eleventy_id} not in BM25 top-3: {top_ids}"
        )
    finally:
        await eng.shutdown()


@pytest.mark.asyncio
async def test_bm25_rebuild_from_store(tmp_path):
    """After compact(rebuild_faiss=True), BM25 must match active docs.

    Models the production path where BM25 is rebuilt from SQLite (e.g.
    after a process restart or large ingest).
    """
    eng = make_engine(tmp_path)
    await eng.startup()
    try:
        await eng.index_documents([
            {"content": f"Smoke doc {i} with content word_{i}"} for i in range(8)
        ])
        before = eng.bm25_index.size
        await eng.compact(rebuild_faiss=True)
        after = eng.bm25_index.size
        active = await active_doc_count(eng)
        assert before == after == active, (
            f"BM25 size diverged across compact: before={before} after={after} active={active}"
        )

        results = eng.bm25_index.search("word_3", top_k=3)
        assert results, "BM25 lost a known-token match after rebuild"
    finally:
        await eng.shutdown()
