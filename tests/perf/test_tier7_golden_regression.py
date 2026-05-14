"""Tier 7 regression — golden corpus baseline at engine.query level.

Real RURI embedder + 30-chunk corpus + 11 queries spanning surface /
semantic-cluster / cross-vocabulary / source-mix axes. The test runs
the full ``engine.query`` and asserts each query's expected fixture id
lands in the top-K.

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

# Real RURI: top-K=5 is tight enough to catch ranking regressions
# while tolerating minor reordering between BM25-strong and
# semantic-strong queries.
TOP_K = 5


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
async def test_golden_queries_hit_engine_query_top(tmp_path):
    """Full ``engine.query`` must satisfy each golden query's expectations.

    With real RURI semantic ranking + BM25 hybrid seed pool + wave
    propagation, the production retrieval path must surface each
    expected fixture id within the top-K window. This is the test
    that catches retrieval-quality regressions across phase boundaries.
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

        failures: list[str] = []
        for q in queries:
            mode, fixture_ids = _query_expectations(q)
            results = await eng.query(text=q["query"], top_k=TOP_K)
            result_ids = [r.id for r in results]
            engine_targets = [fixture_to_engine[fid] for fid in fixture_ids if fid in fixture_to_engine]

            if mode == "all":
                missing = [fid for fid in fixture_ids if fixture_to_engine.get(fid) not in result_ids]
                if missing:
                    failures.append(
                        f"query {q['query']!r}: missing {missing} from engine top-{TOP_K} {result_ids}"
                    )
            else:  # "any"
                if not any(target in result_ids for target in engine_targets):
                    failures.append(
                        f"query {q['query']!r}: none of {fixture_ids} in engine top-{TOP_K} {result_ids}"
                    )
        assert not failures, "Golden regression failures:\n  " + "\n  ".join(failures)
    finally:
        await eng.shutdown()
