"""Phase N candidate β — read-only dry-run projection on the active DB.

Loads node states (and per-id source metadata) directly from SQLite without
spinning up the engine, applies ``evaporate_mass`` once to every active
node under a user-chosen ``(ε, β, γ, τ_idle, τ_grace, floor)`` set, and
writes a markdown + JSON report comparing the *current* mass distribution
to the *projected post-sweep* one.

Safety contract:
  - **NO MUTATION** — only ``SELECT``-style reads. The script never imports
    the cache layer, never starts the engine's write-behind / sweep
    loops, never calls any ``set_*`` or ``save_*`` method.
  - Default data-dir comes from ``GaOTTTConfig.from_config_file()`` — same
    path as production, but only the SQLite file is read. FAISS files are
    not touched.
  - Output goes to ``./.phase-n-dry-run/`` (gitignored; create if missing).

Use this for Stage 1.5 readiness assessment:
  - Does the chosen ``(ε, β, γ)`` redistribute mass at the rate we want?
  - Do the right legacy hubs lose their attractor status?
  - Does Phase O Stage 5 dormant (mass ≤ ``dormant_mass_threshold``)
    repopulate to a non-empty pool?
  - Is total mass conservation reasonable, or does the rate apocalyptically
    drain the field?

Run a single config:

    .venv/bin/python scripts/phase_n_dry_run.py --label default

Sweep three configs in one pass (see ``--sweep`` for built-in presets):

    .venv/bin/python scripts/phase_n_dry_run.py --sweep
"""
from __future__ import annotations

import argparse
import asyncio
import json
import random
import statistics
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from gaottt.config import GaOTTTConfig
from gaottt.core.gravity import evaporate_mass
from gaottt.store.sqlite_store import SqliteStore


OUT_DIR = Path(".phase-n-dry-run")
TOP_K_HUB_REPORT = 20
TOP_K_LOSERS_REPORT = 20
DORMANT_MASS_GATE = 2.0   # matches Phase O Stage 5 default ``dormant_mass_threshold``


# --- Preset parameter sweep ---


@dataclass(frozen=True)
class Preset:
    label: str
    rate: float
    mass_exp: float
    time_exp: float
    idle_normalize_days: float
    grace_days: float
    floor: float


PRESETS: list[Preset] = [
    Preset("default",    rate=0.01,  mass_exp=1.5, time_exp=1.0, idle_normalize_days=30, grace_days=7, floor=1.0),
    Preset("conservative", rate=0.005, mass_exp=1.5, time_exp=1.0, idle_normalize_days=30, grace_days=7, floor=1.0),
    Preset("aggressive", rate=0.05,  mass_exp=1.5, time_exp=1.0, idle_normalize_days=30, grace_days=7, floor=1.0),
    Preset("heavy-hub-bias", rate=0.01, mass_exp=2.0, time_exp=1.0, idle_normalize_days=30, grace_days=7, floor=1.0),
    Preset("slow-idle-bias", rate=0.01, mass_exp=1.5, time_exp=2.0, idle_normalize_days=30, grace_days=7, floor=1.0),
]


def preset_to_config_overrides(p: Preset) -> dict[str, Any]:
    return dict(
        mass_evaporation_enabled=True,
        mass_evaporation_floor=p.floor,
        mass_evaporation_grace_seconds=p.grace_days * 86400.0,
        mass_evaporation_idle_normalize_seconds=p.idle_normalize_days * 86400.0,
        mass_evaporation_rate=p.rate,
        mass_evaporation_mass_exponent=p.mass_exp,
        mass_evaporation_time_exponent=p.time_exp,
    )


# --- Read-only loader ---


async def load_states_and_sources(
    base_config: GaOTTTConfig,
) -> tuple[list[Any], dict[str, str], dict[str, str]]:
    """Read every non-archived node's mass / last_access + per-id source.

    Returns (states, source_by_id, content_excerpt_by_id).
    """
    store = SqliteStore(db_path=base_config.db_path)
    await store.initialize()
    states = [s for s in await store.get_all_node_states() if not s.is_archived]
    sources = await store.get_all_sources()
    # Content excerpts only for hub-report rows we'll actually print.
    excerpts: dict[str, str] = {}
    return states, sources, excerpts


