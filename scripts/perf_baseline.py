"""Capture a perf baseline snapshot to ``tests/perf/baselines/``.

Runs the same measurement loops as ``tests/perf/test_tier6_performance.py``
but writes the numbers to a JSON file instead of asserting bounds. Use
this when a structural change should be remeasured (e.g. a new
optimisation, a config default tweak, or a model upgrade).

The output filename encodes ``<git_sha>_<UTC_timestamp>.json`` so
multiple baselines coexist; the most recent two can be diffed with
``scripts/perf_diff.py``.

Isolated from the production DB by default (``--data-dir /tmp/...``).

Usage::

    python scripts/perf_baseline.py
    python scripts/perf_baseline.py --label phase-l-stage-1
    python scripts/perf_baseline.py --corpus-size 500 --recall-calls 200
"""
from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
import time
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from gaottt.config import GaOTTTConfig  # noqa: E402
from gaottt.index.bm25_index import BM25Index  # noqa: E402
from gaottt.index.faiss_index import FaissIndex  # noqa: E402
from gaottt.store.cache import CacheLayer  # noqa: E402
from gaottt.store.sqlite_store import SqliteStore  # noqa: E402
from gaottt.core.engine import GaOTTTEngine  # noqa: E402

from tests.perf._helpers import StubEmbedder  # noqa: E402


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = int(round((pct / 100.0) * (len(s) - 1)))
    return s[k]


def _git_sha() -> str:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=_PROJECT_ROOT, stderr=subprocess.DEVNULL,
        )
        return out.decode().strip()
    except Exception:
        return "nogit"


def _make_engine(data_dir: Path) -> GaOTTTEngine:
    config = GaOTTTConfig(
        data_dir=str(data_dir),
        db_path=str(data_dir / "perf.db"),
        faiss_index_path=str(data_dir / "perf.faiss"),
        virtual_faiss_index_path=str(data_dir / "perf.virtual.faiss"),
        virtual_faiss_enabled=True,
        hybrid_bm25_enabled=True,
        wave_initial_k=3,
        wave_seed_mass_alpha=0.0,
        wave_dynamic_k_enabled=False,
        genesis_kick_enabled=False,
        supernova_enabled=False,
        dream_enabled=False,
        faiss_save_interval_seconds=0.0,
        virtual_faiss_save_interval_seconds=0.0,
        flush_interval_seconds=0.05,
        persona_boost_enabled=False,
        mass_conservation_enabled=False,
        mass_bh_enabled=False,
    )
    embedder = StubEmbedder(dim=config.embedding_dim)
    return GaOTTTEngine(
        config=config,
        embedder=embedder,
        faiss_index=FaissIndex(dimension=config.embedding_dim),
        cache=CacheLayer(
            flush_interval=config.flush_interval_seconds,
            flush_threshold=config.flush_threshold,
        ),
        store=SqliteStore(db_path=config.db_path),
        virtual_faiss_index=FaissIndex(dimension=config.embedding_dim),
        bm25_index=BM25Index(
            k1=config.bm25_k1, b=config.bm25_b, tokenizer=config.bm25_tokenizer,
        ),
    )


async def _measure(args) -> dict:
    metrics: dict = {}
    data_dir = Path(args.data_dir).expanduser()
    data_dir.mkdir(parents=True, exist_ok=True)
    # Wipe leftovers from a prior run so cold metrics are honest.
    for f in data_dir.iterdir():
        if f.is_file():
            f.unlink()

    # --- Cold startup
    eng_cold = _make_engine(data_dir)
    t0 = time.perf_counter()
    await eng_cold.startup()
    metrics["cold_startup_seconds"] = time.perf_counter() - t0
    try:
        # --- Ingest throughput
        docs = [{"content": f"perf doc {i} body lorem ipsum"} for i in range(args.corpus_size)]
        t0 = time.perf_counter()
        await eng_cold.index_documents(docs)
        elapsed = time.perf_counter() - t0
        metrics["ingest_seconds"] = elapsed
        metrics["ingest_docs_per_sec"] = args.corpus_size / elapsed if elapsed > 0 else float("inf")

        # --- Recall latency (warm-up, then measure)
        for _ in range(5):
            await eng_cold.query(text="perf doc 0", top_k=5)

        latencies_ms: list[float] = []
        for i in range(args.recall_calls):
            t0 = time.perf_counter()
            await eng_cold.query(text=f"perf doc {i % 50}", top_k=5)
            latencies_ms.append((time.perf_counter() - t0) * 1000.0)
        metrics["recall_p50_ms"] = _percentile(latencies_ms, 50)
        metrics["recall_p95_ms"] = _percentile(latencies_ms, 95)
        metrics["recall_p99_ms"] = _percentile(latencies_ms, 99)
        metrics["recall_calls"] = args.recall_calls

        # --- Compact
        t0 = time.perf_counter()
        await eng_cold.compact(rebuild_faiss=True)
        metrics["compact_seconds"] = time.perf_counter() - t0

        await eng_cold.cache.flush_to_store(eng_cold.store)
    finally:
        await eng_cold.shutdown()

    # --- Warm startup (corpus_size docs already persisted)
    eng_warm = _make_engine(data_dir)
    t0 = time.perf_counter()
    await eng_warm.startup()
    metrics["warm_startup_seconds"] = time.perf_counter() - t0
    metrics["warm_startup_corpus_size"] = args.corpus_size
    try:
        metrics["faiss_size_after_warm"] = eng_warm.faiss_index.size
        metrics["bm25_size_after_warm"] = (
            eng_warm.bm25_index.size if eng_warm.bm25_index else 0
        )
    finally:
        await eng_warm.shutdown()

    return metrics


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data-dir", default="/tmp/gaottt-perf-baseline")
    parser.add_argument("--corpus-size", type=int, default=200)
    parser.add_argument("--recall-calls", type=int, default=100)
    parser.add_argument("--label", default="", help="Short label appended to filename for context")
    parser.add_argument("--out-dir", default=str(_PROJECT_ROOT / "tests" / "perf" / "baselines"))
    args = parser.parse_args(argv)

    metrics = asyncio.run(_measure(args))

    out_dir = Path(args.out_dir).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    sha = _git_sha()
    label = f"_{args.label}" if args.label else ""
    out_path = out_dir / f"{ts}_{sha}{label}.json"

    payload = {
        "captured_at": ts,
        "git_sha": sha,
        "label": args.label,
        "corpus_size": args.corpus_size,
        "recall_calls": args.recall_calls,
        "metrics": metrics,
    }
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    print(f"Baseline written to {out_path}")
    print(json.dumps(metrics, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
