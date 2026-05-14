"""Tier 6 performance — latency / throughput baselines.

Each test prints its measurement (so they're useful even when run
locally) and asserts a generous upper bound — they catch *structural*
regressions (O(N²) loops, missing batching, sync flushes per call) but
not normal hardware variance.

Stage 3 follow-up: ``scripts/perf_baseline.py`` snapshots these numbers
to ``tests/perf/baselines/`` so CI can compare across versions.

Budgets (deliberately loose):
  - recall p50 < 200ms (CLAUDE.md p50 < 50ms is the production
    target; this is a CI-friendly 4× headroom for stub embedder
    + small corpus startup overhead)
  - recall p99 < 500ms
  - ingest > 50 docs/sec
  - cold startup < 30s (empty DB, no FAISS to reload)
  - warm startup < 60s (DB with 200 docs to reload)
  - compact < 30s (200-doc corpus)
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

        # Loose CI bounds. Local p50 typically < 20ms.
        assert p50 < 200.0, f"p50={p50:.1f}ms > 200ms budget"
        assert p99 < 500.0, f"p99={p99:.1f}ms > 500ms budget"
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
        assert throughput > 50.0, (
            f"ingest throughput {throughput:.1f} docs/sec < 50 docs/sec floor"
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