async def _content_excerpt(
    base_config: GaOTTTConfig, node_id: str, limit: int = 80,
) -> str:
    """Pull a short content excerpt for one node id (used for hub-report labels)."""
    store = SqliteStore(db_path=base_config.db_path)
    await store.initialize()
    doc = await store.get_document(node_id)
    if doc is None:
        return "(no document)"
    content = (doc.get("content") or "").replace("\n", " ").strip()
    if len(content) > limit:
        content = content[: limit - 1] + "…"
    return content


# --- Projection ---


@dataclass
class Projection:
    preset: Preset
    n_active: int
    before: list[tuple[str, float]]    # (id, mass) sorted by id (stable)
    after: list[tuple[str, float]]     # same order
    last_access_age_days: list[float]  # per-node t_idle in days
    sources: dict[str, str]

    @property
    def before_masses(self) -> list[float]:
        return [m for _, m in self.before]

    @property
    def after_masses(self) -> list[float]:
        return [m for _, m in self.after]


def project(
    config_overrides: dict[str, Any], base_config: GaOTTTConfig,
    states: list[Any], sources: dict[str, str], preset: Preset,
    simulate_aging_days: float = 0.0,
    aging_fraction: float = 0.0,
    aging_mass_bias: str = "random",
    rng_seed: int = 0xA10E,
) -> Projection:
    """Apply ``evaporate_mass`` to every node under the given config.

    ``simulate_aging_days`` + ``aging_fraction``: synthetic aging — pick
    ``aging_fraction`` of nodes and back-date their ``last_access`` by
    ``simulate_aging_days`` (within the projection only, never to disk).
    Used to ask "if a subset of the field cools down over N days, what
    would Phase N β drain off them?". ``aging_mass_bias``:
      - ``random``: pick the cohort uniformly at random
      - ``high-mass``: bias toward heavy nodes (simulates "legacy hubs
        stop getting recalled while small notes keep flowing")
      - ``low-mass``: bias toward light nodes (control)
    """
    cfg = GaOTTTConfig(**{**{f.name: getattr(base_config, f.name)
                             for f in base_config.__dataclass_fields__.values()},
                          **config_overrides})
    now = time.time()

    # Build a synthetic-aging map: id → adjusted last_access.
    adjusted_last_access: dict[str, float] = {}
    if aging_fraction > 0.0 and simulate_aging_days > 0.0:
        rng = random.Random(rng_seed)
        cohort_n = int(round(len(states) * aging_fraction))
        if aging_mass_bias == "high-mass":
            ranked = sorted(states, key=lambda s: s.mass, reverse=True)
            cohort = ranked[:cohort_n]
        elif aging_mass_bias == "low-mass":
            ranked = sorted(states, key=lambda s: s.mass)
            cohort = ranked[:cohort_n]
        else:
            cohort = rng.sample(states, cohort_n)
        shift = simulate_aging_days * 86400.0
        for s in cohort:
            adjusted_last_access[s.id] = s.last_access - shift

    before: list[tuple[str, float]] = []
    after: list[tuple[str, float]] = []
    ages_days: list[float] = []
    for state in states:
        before.append((state.id, state.mass))
        la = adjusted_last_access.get(state.id, state.last_access)
        new_mass = evaporate_mass(state.mass, la, now, cfg)
        after.append((state.id, new_mass))
        ages_days.append(max(0.0, (now - la) / 86400.0))
    return Projection(
        preset=preset, n_active=len(states),
        before=before, after=after,
        last_access_age_days=ages_days, sources=sources,
    )


# --- Reporting ---


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]
    s = sorted(values)
    idx = int(round((len(s) - 1) * (p / 100.0)))
    return s[idx]


def _distribution_row(label: str, masses: list[float]) -> dict[str, float]:
    if not masses:
        return {"label": label, "n": 0}
    return {
        "label": label,
        "n": len(masses),
        "min": min(masses),
        "p50": _percentile(masses, 50),
        "p90": _percentile(masses, 90),
        "p99": _percentile(masses, 99),
        "p99.9": _percentile(masses, 99.9),
        "max": max(masses),
        "mean": statistics.fmean(masses),
        "sum": sum(masses),
    }


