"""Stage 7.1 cluster_key coverage diagnostic — accurate (uses live cache).

The naive way to check coverage is to query
``json_extract(metadata, '$.original_id')`` directly. THAT IS WRONG —
``SqliteStore.get_all_originals`` uses ``COALESCE(original_id, file_path)``
so chunked file ingests (which set ``file_path`` only) ARE clustered.

The 2026-05-27 GLM review investigation (Plans-Lens-Hygiene Stage 2)
fell into this exact trap: a raw-SQL scan reported "file source has 0%
cluster_key coverage" but the live engine cache shows 100%. This script
talks to the live cache (via the same maps the engine uses at retrieval
time) so the numbers it prints are the numbers anti-hub actually sees.

Output:
  1. Per-source cluster_key coverage from the live cache
     (uses the same ``_cluster_key_for`` engine.cache wires up)
  2. Per-source cluster size distribution
     (max / p95 / singleton count — helps see where anti-hub will or
     won't structurally help: big clusters benefit, all-singleton
     sources like ``tweet`` cannot be helped by clustering alone)

Usage::

    .venv/bin/python scripts/diag_cluster_coverage.py
    .venv/bin/python scripts/diag_cluster_coverage.py --data-dir /path/to/data
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

# Defer engine import until after env setup
def _add_repo_to_path() -> None:
    here = Path(__file__).resolve()
    sys.path.insert(0, str(here.parent.parent))


async def main_async(args: argparse.Namespace) -> None:
    if args.data_dir:
        os.environ["GAOTTT_DATA_DIR"] = str(Path(args.data_dir).resolve())

    from gaottt.config import GaOTTTConfig
    from gaottt.services.runtime import build_engine
    from gaottt.services.memory import _cluster_key_for

    cfg = GaOTTTConfig.from_config_file()
    engine = build_engine(cfg)
    await engine.startup()
    try:
        cache = engine.cache
        ck = _cluster_key_for(cache)

        active = [s for s in cache.get_all_nodes() if not s.is_archived]
        print(f"Active nodes: {len(active):,}")

        src_by_id = getattr(cache, "source_by_id", {})

        # Per-source coverage
        coverage: dict[str, list[int]] = {}  # src -> [total, with_key]
        for s in active:
            src = src_by_id.get(s.id, "(missing)")
            coverage.setdefault(src, [0, 0])
            coverage[src][0] += 1
            if ck(s.id) is not None:
                coverage[src][1] += 1

        print()
        print("Per-source cluster_key coverage (live cache):")
        print(f"  {'source':<22} {'total':>7} {'w/key':>7} {'%':>6}")
        for src, (n, k) in sorted(coverage.items(), key=lambda kv: -kv[1][0]):
            pct = 100 * k / n if n else 0.0
            print(f"  {src:<22} {n:>7} {k:>7} {pct:>5.1f}%")

        # Per-source cluster-size distribution — bigger clusters = better
        # anti-hub leverage. all-singleton sources cannot be helped by clustering.
        print()
        print("Per-source cluster SIZE distribution (where coverage > 0):")
        print(f"  {'source':<22} {'clusters':>9} {'max':>6} {'p95':>6} {'p50':>6} {'singletons':>11}")
        # Build cluster_key → count per source
        per_source_keys: dict[str, dict[str, int]] = {}
        for s in active:
            src = src_by_id.get(s.id, "(missing)")
            key = ck(s.id)
            if key is None:
                continue
            per_source_keys.setdefault(src, {})
            per_source_keys[src][key] = per_source_keys[src].get(key, 0) + 1

        for src, key_counts in sorted(per_source_keys.items(), key=lambda kv: -sum(kv[1].values())):
            sizes = sorted(key_counts.values(), reverse=True)
            if not sizes:
                continue
            n_clusters = len(sizes)
            max_sz = sizes[0]
            # top 5% (largest) — index 5%
            p95 = sizes[max(0, int(len(sizes) * 0.05) - 1)]
            # median
            p50 = sizes[len(sizes) // 2]
            singletons = sum(1 for sz in sizes if sz == 1)
            print(f"  {src:<22} {n_clusters:>9} {max_sz:>6} {p95:>6} {p50:>6} {singletons:>11}")

        # Verdict line — anti-hub structural usefulness summary
        print()
        print("Interpretation:")
        print("  - sources with max>>1 are where Stage 7.1 anti-hub structurally")
        print("    helps (file/openai/like/claude-web in production)")
        print("  - sources with mostly singletons (tweet, mostly-agent) get no")
        print("    cluster help — vocabulary-similar singletons need BM25/RRF")
        print("    diversification (Phase L Stage 1) not cluster anti-hub.")
    finally:
        await engine.shutdown()


def main() -> None:
    _add_repo_to_path()
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--data-dir", default=None,
        help="GaOTTT data dir (defaults to the configured GAOTTT_DATA_DIR / "
             "~/.local/share/gaottt)",
    )
    args = parser.parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
