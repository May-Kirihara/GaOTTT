"""Diff two perf baselines and flag metrics that regressed.

Picks two snapshot files from ``tests/perf/baselines/`` (or any two
files passed explicitly) and prints a table of metric deltas. Exit
code is 1 if any metric breached its allowed-regression threshold —
useful for CI gating.

Usage::

    # Most recent vs second-most-recent
    python scripts/perf_diff.py

    # Explicit pair
    python scripts/perf_diff.py before.json after.json

    # Tighter / looser regression budget (default 25%)
    python scripts/perf_diff.py --threshold 0.10
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
BASELINES_DIR = _PROJECT_ROOT / "tests" / "perf" / "baselines"


# Metric → (direction, label)
# direction: "higher_better" or "lower_better"
METRIC_DIRECTION = {
    "cold_startup_seconds": "lower_better",
    "warm_startup_seconds": "lower_better",
    "ingest_seconds": "lower_better",
    "ingest_docs_per_sec": "higher_better",
    "recall_p50_ms": "lower_better",
    "recall_p95_ms": "lower_better",
    "recall_p99_ms": "lower_better",
    "compact_seconds": "lower_better",
}


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _pick_recent_pair() -> tuple[Path, Path]:
    if not BASELINES_DIR.exists():
        raise SystemExit(f"No baselines dir at {BASELINES_DIR}; run perf_baseline.py first")
    files = sorted(BASELINES_DIR.glob("*.json"))
    if len(files) < 2:
        raise SystemExit(f"Need ≥2 snapshots in {BASELINES_DIR}; have {len(files)}")
    return files[-2], files[-1]


def _delta_pct(before: float, after: float, direction: str) -> tuple[float, bool]:
    """Return (delta_pct, regressed_bool).

    ``delta_pct`` is signed relative to ``before`` (positive = "after larger").
    ``regressed_bool`` accounts for direction.
    """
    if before == 0:
        return (float("inf") if after > 0 else 0.0), False
    delta = (after - before) / abs(before)
    if direction == "lower_better":
        regressed = after > before
    else:
        regressed = after < before
    return delta, regressed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("before", nargs="?", help="Earlier snapshot (defaults to second-most-recent)")
    parser.add_argument("after", nargs="?", help="Later snapshot (defaults to most-recent)")
    parser.add_argument("--threshold", type=float, default=0.25, help="Allowed regression fraction (default 0.25 = 25%%)")
    args = parser.parse_args(argv)

    if args.before and args.after:
        before_path = Path(args.before)
        after_path = Path(args.after)
    else:
        before_path, after_path = _pick_recent_pair()

    before = _load(before_path)
    after = _load(after_path)

    print(f"before: {before_path.name}  ({before.get('git_sha', '?')}, label={before.get('label') or '-'})")
    print(f"after:  {after_path.name}  ({after.get('git_sha', '?')}, label={after.get('label') or '-'})")
    print()

    before_m = before["metrics"]
    after_m = after["metrics"]

    regressed_any = False
    rows: list[tuple[str, float, float, float, str]] = []
    for metric, direction in METRIC_DIRECTION.items():
        if metric not in before_m or metric not in after_m:
            continue
        b = float(before_m[metric])
        a = float(after_m[metric])
        delta, regressed = _delta_pct(b, a, direction)
        flag = ""
        if regressed and abs(delta) > args.threshold:
            flag = f"REGRESS (>{args.threshold:.0%})"
            regressed_any = True
        elif regressed:
            flag = "slower / lower (within budget)"
        elif abs(delta) > args.threshold:
            flag = "improved >threshold ✨"
        rows.append((metric, b, a, delta, flag))

    width = max(len(r[0]) for r in rows) if rows else 12
    print(f"{'metric':<{width}}  {'before':>12}  {'after':>12}  {'delta':>9}  flag")
    print("-" * (width + 12 + 12 + 9 + 30))
    for metric, b, a, delta, flag in rows:
        print(f"{metric:<{width}}  {b:>12.4f}  {a:>12.4f}  {delta:>+8.1%}  {flag}")

    return 1 if regressed_any else 0


if __name__ == "__main__":
    sys.exit(main())
