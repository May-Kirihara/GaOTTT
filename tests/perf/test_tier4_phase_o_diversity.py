"""Tier 4 — explore(diversity=...) actually modulates the result set.

GLM's 2026-05-15 playthrough demonstrated the diversity parameter is
*not* noise injection: ``diversity=0.95`` surfaced genuine cross-domain
connections (a magic-school novel passage on a quantum-mechanics query),
``diversity=0.5`` stayed in the semantic neighbourhood. The parameter
maps to ``config.gamma *= (1 + diversity * 20)`` plus wider wave depth
and seed-k, so it's a real structural modulation.

Contract: same query, same corpus, two distinct diversity values
(low vs high) → resulting top-K sets must differ. A regression that
ignores the diversity argument leaves top-K identical.

The threshold is intentionally permissive: any single element differs
counts. We aren't measuring *quality* of the diversity (that's a
qualitative axis; see Track B playthrough harness) — we're proving the
knob is wired through.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from gaottt.services import memory as mem_svc
from tests.perf._helpers import make_engine


GOLDEN_DIR = Path(__file__).parent / "golden_corpus"
CHUNKS_PATH = GOLDEN_DIR / "synthetic_chunks.jsonl"

# A query that has multiple plausible clusters in the golden corpus so
# diversity has somewhere to migrate to (cooking shares syntactic shape
# with the rest of the corpus's "process / ingredient" register).
DIVERSITY_QUERY = "process and ingredients"
TOP_K = 5
LOW_DIVERSITY = 0.0
HIGH_DIVERSITY = 0.95


def _load_chunks() -> list[dict]:
    with CHUNKS_PATH.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


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
    return await eng.index_documents(documents)


@pytest.mark.asyncio
async def test_diversity_parameter_changes_topk(tmp_path):
    """Low vs high diversity → top-K sets must differ on at least one element.

    A regression that makes diversity a no-op (e.g. someone removes the
    gamma scaling or the wave parameter adjustments in services.explore)
    leaves the two sets identical.
    """
    eng = make_engine(tmp_path)
    await eng.startup()
    try:
        await _ingest_corpus(eng)

        low = await mem_svc.explore(
            engine=eng, query=DIVERSITY_QUERY,
            diversity=LOW_DIVERSITY, top_k=TOP_K, auto_route=False,
        )
        high = await mem_svc.explore(
            engine=eng, query=DIVERSITY_QUERY,
            diversity=HIGH_DIVERSITY, top_k=TOP_K, auto_route=False,
        )
        assert low.items and high.items, "explore returned no results"

        low_ids = [i.id for i in low.items]
        high_ids = [i.id for i in high.items]
        overlap = len(set(low_ids) & set(high_ids))

        assert overlap < TOP_K, (
            f"diversity={LOW_DIVERSITY} and diversity={HIGH_DIVERSITY} "
            f"returned identical top-{TOP_K} sets ({overlap}/{TOP_K} overlap). "
            f"The parameter is not wired through — explore(diversity=...) is a no-op."
        )
        # Echo the recorded diversity so a regression on the response field also fires here.
        assert low.diversity == LOW_DIVERSITY
        assert high.diversity == HIGH_DIVERSITY
    finally:
        await eng.shutdown()


@pytest.mark.asyncio
async def test_diversity_recorded_on_response(tmp_path):
    """``ExploreResponse.diversity`` echoes the requested value.

    Cheap structural guard — callers serialize this field, so a silent
    drop (e.g. defaulting to 0.5 always) is invisible without a check.
    """
    eng = make_engine(tmp_path)
    await eng.startup()
    try:
        await _ingest_corpus(eng)
        for d in (0.0, 0.3, 0.7, 0.95):
            r = await mem_svc.explore(
                engine=eng, query=DIVERSITY_QUERY, diversity=d, top_k=3,
                auto_route=False,
            )
            assert r.diversity == d, (
                f"explore(diversity={d}) returned diversity={r.diversity} on response"
            )
    finally:
        await eng.shutdown()
