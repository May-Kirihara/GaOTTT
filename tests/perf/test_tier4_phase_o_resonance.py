"""Tier 4 — Phase O observability + Phase I Stage 2 driven-resonance contract.

Captured from a 2026-05-15 GLM-5.1 external playthrough (33k production
corpus) that observed the literal isomorphism `a = (α · score · gate /
m_i) · (q - pos_i)` in action via the Phase O Stage 2 training_delta
trailer:

  - 3 consecutive identical recalls accumulated `Δmass ≈ +0.057/recall`
    on the top-1 chunk
  - decay grew (0.649 → 0.629 → 0.610) while displacement oscillated ±0.03
  - the system self-regulated (no runaway)

Two contracts here, both Tier 4 (dynamics):

A. **Driven resonance accumulator** — top-1 mass strictly increases
   across 3 forced re-runs of the same query. Catches a regression
   where Phase I Stage 2's query-kick term stops feeding gradient back
   into the field (or fires for the wrong node).

B. **Top-1 displacement stays bounded** — across the same 3 recalls,
   |Δdisplacement| per step stays below a sane practical bound. Catches
   regression toward unbounded drift in the absence of the Hooke anchor.

Both contracts read off the ``training_delta`` payload (Phase O Stage 2)
so the test exercises the **observability surface** itself — if the
trailer goes missing or the dict shape changes, this test fails.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from gaottt.services import maintenance as maint_svc
from gaottt.services import memory as mem_svc
from tests.perf._helpers import make_engine


GOLDEN_DIR = Path(__file__).parent / "golden_corpus"
CHUNKS_PATH = GOLDEN_DIR / "synthetic_chunks.jsonl"

RESONANCE_QUERY = "Eleventy Pipeline"
RECALL_COUNT = 3
TOP_K = 5

# Practical bounds. Tight enough to fire on a real regression, loose
# enough to absorb embedder / cache noise.
MIN_MASS_GAIN_PER_RECALL = 1e-4        # ~ floor of Phase I Stage 2's α·score·gate
MAX_DISPLACEMENT_STEP_PER_RECALL = 1.0 # equilibrium band ~0.8-3.0; >1.0/step is runaway


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
async def test_driven_resonance_mass_accumulates(tmp_path):
    """3 forced recalls of same query → top-1 Δmass > 0 each time.

    Reads training_delta.mass_changes[top1_id] from each recall. Phase M
    self-force filter is OFF in the test engine, so the gradient feeds
    cleanly back into the top-1 node without being cancelled.
    """
    eng = make_engine(
        tmp_path,
        query_kick_enabled=True,
        query_kick_strength=0.05,
        training_delta_enabled=True,
    )
    await eng.startup()
    try:
        await _ingest_corpus(eng)

        deltas: list[float] = []
        top1_id: str | None = None
        for i in range(RECALL_COUNT):
            r = await mem_svc.recall(
                engine=eng,
                query=RESONANCE_QUERY,
                top_k=TOP_K,
                force_refresh=True,           # bypass cache — we want the wave to run
                auto_route=False,             # routing trailer is Stage 3, not under test here
            )
            assert r.items, f"recall #{i+1} returned no items"
            assert r.training_delta is not None, (
                f"recall #{i+1}: training_delta missing — Phase O Stage 2 trailer is broken"
            )
            assert not r.training_delta.cache_hit, (
                f"recall #{i+1}: cache_hit=True but force_refresh was set"
            )
            if top1_id is None:
                top1_id = r.items[0].id
            mass_changes = r.training_delta.mass_changes
            assert top1_id in mass_changes, (
                f"recall #{i+1}: top-1 id {top1_id[:8]}.. not in mass_changes "
                f"({list(mass_changes)[:3]}...)"
            )
            deltas.append(mass_changes[top1_id])

        # Every recall must push mass forward on the top-1 by at least the floor.
        for i, d in enumerate(deltas):
            assert d >= MIN_MASS_GAIN_PER_RECALL, (
                f"Driven resonance broken: recall #{i+1} produced Δmass={d:.5f} "
                f"on top-1 (need ≥ {MIN_MASS_GAIN_PER_RECALL}). "
                f"Phase I Stage 2's α·score·gate term may have regressed."
            )

        total_gain = sum(deltas)
        assert total_gain > 3 * MIN_MASS_GAIN_PER_RECALL, (
            f"Cumulative Δmass over {RECALL_COUNT} recalls = {total_gain:.5f}, "
            f"expected ≥ {3 * MIN_MASS_GAIN_PER_RECALL}. The accumulator is flat."
        )
    finally:
        await eng.shutdown()


@pytest.mark.asyncio
async def test_driven_resonance_displacement_bounded(tmp_path):
    """Same 3 recalls — per-step |Δdisplacement| stays sane.

    The Phase I Stage 2 query-kick produces displacement toward the query
    embedding; the Hooke anchor pulls it back toward the raw embedding.
    Steady state is small oscillation, not unbounded drift. A regression
    that removes the anchor blows past `MAX_DISPLACEMENT_STEP_PER_RECALL`.
    """
    eng = make_engine(
        tmp_path,
        query_kick_enabled=True,
        query_kick_strength=0.05,
        training_delta_enabled=True,
    )
    await eng.startup()
    try:
        await _ingest_corpus(eng)
        top1_id: str | None = None
        steps: list[float] = []
        for _ in range(RECALL_COUNT):
            r = await mem_svc.recall(
                engine=eng, query=RESONANCE_QUERY, top_k=TOP_K,
                force_refresh=True, auto_route=False,
            )
            assert r.items
            if top1_id is None:
                top1_id = r.items[0].id
            td = r.training_delta
            assert td is not None
            steps.append(abs(td.displacement_changes.get(top1_id, 0.0)))

        for i, s in enumerate(steps):
            assert s <= MAX_DISPLACEMENT_STEP_PER_RECALL, (
                f"recall #{i+1}: |Δdisplacement|={s:.4f} exceeded practical bound "
                f"{MAX_DISPLACEMENT_STEP_PER_RECALL}. Hooke anchor regression?"
            )
    finally:
        await eng.shutdown()


@pytest.mark.asyncio
async def test_cache_hit_zero_perturbation(tmp_path):
    """Prefetch → recall(same query) → training_delta.cache_hit == True
    and *all* deltas are exactly zero (Phase O Stage 2 contract).

    Verifies the prefetch cache returns its stored result without
    perturbing the field — the literal *no simulation ran* property is
    machine-checkable here, complementing the substring assertion in
    Tier 1.
    """
    eng = make_engine(
        tmp_path,
        query_kick_enabled=True,
        query_kick_strength=0.05,
        training_delta_enabled=True,
    )
    await eng.startup()
    try:
        await _ingest_corpus(eng)
        # Prime the cache, then drain so the background task completes
        # before we issue the cache-served recall.
        maint_svc.prefetch(eng, query=RESONANCE_QUERY, top_k=TOP_K)
        await eng.prefetch_pool.drain(timeout=5.0)
        # Now recall — should be served from cache.
        r = await mem_svc.recall(
            engine=eng, query=RESONANCE_QUERY, top_k=TOP_K,
            force_refresh=False, auto_route=False,
        )
        assert r.items
        td = r.training_delta
        assert td is not None
        assert td.cache_hit is True, (
            "Cache hit not flagged on prefetch→recall — Phase O Stage 2 contract violated"
        )
        # Every delta must be zero on a cache hit (no simulation ran).
        all_zero_mass = all(v == 0.0 for v in td.mass_changes.values())
        all_zero_disp = all(v == 0.0 for v in td.displacement_changes.values())
        assert all_zero_mass and all_zero_disp, (
            f"Cache hit perturbed the field: "
            f"mass non-zero={[k for k, v in td.mass_changes.items() if v != 0.0][:3]}, "
            f"disp non-zero={[k for k, v in td.displacement_changes.items() if v != 0.0][:3]}"
        )
    finally:
        await eng.shutdown()