async def summarize(
    proj: Projection, base_config: GaOTTTConfig,
) -> dict[str, Any]:
    """Build a JSON-serialisable summary of one projection."""
    before_by_id = dict(proj.before)
    after_by_id = dict(proj.after)

    # Top hubs by mass — before
    top_before = sorted(proj.before, key=lambda t: t[1], reverse=True)[:TOP_K_HUB_REPORT]
    top_after = sorted(proj.after, key=lambda t: t[1], reverse=True)[:TOP_K_HUB_REPORT]
    top_losers = sorted(
        ((nid, before_by_id[nid] - after_by_id[nid], before_by_id[nid], after_by_id[nid])
         for nid in before_by_id),
        key=lambda t: t[1], reverse=True,
    )[:TOP_K_LOSERS_REPORT]

    # Resolve content excerpts for those we report.
    excerpts: dict[str, str] = {}
    for nid, _ in top_before:
        excerpts[nid] = await _content_excerpt(base_config, nid)
    for nid, _ in top_after:
        if nid not in excerpts:
            excerpts[nid] = await _content_excerpt(base_config, nid)
    for nid, _, _, _ in top_losers:
        if nid not in excerpts:
            excerpts[nid] = await _content_excerpt(base_config, nid)

    # Dormant pool: mass ≤ DORMANT_MASS_GATE
    dormant_before = sum(1 for _, m in proj.before if m <= DORMANT_MASS_GATE)
    dormant_after = sum(1 for _, m in proj.after if m <= DORMANT_MASS_GATE)

    # Source-class breakdown — does any class get hit asymmetrically?
    source_totals_before: Counter[str] = Counter()
    source_totals_after: Counter[str] = Counter()
    source_counts: Counter[str] = Counter()
    for nid, m_b in proj.before:
        src = proj.sources.get(nid, "unknown")
        source_totals_before[src] += m_b
        source_totals_after[src] += after_by_id[nid]
        source_counts[src] += 1

    source_rows = []
    for src in sorted(source_counts):
        n = source_counts[src]
        tb = source_totals_before[src]
        ta = source_totals_after[src]
        source_rows.append({
            "source": src, "n": n,
            "mean_before": tb / n if n else 0.0,
            "mean_after":  ta / n if n else 0.0,
            "pct_drained": (1 - ta / tb) * 100.0 if tb > 0 else 0.0,
        })

    total_before = sum(m for _, m in proj.before)
    total_after = sum(m for _, m in proj.after)

    return {
        "preset": proj.preset.__dict__,
        "n_active": proj.n_active,
        "now_iso": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "mass_distribution": {
            "before": _distribution_row("before", proj.before_masses),
            "after":  _distribution_row("after",  proj.after_masses),
        },
        "conservation": {
            "total_mass_before": total_before,
            "total_mass_after":  total_after,
            "drained_total":     total_before - total_after,
            "drained_pct":       (1 - total_after / total_before) * 100.0 if total_before > 0 else 0.0,
        },
        "dormant_pool": {
            "gate": DORMANT_MASS_GATE,
            "count_before": dormant_before,
            "count_after":  dormant_after,
            "delta":        dormant_after - dormant_before,
        },
        "age_distribution_days": {
            "p50": _percentile(proj.last_access_age_days, 50),
            "p90": _percentile(proj.last_access_age_days, 90),
            "p99": _percentile(proj.last_access_age_days, 99),
            "max": max(proj.last_access_age_days) if proj.last_access_age_days else 0.0,
        },
        "top_hubs_before": [
            {"id": nid, "mass": m, "source": proj.sources.get(nid, "?"),
             "excerpt": excerpts.get(nid, "?")}
            for nid, m in top_before
        ],
        "top_hubs_after": [
            {"id": nid, "mass": m, "source": proj.sources.get(nid, "?"),
             "excerpt": excerpts.get(nid, "?")}
            for nid, m in top_after
        ],
        "top_losers": [
            {"id": nid, "delta": delta, "mass_before": mb, "mass_after": ma,
             "source": proj.sources.get(nid, "?"),
             "excerpt": excerpts.get(nid, "?")}
            for nid, delta, mb, ma in top_losers
        ],
        "by_source": source_rows,
    }


