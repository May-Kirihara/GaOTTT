"""Tier 3 retrieval quality — engine.query golden-corpus assertions.

Real RURI v3 310m provides genuine semantic ranking, so the contracts
here are *tight* — they test what a user actually experiences.

Three axes from design doc id=55579286:

A. **Surface (plain)** — top_k=5 must contain the lexical-match chunk.
B. **Surface (tag_filter)** — top_k=3 with Phase J Stage 2 injection;
   exact match must land tightly.
C. **Semantic cluster** — top_k=5; ≥1 cluster member must surface
   (paraphrase reaches the right neighbourhood).
D. **Source-mix sanity** — top_k=5; no single cluster dominates
   ≥ 4/5 of the result.

A regression in any axis fires Tier 3.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.perf._helpers import make_engine


GOLDEN_DIR = Path(__file__).parent / "golden_corpus"
CHUNKS_PATH = GOLDEN_DIR / "synthetic_chunks.jsonl"
QUERIES_PATH = GOLDEN_DIR / "queries.json"

TOP_K_SURFACE_PLAIN = 5         # real RURI: surface match should land in top-5
TOP_K_SURFACE_TAGGED = 3        # tag_filter + RRF — strict
TOP_K_SEMANTIC = 5              # ≥1 cluster member in top-5
TOP_K_SOURCE_MIX = 5
MAX_SOURCE_DOMINANCE = 4        # 4/5 from one cluster is the warning threshold

# Map surface-query tag to a primary cluster tag for tag_filter injection.
# Stays narrow on purpose — Stage 2 only exercises queries whose primary
# tag we can derive deterministically from the corpus.
SURFACE_TAG_HINTS = {
    "Eleventy Pipeline": "eleventy",
    "Sicily naval landing": "sicily",
    "guanciale pecorino eggs": "cooking",
    "Hebbian learning": "hebbian",
    "Reciprocal Rank Fusion": "rrf",
}


def _load_chunks() -> list[dict]:
    with CHUNKS_PATH.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _load_queries() -> list[dict]:
    with QUERIES_PATH.open(encoding="utf-8") as f:
        return json.load(f)


def _query_expectations(q: dict) -> tuple[str, list[str]]:
    if "expected_top" in q:
        return "all", q["expected_top"]
    if "expected_top_any" in q:
        return "any", q["expected_top_any"]
    raise KeyError(q)


async def _ingest_corpus(eng):
    chunks = _load_chunks()
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
    engine_to_fixture = {v: k for k, v in fixture_to_engine.items()}
    return fixture_to_engine, engine_to_fixture, chunks


@pytest.mark.asyncio
async def test_engine_query_surface_plain(tmp_path):
    """Path A — plain engine.query, top_k=5.

    With real RURI semantic ranking + BM25 seed-pool union, a surface
    query must land its lexical match in the top-5.
    """
    queries = _load_queries()
    surface = [q for q in queries if q.get("axis") == "surface"]

    eng = make_engine(tmp_path)
    await eng.startup()
    try:
        fixture_to_engine, _, _ = await _ingest_corpus(eng)

        failures: list[str] = []
        for q in surface:
            _, fixture_ids = _query_expectations(q)
            results = await eng.query(text=q["query"], top_k=TOP_K_SURFACE_PLAIN)
            result_ids = {r.id for r in results}
            for fid in fixture_ids:
                eid = fixture_to_engine.get(fid)
                if eid is None or eid not in result_ids:
                    failures.append(
                        f"surface query {q['query']!r}: fixture {fid} not in plain top-{TOP_K_SURFACE_PLAIN}"
                    )
        assert not failures, "Surface (plain) failures:\n  " + "\n  ".join(failures)
    finally:
        await eng.shutdown()


@pytest.mark.asyncio
async def test_engine_query_surface_with_tag_filter(tmp_path):
    """Path B — tag_filter injection forces RRF re-ranking.

    With Phase J Stage 2 (tag_filter injection) and Phase L Stage 1
    (RRF over injected set), the lexical match must land in top-3. This
    is the contract that catches production-grade regressions where
    ``recall(tag_filter=[...])`` stops surfacing the expected chunk.
    """
    queries = _load_queries()
    surface = [q for q in queries if q.get("axis") == "surface"]

    eng = make_engine(tmp_path)
    await eng.startup()
    try:
        fixture_to_engine, _, _ = await _ingest_corpus(eng)

        failures: list[str] = []
        for q in surface:
            _, fixture_ids = _query_expectations(q)
            tag = SURFACE_TAG_HINTS.get(q["query"])
            if tag is None:
                continue  # not all surface queries have a deterministic tag hint
            results = await eng.query(
                text=q["query"], top_k=TOP_K_SURFACE_TAGGED, tag_filter=[tag],
            )
            result_ids = {r.id for r in results}
            for fid in fixture_ids:
                eid = fixture_to_engine.get(fid)
                if eid is None or eid not in result_ids:
                    failures.append(
                        f"surface query {q['query']!r} (tag={tag!r}): "
                        f"fixture {fid} not in tagged top-{TOP_K_SURFACE_TAGGED}"
                    )
        assert not failures, "Surface (tag_filter) failures:\n  " + "\n  ".join(failures)
    finally:
        await eng.shutdown()


@pytest.mark.asyncio
async def test_engine_query_semantic_cluster(tmp_path):
    """Semantic-cluster queries: ≥1 cluster member must appear in top-K."""
    queries = _load_queries()
    semantic = [q for q in queries if q.get("axis") in ("semantic-cluster", "cross-vocabulary")]

    eng = make_engine(tmp_path)
    await eng.startup()
    try:
        fixture_to_engine, _, _ = await _ingest_corpus(eng)

        failures: list[str] = []
        for q in semantic:
            _, fixture_ids = _query_expectations(q)
            results = await eng.query(text=q["query"], top_k=TOP_K_SEMANTIC)
            result_ids = {r.id for r in results}
            targets = [fixture_to_engine[fid] for fid in fixture_ids if fid in fixture_to_engine]
            if not any(t in result_ids for t in targets):
                failures.append(
                    f"semantic query {q['query']!r}: none of {fixture_ids} in engine top-{TOP_K_SEMANTIC}"
                )
        assert not failures, "Semantic-cluster failures:\n  " + "\n  ".join(failures)
    finally:
        await eng.shutdown()


@pytest.mark.asyncio
async def test_engine_query_source_mix_sanity(tmp_path):
    """No single topic cluster should monopolize the top-K for a generic query.

    Uses the first tag of each chunk as a proxy for "cluster" (e.g. all
    cooking chunks share tag ``cooking``). If 4+ of top-5 share their
    primary tag, that's a hub-like dominance warning.
    """
    queries = _load_queries()
    mix = [q for q in queries if q.get("axis") == "source-mix"]
    if not mix:
        pytest.skip("No source-mix queries defined")

    eng = make_engine(tmp_path)
    await eng.startup()
    try:
        _, engine_to_fixture, chunks = await _ingest_corpus(eng)
        fixture_to_primary_tag = {
            c["id"]: (c.get("tags") or ["uncategorized"])[0]
            for c in chunks
        }

        failures: list[str] = []
        for q in mix:
            results = await eng.query(text=q["query"], top_k=TOP_K_SOURCE_MIX)
            tags = []
            for r in results:
                fid = engine_to_fixture.get(r.id)
                if fid is not None:
                    tags.append(fixture_to_primary_tag.get(fid, "unknown"))
            if not tags:
                continue
            most_common = max(set(tags), key=tags.count)
            count = tags.count(most_common)
            if count >= MAX_SOURCE_DOMINANCE:
                failures.append(
                    f"source-mix query {q['query']!r}: tag {most_common!r} "
                    f"appears {count}/{TOP_K_SOURCE_MIX} times (warn at ≥{MAX_SOURCE_DOMINANCE})"
                )
        # Note: source-mix is a *warning* signal, not a hard fail criterion.
        # The assertion is here so a regression toward hub-dominance fires
        # the test; if you intentionally want a dominant cluster, raise
        # MAX_SOURCE_DOMINANCE.
        assert not failures, "Source-mix dominance:\n  " + "\n  ".join(failures)
    finally:
        await eng.shutdown()


@pytest.mark.asyncio
async def test_engine_query_returns_results_for_every_golden_query(tmp_path):
    """Sanity: engine.query must return at least 1 result for every golden query."""
    queries = _load_queries()
    eng = make_engine(tmp_path)
    await eng.startup()
    try:
        await _ingest_corpus(eng)
        failures: list[str] = []
        for q in queries:
            results = await eng.query(text=q["query"], top_k=5)
            if not results:
                failures.append(f"empty results for query {q['query']!r}")
        assert not failures, "Empty-result failures:\n  " + "\n  ".join(failures)
    finally:
        await eng.shutdown()
