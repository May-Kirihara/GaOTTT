"""Stage 6.2 baseline — dormant percentile distribution diagnostic.

Read-only inspection of a GaOTTT data directory to decide whether the
absolute ``dormant_mass_threshold=2.0`` should become a percentile of the
active corpus mass distribution.

Computes, for each candidate threshold (a fixed 2.0 AND a configurable
percentile set of the active mass distribution), how many self-authored
memos satisfy the full dormant triple:
  - age (now - last_access) >= --age-days     (default 30)
  - source in --sources                       (default: agent value intention commitment note reference)
  - mass <= threshold                         (per-row)
  - NOT archived

The script does NOT load the embedder — only SqliteStore — so it runs in
under a second even on a 30k-memo production DB.

Usage::

    .venv/bin/python scripts/diag_dormant.py --data-dir /path/to/data
    .venv/bin/python scripts/diag_dormant.py --data-dir ./.diag-tmp --percentiles 10,20,30,50

Recommended workflow:
  1. Run against the production DB once (or a recent snapshot) to capture
     the current mass distribution and the dormant-candidate counts under
     several percentile floors.
  2. Pick a percentile that yields a meaningful (non-zero, non-flood)
     dormant pool — typically 5-15 candidates is enough for
     counter-importance sampling.
  3. That percentile becomes the default for ``dormant_mass_percentile``
     (Stage 6.2 implementation).
"""
from __future__ import annotations

import argparse
import asyncio
import statistics
import time
from pathlib import Path

from gaottt.store.sqlite_store import SqliteStore


DEFAULT_SOURCES = ("agent", "value", "intention", "commitment", "note", "reference")
DEFAULT_PERCENTILES = (10.0, 20.0, 30.0, 50.0)
ABSOLUTE_THRESHOLD = 2.0  # current default ``dormant_mass_threshold``


def _percentile(sorted_vals: list[float], p: float) -> float:
    """Linear-interp percentile of a SORTED list. p in [0, 100]."""
    if not sorted_vals:
        return 0.0
    if p <= 0:
        return sorted_vals[0]
    if p >= 100:
        return sorted_vals[-1]
    pos = (p / 100.0) * (len(sorted_vals) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = pos - lo
    return sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac


async def main_async(args: argparse.Namespace) -> None:
    data_dir = Path(args.data_dir).resolve()
    db_path = data_dir / "gaottt.db"
    if not db_path.exists():
        raise SystemExit(f"DB not found: {db_path}")
    print(f"Reading {db_path}")

    store = SqliteStore(db_path=str(db_path))
    await store.initialize()
    try:
        states = await store.get_all_node_states()
        sources_map = await store.get_all_sources()

        active = [s for s in states if not s.is_archived]
        total = len(states)
        archived = total - len(active)
        print(
            f"Active: {len(active):,}   Archived: {archived:,}   "
            f"Total: {total:,}"
        )

        # ---- Mass distribution over active ----
        masses = sorted(s.mass for s in active)
        if not masses:
            raise SystemExit("No active nodes — cannot derive distribution")
        print(
            "\nActive mass distribution:\n"
            f"  min={masses[0]:.3f}  max={masses[-1]:.3f}  "
            f"mean={statistics.fmean(masses):.3f}  median={_percentile(masses, 50):.3f}"
        )
        for p in DEFAULT_PERCENTILES:
            print(f"  p{p:>5.1f} = {_percentile(masses, p):.3f}")

        # ---- Dormant candidate counts ----
        sources_filter = set(args.sources)
        cutoff = time.time() - args.age_days * 86400.0
        # Filter to age + source first; mass is the per-threshold cut.
        prefiltered = [
            s for s in active
            if s.last_access <= cutoff
            and sources_map.get(s.id, "") in sources_filter
        ]
        print(
            f"\nPre-filter (age >= {args.age_days}d AND source in {sorted(sources_filter)}):\n"
            f"  {len(prefiltered):,} candidates"
        )

        # Each threshold = (label, value). Always include the absolute legacy.
        thresholds = [(f"abs {ABSOLUTE_THRESHOLD}", ABSOLUTE_THRESHOLD)]
        percentile_set = (
            [float(p) for p in args.percentiles.split(",")]
            if args.percentiles else list(DEFAULT_PERCENTILES)
        )
        for p in percentile_set:
            v = _percentile(masses, p)
            thresholds.append((f"p{p:.1f}", v))

        print("\nDormant candidate counts under each mass threshold:")
        print(f"  {'threshold':<14}  {'value':>9}  {'count':>7}  {'pct of pre-filter':>20}")
        for label, v in thresholds:
            n = sum(1 for s in prefiltered if s.mass <= v)
            pct = (n / len(prefiltered) * 100.0) if prefiltered else 0.0
            print(f"  {label:<14}  {v:>9.3f}  {n:>7}  {pct:>19.1f}%")

        # ---- Per-source breakdown at the recommended percentile ----
        # If user-supplied percentile list, take the smallest; else 20.
        recommend_p = min(percentile_set) if percentile_set else 20.0
        recommend_v = _percentile(masses, recommend_p)
        print(
            f"\nPer-source breakdown at p{recommend_p:.1f} (mass <= {recommend_v:.3f}):"
        )
        per_source: dict[str, int] = {}
        for s in prefiltered:
            if s.mass <= recommend_v:
                src = sources_map.get(s.id, "?")
                per_source[src] = per_source.get(src, 0) + 1
        if not per_source:
            print("  (no candidates at this threshold)")
        else:
            for src, n in sorted(per_source.items(), key=lambda kv: -kv[1]):
                print(f"  {src:<14}  {n:>6}")

        print(
            "\nInterpretation hint: pick the smallest percentile that yields "
            "5-15 dormant candidates for the per-call top_k (default 10) to "
            "have something to sample without flooding the gravity field."
        )
    finally:
        await store.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-dir", required=True, help="GaOTTT data dir (contains gaottt.db)")
    parser.add_argument(
        "--age-days", type=float, default=30.0,
        help="Idle age threshold in days (default 30)",
    )
    parser.add_argument(
        "--sources", nargs="+", default=list(DEFAULT_SOURCES),
        help="Source classes to count as self-authored (space-separated)",
    )
    parser.add_argument(
        "--percentiles", default="10,20,30,50",
        help="Comma-separated percentiles of active mass to evaluate "
             "(default 10,20,30,50)",
    )
    args = parser.parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
