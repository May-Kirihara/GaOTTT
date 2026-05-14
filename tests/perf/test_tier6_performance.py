"""Tier 6 performance — latency / throughput baselines (real RURI).

Each test prints its measurement and asserts an upper bound that
catches structural regressions while tolerating modest hardware
variance.

Used as part of the 仮説 → 実装 → 検証 manual loop: after touching a hot
path, run this and confirm the numbers haven't drifted past the
budget. Snapshot historical values with ``scripts/perf_baseline.py``
for delta inspection.

Budgets (calibrated against real RURI v3 310m on a workstation,
2026-05-14):
  - recall p50 < 60ms (CLAUDE.md production target is < 50ms;
    observed ~35ms; budget gives ~70% headroom)
  - recall p95 < 120ms (observed ~56ms)
  - recall p99 < 250ms (observed ~85ms)
  - ingest > 500 docs/sec (observed ~1200; budget ~40% of observed
    to absorb batch-size + corpus variation)
  - engine init (cold/warm, model already in singleton) < 30s
  - compact (200 docs) < 30s
"""
from __future__ import annotations

import time

import pytest

from tests.perf._helpers import active_doc_count, make_engine


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = int(round((pct / 100.0) * (len(s) - 1)))
    return s[k]


@pytest.mark.asyncio
async def test_recall_latency_under_budget(tmp_path):
    eng = make_engine(tmp_path)
    await eng.startup()
    try:
        await eng.index_documents(
            [{"content": f"latency doc {i} with some body text"} for i in range(200)]
        )

        # Warm-up — exclude cold caches from the measurement
        for _ in range(5):
            await eng.query(text="latency doc 1", top_k=5)

        latencies_ms: list[float] = []
        for i in range(100):
            t0 = time.perf_counter()
            await eng.query(text=f"latency doc {i % 50}", top_k=5)
            latencies_ms.append((time.perf_counter() - t0) * 1000.0)

        p50 = _percentile(latencies_ms, 50)
        p95 = _percentile(latencies_ms, 95)
        p99 = _percentile(latencies_ms, 99)
        print(
            f"\nrecall latency (200-doc corpus, 100 calls): "
            f"p50={p50:.1f}ms p95={p95:.1f}ms p99={p99:.1f}ms"
        )

        # Real-RURI calibrated bounds. CLAUDE.md target is p50 < 50ms;
        # budget allows ~70% headroom for hardware variance.
        assert p50 < 60.0, f"p50={p50:.1f}ms > 60ms budget (CLAUDE.md target <50ms)"
        assert p95 < 120.0, f"p95={p95:.1f}ms > 120ms budget"
        assert p99 < 250.0, f"p99={p99:.1f}ms > 250ms budget"
    finally:
        await eng.shutdown()


@pytest.mark.asyncio
async def test_ingest_throughput_above_floor(tmp_path):
    eng = make_engine(tmp_path)
    await eng.startup()
    try:
        docs = [
            {"content": f"throughput doc {i} body lorem ipsum dolor sit amet"}
            for i in range(500)
        ]
        t0 = time.perf_counter()
        ids = await eng.index_documents(docs)
        elapsed = time.perf_counter() - t0

        assert len(ids) == 500
        throughput = 500 / elapsed
        print(f"\ningest throughput: {throughput:.1f} docs/sec (500 docs in {elapsed:.2f}s)")
        # Real-RURI calibrated: observed ~1200 docs/sec, budget at 40% headroom.
        assert throughput > 500.0, (
            f"ingest throughput {throughput:.1f} docs/sec < 500 docs/sec floor"
        )
    finally:
        await eng.shutdown()


@pytest.mark.asyncio
async def test_startup_time_under_budget(tmp_path):
    """Cold (empty) and warm (200-doc DB) startup must stay sane."""
    cold_engine = make_engine(tmp_path)
    t0 = time.perf_counter()
    await cold_engine.startup()
    cold_elapsed = time.perf_counter() - t0
    try:
        await cold_engine.index_documents(
            [{"content": f"warm doc {i}"} for i in range(200)]
        )
        await cold_engine.cache.flush_to_store(cold_engine.store)
    finally:
        await cold_engine.shutdown()

    warm_engine = make_engine(tmp_path)
    t0 = time.perf_counter()
    await warm_engine.startup()
    warm_elapsed = time.perf_counter() - t0
    try:
        assert await active_doc_count(warm_engine) == 200
    finally:
        await warm_engine.shutdown()

    print(
        f"\nstartup: cold={cold_elapsed:.2f}s warm(200 docs)={warm_elapsed:.2f}s"
    )
    assert cold_elapsed < 30.0, f"cold startup {cold_elapsed:.2f}s > 30s budget"
    assert warm_elapsed < 60.0, f"warm startup {warm_elapsed:.2f}s > 60s budget"


@pytest.mark.asyncio
async def test_compact_time_under_budget(tmp_path):
    eng = make_engine(tmp_path)
    await eng.startup()
    try:
        await eng.index_documents([{"content": f"compact doc {i}"} for i in range(200)])
        t0 = time.perf_counter()
        await eng.compact(rebuild_faiss=True)
        elapsed = time.perf_counter() - t0
        print(f"\ncompact(rebuild_faiss=True, 200-doc corpus): {elapsed:.2f}s")
        assert elapsed < 30.0, f"compact {elapsed:.2f}s > 30s budget"
    finally:
        await eng.shutdown()
