"""Capture a perf baseline snapshot to ``tests/perf/baselines/``.

Runs the same measurement loops as ``tests/perf/test_tier6_performance.py``
but writes the numbers to a JSON file instead of asserting bounds. Use
this when implementing a hypothesis-driven change and you want a
before/after delta of real-RURI performance (the 仮説 → 実装 → 検証
loop's measurement step).

The output filename encodes ``<UTC_timestamp>_<git_sha>[_<label>].json``
so multiple baselines coexist; the most recent two can be diffed with
``scripts/perf_diff.py``.

Uses **real RURI v3 310m** via the shared ``tests/perf/_helpers``
factory — every metric reflects production-grade behaviour, not a
stub-embedder lower bound. The data directory is isolated from the
production DB by default.

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

from tests.perf._helpers import make_engine  # noqa: E402


def _make_engine_with_overrides(data_dir: Path, overrides: dict | None):
    """Wrap ``make_engine`` so CLI ``--config-overrides`` (JSON) can flip
    individual config fields (e.g. ``mass_anchor_extra_strength``) without
    touching the user's ~/.config/gaottt/config.json or shifting defaults.
    """
    if not overrides:
        return make_engine(data_dir)
    return make_engine(data_dir, **overrides)


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


async def _measure(args) -> dict:
    metrics: dict = {}
    data_dir = Path(args.data_dir).expanduser()
    data_dir.mkdir(parents=True, exist_ok=True)
    # Wipe leftovers from a prior run so cold metrics are honest.
    for f in data_dir.iterdir():
        if f.is_file():
            f.unlink()

    overrides = json.loads(args.config_overrides) if args.config_overrides else {}

    # --- Cold startup
    eng_cold = _make_engine_with_overrides(data_dir, overrides)
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
    eng_warm = _make_engine_with_overrides(data_dir, overrides)
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
    parser.add_argument("--data-dir", default=str(_PROJECT_ROOT / ".perf-baseline-tmp"))
    parser.add_argument("--corpus-size", type=int, default=200)
    parser.add_argument("--recall-calls", type=int, default=100)
    parser.add_argument("--label", default="", help="Short label appended to filename for context")
    parser.add_argument("--out-dir", default=str(_PROJECT_ROOT / "tests" / "perf" / "baselines"))
    parser.add_argument(
        "--config-overrides",
        default="",
        help=(
            'JSON dict of GaOTTTConfig field overrides, e.g. '
            '\'{"mass_anchor_extra_strength": 1.0}\'. Applied to both the '
            "cold-startup engine and the warm-startup engine so the metric "
            "comparison is fair."
        ),
    )
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
        "config_overrides": json.loads(args.config_overrides) if args.config_overrides else {},
        "metrics": metrics,
    }
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    print(f"Baseline written to {out_path}")
    print(json.dumps(metrics, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
