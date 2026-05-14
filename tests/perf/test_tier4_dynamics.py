"""Tier 4 dynamics — gravity field behaviour over time.

Three contracts from design doc id=55579286:

1. **Anti-hub** — across a diverse query set, no single chunk may
   dominate top-1 results. The threshold (60% unique top-1 on 30
   queries) is loose enough for a random-embedder regime; a real
   regression toward hub-chunks pushes well below it.
2. **Displacement runaway** — repeatedly recalling the same query must
   not let the targeted chunk's ``displacement_norm`` grow without
   bound. With ``orbital_anchor_strength`` and the Hooke restoring
   force, displacement should stabilise around an equilibrium.
3. **Generational stability** — running the same query repeatedly with
   no other corpus mutation should return a *stable or near-stable* top
   set. A wildly different top-K each call indicates a state-pollution
   bug.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.perf._helpers import make_engine


GOLDEN_DIR = Path(__file__).parent / "golden_corpus"
CHUNKS_PATH = GOLDEN_DIR / "synthetic_chunks.jsonl"


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
    ids = await eng.index_documents(documents)
    return dict(zip([c["id"] for c in chunks], ids))


# 30 diverse queries spanning all topic clusters + a few generic ones.
ANTI_HUB_QUERIES = [
    "Eleventy Pipeline",
    "data cascade variables",
    "Nunjucks Liquid template",
    "plugin filters shortcodes",
    "static-site build CDN",
    "Operation Husky 1943",
    "Patton Palermo Seventh Army",
    "Mussolini Italian campaign",
    "Allied Mediterranean strategy",
    "Sicilian mountainous terrain",
    "astrocyte tripartite synapse",
    "Hebbian co-active neurons",
    "glia neurons brain regions",
    "astrocyte slow modulation",
    "synaptic plasticity TTT",
    "FAISS IndexFlatIP",
    "BM25 token frequency",
    "embedding cosine similarity",
    "Reciprocal Rank Fusion",
    "gravity waves knowledge graph",
    "carbonara guanciale pecorino",
    "starchy pasta water emulsion",
    "Roman cuisine cured pork",
    "tempering egg yolks",
    "guanciale pancetta cured",
    "quantum entanglement Bell",
    "medieval Cordoba Andalusian",
    "11ty 静的サイト",
    "シチリア 1943",
    "アストロサイト シナプス",
]
MIN_UNIQUE_TOP1_RATIO = 0.60     # 60% of queries must have distinct top-1


@pytest.mark.asyncio
async def test_anti_hub_top1_diversity(tmp_path):
    """No single chunk dominates top-1 across a diverse query set."""
    eng = make_engine(tmp_path)
    await eng.startup()
    try:
        await _ingest_corpus(eng)
        top1: list[str] = []
        for q in ANTI_HUB_QUERIES:
            results = await eng.query(text=q, top_k=1)
            if results:
                top1.append(results[0].id)
        assert top1, "Anti-hub: no queries returned any results"

        unique_ratio = len(set(top1)) / len(top1)
        most_common = max(set(top1), key=top1.count)
        most_count = top1.count(most_common)
        assert unique_ratio >= MIN_UNIQUE_TOP1_RATIO, (
            f"Anti-hub failed: only {unique_ratio:.0%} unique top-1 "
            f"({len(set(top1))}/{len(top1)}). "
            f"Most-common id {most_common} appeared {most_count} times."
        )
    finally:
        await eng.shutdown()


@pytest.mark.asyncio
async def test_displacement_stays_in_physical_bounds(tmp_path):
    """Hammering the same query 30× keeps displacement physically sane.

    With ``query_kick_strength=0.05`` and the Hooke anchor at
    equilibrium ~0.8-3.0, repeated recall should drift toward
    equilibrium and stay bounded. Catches a regression where
    displacement grows without a restoring force.

    Hard bound: ``max_displacement_norm`` (default 1e6, an emergency knob).
    Practical bound: ≤ 20 — well above the documented equilibrium
    band, but orders of magnitude below "runaway". The corpus-wide
    max displacement is tracked, not per-chunk, because the
    query_kick target shifts with whichever chunks land in top-K.
    """
    eng = make_engine(tmp_path, query_kick_enabled=True, query_kick_strength=0.05)
    await eng.startup()
    try:
        fixture_to_engine = await _ingest_corpus(eng)
        all_ids = list(fixture_to_engine.values())

        max_norm_seen = 0.0
        for _ in range(30):
            await eng.query(text="Eleventy Pipeline", top_k=5)
            iter_max = max(eng.get_displacement_norm(nid) for nid in all_ids)
            max_norm_seen = max(max_norm_seen, iter_max)

        assert max_norm_seen < eng.config.max_displacement_norm, (
            f"Displacement hit the hard cap: {max_norm_seen} "
            f"vs cap {eng.config.max_displacement_norm}"
        )
        # Practical sanity — equilibrium is ~0.8-3.0; allow 7× headroom.
        assert max_norm_seen < 20.0, (
            f"Displacement exceeded practical bound: {max_norm_seen} > 20.0 "
            "(suggests broken Hooke / missing anchor / cap saturation)"
        )
    finally:
        await eng.shutdown()


@pytest.mark.asyncio
async def test_repeated_recall_top_set_stays_mostly_stable(tmp_path):
    """Same query, 5 consecutive calls → top-5 sets overlap ≥ 4 / 5.

    With ``query_kick_enabled=True`` (the production default) each
    recall nudges displacement, which can shift one or two chunks in
    and out of the top-K window. We tolerate that and require
    Jaccard-style overlap of ≥ 4/5 across calls. A wider divergence
    indicates state-pollution in the wave or cache layer.
    """
    eng = make_engine(tmp_path)
    await eng.startup()
    try:
        await _ingest_corpus(eng)
        sets: list[frozenset] = []
        for _ in range(5):
            results = await eng.query(text="Eleventy Pipeline", top_k=5)
            sets.append(frozenset(r.id for r in results))

        baseline = sets[0]
        failures: list[str] = []
        for i, s in enumerate(sets[1:], start=1):
            overlap = len(s & baseline)
            if overlap < 4:
                failures.append(
                    f"call {i}: only {overlap}/5 overlap with call 0 "
                    f"(set diff: in={sorted(s - baseline)}, "
                    f"out={sorted(baseline - s)})"
                )
        assert not failures, "Top-5 instability:\n  " + "\n  ".join(failures)
    finally:
        await eng.shutdown()
