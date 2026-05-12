#!/usr/bin/env python3
"""Aggregate GaOTTT Phase 2 results across the 2x2 factorial design.

Walks the results directory, loads every meta.json, and prints:
  1. Cell-by-cell pass-rate matrix (scenario × model)
  2. Tool-call distribution per model (M1)
  3. 2x2 factorial marginal effects + interaction on pass/tokens/cost/latency
  4. Token & cost totals per model

Handles partial data gracefully — safe to run while the sweep is still going.

Usage:
    .venv/bin/python scripts/eval_aggregate.py
    .venv/bin/python scripts/eval_aggregate.py --results-root /tmp/gaottt-eval-results
    .venv/bin/python scripts/eval_aggregate.py --date 2026-04-25
    .venv/bin/python scripts/eval_aggregate.py --json > summary.json
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date as _date
from pathlib import Path
from typing import Any, Callable

DEFAULT_RESULTS_ROOT = Path("/tmp/gaottt-eval-results")

# Factorial design: map each model slug to (architecture, family)
MODEL_DESIGN: dict[str, tuple[str, str]] = {
    "openrouter/google/gemma-4-31b-it":     ("dense", "Gemma"),
    "openrouter/google/gemma-4-26b-a4b-it": ("MoE",   "Gemma"),
    "openrouter/qwen/qwen3.5-27b":          ("dense", "Qwen"),
    "openrouter/qwen/qwen3.5-35b-a3b":      ("MoE",   "Qwen"),
}

SHORT_NAME = {
    "openrouter/google/gemma-4-31b-it":     "gem4-31b",
    "openrouter/google/gemma-4-26b-a4b-it": "gem4-26b-a4b",
    "openrouter/qwen/qwen3.5-27b":          "qwen3.5-27b",
    "openrouter/qwen/qwen3.5-35b-a3b":      "qwen3.5-35b-a3b",
}


@dataclass
class Cell:
    model: str
    scenario: str
    runs: list[dict[str, Any]]  # list of meta dicts

    @property
    def n(self) -> int:
        return len(self.runs)

    @property
    def pass_rate(self) -> float | None:
        with_require = [r for r in self.runs if r.get("overall_pass") is not None]
        if not with_require:
            return None
        passed = sum(1 for r in with_require if r["overall_pass"])
        return passed / len(with_require)

    def avg(self, fn: Callable[[dict[str, Any]], float | None]) -> float | None:
        vals = [v for v in (fn(r) for r in self.runs) if v is not None]
        return statistics.mean(vals) if vals else None


def discover_runs(root: Path, target_date: str | None) -> list[Cell]:
    """Find all meta.json files and bucket them into cells."""
    cells_by_key: dict[tuple[str, str], list[dict]] = defaultdict(list)

    if not root.exists():
        return []

    date_dirs = [root / target_date] if target_date else sorted(root.iterdir())
    for date_dir in date_dirs:
        if not date_dir.is_dir():
            continue
        for meta_path in date_dir.rglob("meta.json"):
            try:
                meta = json.loads(meta_path.read_text())
            except (json.JSONDecodeError, OSError):
                continue
            model = meta.get("model", "?")
            scenario = meta.get("scenario", "?")
            cells_by_key[(model, scenario)].append(meta)

    return [Cell(model=m, scenario=s, runs=runs)
            for (m, s), runs in sorted(cells_by_key.items())]


# -------------------------------------------------------------- metric extractors

def _total_tokens(meta: dict) -> int | None:
    t = meta.get("total_tokens") or {}
    if not t:
        return None
    return sum(v for v in t.values() if isinstance(v, (int, float)))


def _total_cost(meta: dict) -> float | None:
    c = meta.get("total_cost")
    return float(c) if c is not None else None


def _total_latency_ms(meta: dict) -> int | None:
    turns = meta.get("turns") or []
    if not turns:
        return None
    return sum(int(t.get("latency_ms", 0)) for t in turns)


def _unique_tools(meta: dict) -> int | None:
    turns = meta.get("turns") or []
    tools: set[str] = set()
    for t in turns:
        for c in t.get("tool_calls", []):
            tools.add(c.get("tool", ""))
    return len(tools) if turns else None


def _pass_as_float(meta: dict) -> float | None:
    p = meta.get("overall_pass")
    if p is None:
        return None
    return 1.0 if p else 0.0


# ------------------------------------------------------------------ reporters

def report_pass_matrix(cells: list[Cell], models: list[str], scenarios: list[str]) -> None:
    print("\n── Pass rate matrix (scenario × model) ──────────────────────────────")
    col_w = 16
    header = f"{'scenario':<10}" + "".join(f"{SHORT_NAME.get(m, m[:15]):<{col_w}}" for m in models)
    print(header)
    print("-" * len(header))
    by_key = {(c.model, c.scenario): c for c in cells}
    for s in scenarios:
        row = f"{s:<10}"
        for m in models:
            c = by_key.get((m, s))
            if c is None:
                row += f"{'--':<{col_w}}"
            elif c.pass_rate is None:
                row += f"{'obs×' + str(c.n):<{col_w}}"  # observe-only, no require
            else:
                pct = f"{int(c.pass_rate * 100)}% ({c.n})"
                row += f"{pct:<{col_w}}"
        print(row)
    print("  (legend: XX% (N runs); obs×N = observe-only scenario with N runs; -- = missing)")


def report_tool_distribution(cells: list[Cell], models: list[str]) -> None:
    print("\n── Tool call distribution (M1) per model ─────────────────────────────")
    per_model: dict[str, Counter] = defaultdict(Counter)
    for c in cells:
        for run in c.runs:
            for turn in run.get("turns", []):
                for call in turn.get("tool_calls", []):
                    tool = call.get("tool", "?")
                    per_model[c.model][tool] += 1

    all_tools = sorted({t for ctr in per_model.values() for t in ctr})
    if not all_tools:
        print("  (no tool calls observed yet)")
        return

    col_w = 16
    header = f"{'tool':<28}" + "".join(f"{SHORT_NAME.get(m, m[:15]):<{col_w}}" for m in models)
    print(header)
    print("-" * len(header))
    for tool in all_tools:
        row = f"{tool:<28}"
        for m in models:
            row += f"{per_model[m].get(tool, 0):<{col_w}}"
        print(row)


def report_factorial(cells: list[Cell], label: str,
                     fn: Callable[[dict], float | None],
                     fmt: str = ".3f") -> None:
    """2x2 factorial marginal effects for a scalar metric."""
    # Aggregate per (architecture, family) — averages across scenarios + runs
    cell_means: dict[tuple[str, str], list[float]] = defaultdict(list)
    for c in cells:
        design = MODEL_DESIGN.get(c.model)
        if design is None:
            continue
        avg = c.avg(fn)
        if avg is not None:
            cell_means[design].append(avg)

    if not cell_means:
        print(f"\n── Factorial on {label} ─── (no data)")
        return

    grid: dict[tuple[str, str], float] = {
        k: statistics.mean(v) for k, v in cell_means.items()
    }

    print(f"\n── Factorial on {label} ────────────────────────────────────────────")
    print(f"  {'':>10} {'Gemma':>14} {'Qwen':>14} {'row avg':>14}")
    row_avgs: dict[str, float] = {}
    for arch in ("dense", "MoE"):
        vals = [grid.get((arch, fam)) for fam in ("Gemma", "Qwen")]
        present = [v for v in vals if v is not None]
        row_avg = statistics.mean(present) if present else None
        row_avgs[arch] = row_avg if row_avg is not None else float("nan")
        cells_str = []
        for v in vals:
            cells_str.append(f"{v:>14{fmt}}" if v is not None else f"{'--':>14}")
        avg_str = f"{row_avg:>14{fmt}}" if row_avg is not None else f"{'--':>14}"
        print(f"  {arch:>10} {cells_str[0]} {cells_str[1]} {avg_str}")

    col_avgs: dict[str, float] = {}
    col_strs: list[str] = []
    for fam in ("Gemma", "Qwen"):
        vals = [grid.get((arch, fam)) for arch in ("dense", "MoE")]
        present = [v for v in vals if v is not None]
        col_avg = statistics.mean(present) if present else None
        col_avgs[fam] = col_avg if col_avg is not None else float("nan")
        col_strs.append(f"{col_avg:>14{fmt}}" if col_avg is not None else f"{'--':>14}")
    print(f"  {'col avg':>10} {col_strs[0]} {col_strs[1]}")

    # Marginal effects
    if all(v == v for v in row_avgs.values()):  # no NaN
        arch_eff = row_avgs["dense"] - row_avgs["MoE"]
        print(f"  Architecture effect (dense − MoE): {arch_eff:+{fmt}}")
    if all(v == v for v in col_avgs.values()):
        fam_eff = col_avgs["Gemma"] - col_avgs["Qwen"]
        print(f"  Family effect       (Gemma − Qwen): {fam_eff:+{fmt}}")

    # Interaction: (Gemma_dense − Gemma_MoE) − (Qwen_dense − Qwen_MoE)
    try:
        gemma_d = grid[("dense", "Gemma")]
        gemma_m = grid[("MoE", "Gemma")]
        qwen_d = grid[("dense", "Qwen")]
        qwen_m = grid[("MoE", "Qwen")]
        inter = (gemma_d - gemma_m) - (qwen_d - qwen_m)
        print(f"  Interaction (family × arch):       {inter:+{fmt}}")
    except KeyError:
        pass


def report_totals(cells: list[Cell], models: list[str]) -> None:
    print("\n── Per-model totals (across all runs) ────────────────────────────────")
    header = f"{'model':<20} {'runs':>6} {'pass':>8} {'tokens':>10} {'cost $':>10} {'latency s':>12}"
    print(header)
    print("-" * len(header))
    by_model: dict[str, list[Cell]] = defaultdict(list)
    for c in cells:
        by_model[c.model].append(c)
    for m in models:
        mcells = by_model.get(m, [])
        runs = sum(c.n for c in mcells)
        pass_rates = [c.pass_rate for c in mcells if c.pass_rate is not None]
        pass_avg = statistics.mean(pass_rates) if pass_rates else None
        tok = sum(_total_tokens(r) or 0 for c in mcells for r in c.runs)
        cost = sum(_total_cost(r) or 0 for c in mcells for r in c.runs)
        lat = sum((_total_latency_ms(r) or 0) for c in mcells for r in c.runs) / 1000
        pass_str = f"{int(pass_avg*100)}%" if pass_avg is not None else "-"
        print(f"{SHORT_NAME.get(m, m[:19]):<20} {runs:>6} {pass_str:>8} {tok:>10} {cost:>10.4f} {lat:>12.1f}")


# ---------------------------------------------------------------------- JSON

def as_json(cells: list[Cell]) -> dict[str, Any]:
    out: dict[str, Any] = {
        "total_runs": sum(c.n for c in cells),
        "total_cells": len(cells),
        "cells": [],
    }
    for c in cells:
        out["cells"].append({
            "model": c.model,
            "scenario": c.scenario,
            "n_runs": c.n,
            "pass_rate": c.pass_rate,
            "avg_tokens": c.avg(_total_tokens),
            "avg_cost": c.avg(_total_cost),
            "avg_latency_ms": c.avg(_total_latency_ms),
            "avg_unique_tools": c.avg(_unique_tools),
        })
    return out


# ------------------------------------------------------------------------ main

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--results-root", type=Path, default=DEFAULT_RESULTS_ROOT)
    ap.add_argument("--date", default=None, help="YYYY-MM-DD (default: all dates)")
    ap.add_argument("--json", action="store_true", help="emit JSON instead of tables")
    args = ap.parse_args()

    cells = discover_runs(args.results_root, args.date)
    if not cells:
        print(f"No runs found in {args.results_root}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(as_json(cells), ensure_ascii=False, indent=2))
        return 0

    total_runs = sum(c.n for c in cells)
    print(f"Loaded {total_runs} runs across {len(cells)} cells from {args.results_root}")
    if args.date:
        print(f"  (filtered to date {args.date})")

    models = list(MODEL_DESIGN.keys())
    scenarios = sorted({c.scenario for c in cells})

    report_pass_matrix(cells, models, scenarios)
    report_tool_distribution(cells, models)
    report_totals(cells, models)

    report_factorial(cells, "pass rate", _pass_as_float, ".2f")
    report_factorial(cells, "avg tokens per run", _total_tokens, ",.0f")
    report_factorial(cells, "avg cost per run ($)", _total_cost, ".4f")
    report_factorial(cells, "avg latency per run (ms)", _total_latency_ms, ",.0f")
    report_factorial(cells, "avg unique tools per run", _unique_tools, ".2f")

    return 0


if __name__ == "__main__":
    sys.exit(main())
