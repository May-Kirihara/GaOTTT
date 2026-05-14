"""Tier 7 regression — golden corpus baseline.

Stage 1 scope (this file):
  - Verify the loader path (chunks + queries parse, ids cross-reference).
  - Verify that for every golden query the lexical layer (BM25) returns
    the expected fixture id in its top-K. This is the layer we can
    assert deterministically with random embeddings; the full
    ``engine.query`` ranking depends on wave dynamics that need a larger
    corpus to baseline meaningfully.

Stage 2 (deferred — same commitment id=faf61f5f, deadline 2026-05-28):
  - Expand the corpus to ~30 chunks across topic clusters.
  - Add `engine.query` top-K assertions with Surface / Semantic /
    Score-scale axes.
  - Add a score-scale baseline (raw FAISS / RRF / final) frozen at ±30%.

If you intentionally change retrieval behaviour and want to re-baseline,
edit ``golden_corpus/queries.json`` — never adjust this test to make a
real regression pass silently.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.perf._helpers import make_engine


GOLDEN_DIR = Path(__file__).parent / "golden_corpus"
CHUNKS_PATH = GOLDEN_DIR / "synthetic_chunks.jsonl"
QUERIES_PATH = GOLDEN_DIR / "queries.json"

# Stage 1: top-K window. Generous enough that BM25's lexical match for
# the seeded queries lands inside the window even with random embeddings.
TOP_K = 3


def _load_chunks() -> list[dict]:
    if not CHUNKS_PATH.exists():
        pytest.skip(f"Golden corpus missing: {CHUNKS_PATH}")
    chunks: list[dict] = []
    with CHUNKS_PATH.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            chunks.append(json.loads(line))
    return chunks


def _load_queries() -> list[dict]:
    if not QUERIES_PATH.exists():
        pytest.skip(f"Golden queries missing: {QUERIES_PATH}")
    with QUERIES_PATH.open(encoding="utf-8") as f:
        return json.load(f)


def test_golden_corpus_files_load():
    """Stage 1 sanity — the corpus and queries parse and reference each other."""
    chunks = _load_chunks()
    queries = _load_queries()

    assert chunks, "synthetic_chunks.jsonl is empty"
    assert queries, "queries.json is empty"

    fixture_ids = {c["id"] for c in chunks}
    for q in queries:
        _, expected_ids = _query_expectations(q)
        for expected in expected_ids:
            assert expected in fixture_ids, (
                f"query {q['query']!r} expects unknown fixture id {expected!r}"
            )


def _query_expectations(q: dict) -> tuple[str, list[str]]:
    """Pull the match mode out of a query record.

    Returns ``(mode, fixture_ids)`` where ``mode`` is:
      - ``"all"`` — every id in the list must appear in top-K
      - ``"any"`` — at least one id in the list must appear in top-K
    """
    if "expected_top" in q:
        return "all", q["expected_top"]
    if "expected_top_any" in q:
        return "any", q["expected_top_any"]
    raise KeyError(f"query missing expected_top / expected_top_any: {q}")


@pytest.mark.asyncio
async def test_golden_queries_hit_bm25_top(tmp_path):
    """BM25 layer must satisfy each golden query's expectations.

    Uses BM25 directly (not the full ``engine.query`` wave) so the
    assertion is deterministic under the random-embedder regime. The
    full wave-level golden lives in Tier 3.
    """
    chunks = _load_chunks()
    queries = _load_queries()

    eng = make_engine(tmp_path)
    await eng.startup()
    try:
        documents = [
            {
                "content": c["content"],
                "metadata": {
                    "source": c.get("source", "synthetic"),
                    "tags": c.get("tags", []),
                    "golden_fixture_id": c["id"],
                },
            }
            for c in chunks
        ]
        engine_ids = await eng.index_documents(documents)
        fixture_to_engine = dict(zip([c["id"] for c in chunks], engine_ids))

        assert eng.bm25_index is not None, (
            "Tier 7 assumes BM25 is enabled — see _helpers.make_engine"
        )

        failures: list[str] = []
        for q in queries:
            mode, fixture_ids = _query_expectations(q)
            results = eng.bm25_index.search(q["query"], top_k=TOP_K)
            result_ids = [doc_id for doc_id, _ in results]
            engine_targets = [fixture_to_engine[fid] for fid in fixture_ids if fid in fixture_to_engine]

            if mode == "all":
                missing = [fid for fid in fixture_ids if fixture_to_engine.get(fid) not in result_ids]
                if missing:
                    failures.append(
                        f"query {q['query']!r}: missing {missing} from BM25 top-{TOP_K} {result_ids}"
                    )
            else:  # "any"
                if not any(target in result_ids for target in engine_targets):
                    failures.append(
                        f"query {q['query']!r}: none of {fixture_ids} in BM25 top-{TOP_K} {result_ids}"
                    )
        assert not failures, "Golden regression failures:\n  " + "\n  ".join(failures)
    finally:
        await eng.shutdown()