def render_markdown(summary: dict[str, Any]) -> str:
    p = summary["preset"]
    d = summary["mass_distribution"]
    c = summary["conservation"]
    dp = summary["dormant_pool"]
    age = summary["age_distribution_days"]

    lines = [
        f"# Phase N β dry-run — `{p['label']}`",
        "",
        f"- Active nodes: **{summary['n_active']:,}**",
        f"- Run at: {summary['now_iso']}",
        f"- Parameters: ε={p['rate']}, β={p['mass_exp']}, γ={p['time_exp']}, "
        f"τ_idle={p['idle_normalize_days']}d, τ_grace={p['grace_days']}d, floor={p['floor']}",
        "",
        "## Mass distribution",
        "",
        "| | n | min | p50 | p90 | p99 | p99.9 | max | mean | sum |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for row_label in ("before", "after"):
        row = d[row_label]
        lines.append(
            f"| {row['label']} | {row['n']:,} | {row['min']:.3f} | {row['p50']:.3f} | "
            f"{row['p90']:.3f} | {row['p99']:.3f} | {row['p99.9']:.3f} | {row['max']:.3f} | "
            f"{row['mean']:.3f} | {row['sum']:.1f} |"
        )

    lines += [
        "",
        "## Conservation (total mass)",
        "",
        f"- Before: **{c['total_mass_before']:.1f}**",
        f"- After:  **{c['total_mass_after']:.1f}**",
        f"- Drained: **{c['drained_total']:.1f}** ({c['drained_pct']:.2f}% of total)",
        "",
        "## Phase O Stage 5 dormant pool",
        "",
        f"Mass-gate ≤ {dp['gate']}:",
        "",
        f"- Before: **{dp['count_before']:,}** nodes",
        f"- After:  **{dp['count_after']:,}** nodes",
        f"- Delta:  **{dp['delta']:+,}** (positive = pool grew = dormant becomes surfaceable)",
        "",
        "## Idle age distribution (days since last_access)",
        "",
        f"- p50: {age['p50']:.1f}",
        f"- p90: {age['p90']:.1f}",
        f"- p99: {age['p99']:.1f}",
        f"- max: {age['max']:.1f}",
        "",
        "## Top mass-losers (cold hubs draining)",
        "",
        "| Δmass | before → after | source | excerpt |",
        "|---|---|---|---|",
    ]
    for row in summary["top_losers"]:
        lines.append(
            f"| {row['delta']:.3f} | {row['mass_before']:.3f} → {row['mass_after']:.3f} | "
            f"{row['source']} | {row['excerpt']} |"
        )

    lines += ["", "## Top hubs — before sweep", "", "| rank | mass | source | excerpt |", "|---|---|---|---|"]
    for i, row in enumerate(summary["top_hubs_before"], 1):
        lines.append(f"| {i} | {row['mass']:.3f} | {row['source']} | {row['excerpt']} |")

    lines += ["", "## Top hubs — after projected sweep", "", "| rank | mass | source | excerpt |", "|---|---|---|---|"]
    for i, row in enumerate(summary["top_hubs_after"], 1):
        lines.append(f"| {i} | {row['mass']:.3f} | {row['source']} | {row['excerpt']} |")

    lines += [
        "", "## By-source breakdown",
        "",
        "| source | n | mean before | mean after | % drained |",
        "|---|---|---|---|---|",
    ]
    for row in summary["by_source"]:
        lines.append(
            f"| {row['source']} | {row['n']:,} | {row['mean_before']:.3f} | "
            f"{row['mean_after']:.3f} | {row['pct_drained']:.2f}% |"
        )

    return "\n".join(lines) + "\n"


# --- Cross-preset comparison ---


def render_sweep_summary(summaries: list[dict[str, Any]]) -> str:
    lines = [
        "# Phase N β dry-run — sweep summary",
        "",
        f"- Active nodes: {summaries[0]['n_active']:,}",
        f"- Run at: {summaries[0]['now_iso']}",
        "",
        "| preset | ε | β | γ | drained % | dormant pool Δ | top1 mass before → after |",
        "|---|---|---|---|---|---|---|",
    ]
    for s in summaries:
        p = s["preset"]
        top1_before = s["top_hubs_before"][0]["mass"] if s["top_hubs_before"] else 0
        top1_after_for_same_id = next(
            (h["mass"] for h in s["top_hubs_after"]
             if h["id"] == s["top_hubs_before"][0]["id"]),
            None,
        ) if s["top_hubs_before"] else None
        top1_str = (
            f"{top1_before:.2f} → {top1_after_for_same_id:.2f}"
            if top1_after_for_same_id is not None else f"{top1_before:.2f} → ?"
        )
        lines.append(
            f"| `{p['label']}` | {p['rate']} | {p['mass_exp']} | {p['time_exp']} | "
            f"{s['conservation']['drained_pct']:.2f}% | "
            f"{s['dormant_pool']['delta']:+,} | {top1_str} |"
        )
    lines += [
        "",
        "個別 preset の詳細は `<label>.md` を参照。",
    ]
    return "\n".join(lines) + "\n"


# --- CLI ---


async def amain():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--label", default="default",
        help="Single-preset run. Picks from the built-in presets, or pass "
             "custom params to override (--rate / --mass-exp / --time-exp / "
             "--idle-normalize-days / --grace-days / --floor).",
    )
    parser.add_argument("--rate", type=float)
    parser.add_argument("--mass-exp", type=float)
    parser.add_argument("--time-exp", type=float)
    parser.add_argument("--idle-normalize-days", type=float)
    parser.add_argument("--grace-days", type=float)
    parser.add_argument("--floor", type=float)
    parser.add_argument(
        "--sweep", action="store_true",
        help="Run every built-in preset and emit a summary table.",
    )
    parser.add_argument(
        "--simulate-aging-days", type=float, default=0.0,
        help="Synthetic aging: back-date a cohort's last_access by this many "
             "days within the projection only. Use when the DB was reset "
             "recently and you want to project a future state.",
    )
    parser.add_argument(
        "--aging-fraction", type=float, default=0.0,
        help="Fraction of nodes to apply --simulate-aging-days to.",
    )
    parser.add_argument(
        "--aging-mass-bias", choices=("random", "high-mass", "low-mass"),
        default="random",
        help="Which nodes form the synthetic-aging cohort. ``high-mass`` "
             "simulates the legacy-hub-stop-being-recalled scenario.",
    )
    parser.add_argument(
        "--out-dir", default=str(OUT_DIR),
        help="Output directory (default: ./.phase-n-dry-run).",
    )
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    base_config = GaOTTTConfig.from_config_file()
    print(f"Loading active node states from {base_config.db_path} (READ-ONLY)...")
    states, sources, _excerpts = await load_states_and_sources(base_config)
    print(f"  {len(states):,} active nodes loaded.")

    if args.sweep:
        presets = PRESETS
    else:
        # Pick preset by label, or build custom from CLI overrides.
        named = {p.label: p for p in PRESETS}
        if args.label in named and not any(
            getattr(args, k) is not None for k in
            ("rate", "mass_exp", "time_exp", "idle_normalize_days", "grace_days", "floor")
        ):
            presets = [named[args.label]]
        else:
            base = named.get(args.label, PRESETS[0])
            presets = [Preset(
                label=args.label,
                rate=args.rate if args.rate is not None else base.rate,
                mass_exp=args.mass_exp if args.mass_exp is not None else base.mass_exp,
                time_exp=args.time_exp if args.time_exp is not None else base.time_exp,
                idle_normalize_days=(
                    args.idle_normalize_days if args.idle_normalize_days is not None
                    else base.idle_normalize_days
                ),
                grace_days=args.grace_days if args.grace_days is not None else base.grace_days,
                floor=args.floor if args.floor is not None else base.floor,
            )]

    summaries: list[dict[str, Any]] = []
    for p in presets:
        aging_note = ""
        if args.aging_fraction > 0 and args.simulate_aging_days > 0:
            aging_note = (
                f" [aging: {args.aging_fraction:.0%} cohort, "
                f"{args.simulate_aging_days:.0f}d, bias={args.aging_mass_bias}]"
            )
        print(f"Projecting `{p.label}` (ε={p.rate}, β={p.mass_exp}, γ={p.time_exp}){aging_note}...")
        overrides = preset_to_config_overrides(p)
        proj = project(
            overrides, base_config, states, sources, p,
            simulate_aging_days=args.simulate_aging_days,
            aging_fraction=args.aging_fraction,
            aging_mass_bias=args.aging_mass_bias,
        )
        summary = await summarize(proj, base_config)
        # Record the simulation knobs so the report carries provenance.
        summary["aging_simulation"] = {
            "simulate_aging_days": args.simulate_aging_days,
            "aging_fraction": args.aging_fraction,
            "aging_mass_bias": args.aging_mass_bias,
        }
        summaries.append(summary)

        md_path = out_dir / f"{p.label}.md"
        json_path = out_dir / f"{p.label}.json"
        md_path.write_text(render_markdown(summary), encoding="utf-8")
        json_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"  → {md_path}")

    if len(summaries) > 1:
        sweep_path = out_dir / "sweep-summary.md"
        sweep_path.write_text(render_sweep_summary(summaries), encoding="utf-8")
        print(f"Sweep summary → {sweep_path}")

    print("Done. (No production state mutated.)")


def main():
    asyncio.run(amain())


if __name__ == "__main__":
    main()
