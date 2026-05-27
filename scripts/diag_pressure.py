"""Phase P (Pressure Terms) — read-only dry-run projection.

Loads the active DB read-only and projects what happens for **one** physics
step with each subset of {Λ, Langevin} enabled. Reports per-hub
displacement deltas and global Langevin σ scaling.

Safety contract:
  - **NO MUTATION** of the live DB or FAISS files. Engine starts read-only
    (write-behind / dream / faiss_save loops are disabled by overriding
    their intervals to 999s, then we never call ``recall``/``remember``/
    ``index_documents``).
  - All projection happens on **copies** of (displacement, velocity) — the
    engine's cache state is *read* but not mutated.
  - Output to stdout (text or ``--json``); no files written unless
    ``--out`` is given.

Use this BEFORE flipping Stage 1.5 (Langevin) or Stage 2.5 (Λ) env opt-in
to:
  - Confirm σ = √(2·T₀) is the magnitude you expect for your T₀ choice.
  - Identify the singleton hubs that will be pushed by Λ (Plan §5 仮説 1).
  - Sanity-check that no hub is catastrophically expelled at the chosen H.
  - Feed the JSON to secondopinion-MCP as Observer C input.

Examples::

    # Default (cosmological_lambda_h=0.001 / langevin_temperature_t0=0.001)
    .venv/bin/python scripts/diag_pressure.py snapshot

    # Override H / T₀ to preview a louder setting
    .venv/bin/python scripts/diag_pressure.py snapshot \\
        --lambda-h 0.005 --langevin-t0 0.005

    # Machine-readable for diff / Observer C
    .venv/bin/python scripts/diag_pressure.py snapshot --json > snap.json

    # Different data-dir (snapshot of a captured backup)
    .venv/bin/python scripts/diag_pressure.py snapshot \\
        --data-dir /tmp/gaottt-snap-2026-05-27
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import statistics
import sys
from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np

from gaottt.config import GaOTTTConfig
from gaottt.services.runtime import build_engine


# --------------------------------------------------------------------- types


@dataclass
class HubRow:
    """One hub's projection result."""
    id: str
    mass: float
    source: str
    content_preview: str
    disp_norm_before: float
    neighbor_count: int
    # Λ projection
    lambda_accel_norm: float       # ||a_Λ|| at this hub for one step
    lambda_disp_delta: float       # ||a_Λ · dt² / m|| (approximate displacement per step)
    # Langevin projection (global scale, same for every node — included for reference)
    langevin_expected_step_norm: float


@dataclass
class SnapshotReport:
    data_dir: str
    embedding_dim: int
    total_active_nodes: int
    lambda_h: float
    langevin_t0: float
    langevin_sigma: float                  # √(2·T₀)
    langevin_expected_step_norm: float     # σ · √dim
    top_k_hubs: int
    neighbor_k: int
    hubs: list[HubRow] = field(default_factory=list)
    # Distribution stats over hubs
    lambda_accel_stats: dict[str, float] = field(default_factory=dict)


# --------------------------------------------------------------------- helpers


def _percentiles(vals: list[float]) -> dict[str, float]:
    if not vals:
        return {}
    sv = sorted(vals)
    n = len(sv)
    def _at(p: float) -> float:
        i = int(p * (n - 1))
        return sv[i]
    return {
        "min": sv[0],
        "p50": _at(0.5),
        "p90": _at(0.9),
        "p95": _at(0.95),
        "p99": _at(0.99),
        "max": sv[-1],
        "mean": statistics.fmean(sv),
    }


def _excerpt(text: str, limit: int = 80) -> str:
    flat = (text or "").replace("\n", " ").replace("\r", " ").strip()
    return flat[:limit] + ("…" if len(flat) > limit else "")


# --------------------------------------------------------------------- projection


async def _project_lambda_for_hub(
    engine,
    hub,                       # NodeState (in cache)
    *,
    h: float,
    neighbor_k: int,
) -> tuple[np.ndarray, int]:
    """Return (a_Λ at hub, number of neighbors used).

    Reads the hub's position = original_emb + displacement, queries FAISS for
    top-K neighbors (read-only), then sums ``H · (pos_i - pos_j)`` literally
    as the production code does inside ``compute_acceleration`` (Phase P-α).
    """
    vecs = engine.faiss_index.get_vectors([hub.id])
    orig = vecs.get(hub.id)
    if orig is None:
        return np.zeros(engine.config.embedding_dim, dtype=np.float32), 0
    disp_cache = engine.cache.get_displacement(hub.id)
    disp = (
        disp_cache.copy()
        if disp_cache is not None
        else np.zeros(engine.config.embedding_dim, dtype=np.float32)
    )
    pos_i = orig + disp

    # FAISS top-K from hub's position (self-search). search_by_id uses the
    # stored original_emb as the query, which is the production neighbor
    # scope at startup time.
    hits = engine.faiss_index.search_by_id(hub.id, top_k=neighbor_k + 1)
    a_lambda = np.zeros_like(pos_i)
    used = 0
    for nid, _score in hits:
        if nid == hub.id:
            continue
        n_vecs = engine.faiss_index.get_vectors([nid])
        n_orig = n_vecs.get(nid)
        if n_orig is None:
            continue
        n_disp = engine.cache.get_displacement(nid)
        n_pos = n_orig + (
            n_disp if n_disp is not None
            else np.zeros(engine.config.embedding_dim, dtype=np.float32)
        )
        a_lambda += h * (pos_i - n_pos)
        used += 1
        if used >= neighbor_k:
            break
    return a_lambda.astype(np.float32), used


async def _build_snapshot(args: argparse.Namespace) -> SnapshotReport:
    overrides: dict[str, Any] = dict(
        # Read-only: disable write-behind loops so the engine never writes.
        faiss_save_interval_seconds=999.0,
        flush_interval_seconds=999.0,
        virtual_faiss_save_interval_seconds=999.0,
        genesis_kick_enabled=False,
        dream_enabled=False,
    )
    if args.data_dir:
        overrides["data_dir"] = args.data_dir
        overrides["db_path"] = f"{args.data_dir}/gaottt.db"
        overrides["faiss_index_path"] = f"{args.data_dir}/gaottt.faiss"

    config = GaOTTTConfig(**overrides) if overrides else GaOTTTConfig()
    engine = build_engine(config)
    await engine.startup()
    try:
        states = [
            s for s in engine.cache.get_all_nodes() if not s.is_archived
        ]
        if not states:
            raise SystemExit("No active nodes in the DB — nothing to project")

        top_hubs = sorted(states, key=lambda s: s.mass, reverse=True)[: args.top_k_hubs]

        sigma = math.sqrt(2.0 * args.langevin_t0)
        expected_langevin_step = sigma * math.sqrt(config.embedding_dim)

        hubs: list[HubRow] = []
        for hub in top_hubs:
            a_lambda, n_used = await _project_lambda_for_hub(
                engine, hub, h=args.lambda_h, neighbor_k=args.neighbor_k,
            )
            disp_cache = engine.cache.get_displacement(hub.id)
            disp_norm_before = (
                float(np.linalg.norm(disp_cache))
                if disp_cache is not None else 0.0
            )
            mass_safe = max(hub.mass, 1e-9)
            # Per-step displacement contribution from this Λ alone, in the
            # Verlet model with dt=1: new_v = v + a/m, new_disp = old_disp + v.
            # We approximate the steady-state per-step displacement as
            # ||a_Λ / m||. This is an upper bound — friction/Hooke pull back.
            lambda_disp_delta = float(np.linalg.norm(a_lambda) / mass_safe)
            src = engine.cache.source_by_id.get(hub.id, "unknown")
            doc = await engine.store.get_document(hub.id)
            content = (doc or {}).get("content", "") if doc else ""
            hubs.append(HubRow(
                id=hub.id,
                mass=float(hub.mass),
                source=src,
                content_preview=_excerpt(content),
                disp_norm_before=disp_norm_before,
                neighbor_count=n_used,
                lambda_accel_norm=float(np.linalg.norm(a_lambda)),
                lambda_disp_delta=lambda_disp_delta,
                langevin_expected_step_norm=expected_langevin_step,
            ))

        lambda_norms = [h.lambda_accel_norm for h in hubs]
        return SnapshotReport(
            data_dir=str(config.data_dir),
            embedding_dim=config.embedding_dim,
            total_active_nodes=len(states),
            lambda_h=args.lambda_h,
            langevin_t0=args.langevin_t0,
            langevin_sigma=sigma,
            langevin_expected_step_norm=expected_langevin_step,
            top_k_hubs=args.top_k_hubs,
            neighbor_k=args.neighbor_k,
            hubs=hubs,
            lambda_accel_stats=_percentiles(lambda_norms),
        )
    finally:
        await engine.shutdown()


# --------------------------------------------------------------------- rendering


def _render_text(rep: SnapshotReport) -> str:
    out: list[str] = []
    out.append("=== Phase P dry-run snapshot ===")
    out.append(f"data_dir       : {rep.data_dir}")
    out.append(f"active nodes   : {rep.total_active_nodes}")
    out.append(f"embedding dim  : {rep.embedding_dim}")
    out.append("")
    out.append(f"Λ  (P-α): H = {rep.lambda_h}")
    out.append("  per-hub accel ||a_Λ|| stats:")
    for k, v in rep.lambda_accel_stats.items():
        out.append(f"    {k:>5s} = {v:.5f}")
    out.append("")
    out.append(f"Langevin (P-β): T₀ = {rep.langevin_t0}")
    out.append(f"  σ = √(2·T₀)                  = {rep.langevin_sigma:.5f}")
    out.append(f"  expected per-step ||noise||  = σ·√dim = {rep.langevin_expected_step_norm:.5f}")
    out.append("  (uniform across all nodes — Langevin is mass-blind and per-node independent)")
    out.append("")
    out.append(f"Top {len(rep.hubs)} mass hubs (Λ effect breakdown):")
    out.append(
        f"  {'idx':>3s} {'mass':>6s} {'|d|':>6s} {'src':>10s} "
        f"{'nbr':>4s} {'||a_Λ||':>10s} {'a_Λ/m':>10s}  content"
    )
    for i, h in enumerate(rep.hubs, 1):
        out.append(
            f"  {i:>3d} {h.mass:>6.2f} {h.disp_norm_before:>6.3f} "
            f"{h.source[:10]:>10s} {h.neighbor_count:>4d} "
            f"{h.lambda_accel_norm:>10.5f} {h.lambda_disp_delta:>10.5f}  "
            f"{h.content_preview}"
        )
    # Headlines a reader of Stage 7 acceptance cares about
    out.append("")
    out.append("=== Headlines ===")
    if rep.hubs:
        max_lambda = max(rep.hubs, key=lambda h: h.lambda_accel_norm)
        out.append(
            f"  · largest Λ accel hub: {max_lambda.id[:8]} "
            f"mass={max_lambda.mass:.2f} ||a_Λ||={max_lambda.lambda_accel_norm:.5f} "
            f"({_excerpt(max_lambda.content_preview, 50)})"
        )
        # Compare Λ vs Langevin scale
        median_lambda = statistics.fmean([h.lambda_accel_norm for h in rep.hubs])
        ratio = (
            median_lambda / rep.langevin_expected_step_norm
            if rep.langevin_expected_step_norm > 0 else float("inf")
        )
        out.append(
            f"  · median ||a_Λ|| ({median_lambda:.5f}) "
            f"vs ||Langevin step|| ({rep.langevin_expected_step_norm:.5f}) "
            f"ratio = {ratio:.2f}× "
            f"({'Λ dominates' if ratio > 1.0 else 'Langevin dominates'})"
        )
    return "\n".join(out)


def _render_json(rep: SnapshotReport) -> str:
    return json.dumps(asdict(rep), ensure_ascii=False, indent=2)


# --------------------------------------------------------------------- main


async def main_async(args: argparse.Namespace) -> int:
    if args.subcommand != "snapshot":
        print(f"unknown subcommand: {args.subcommand}", file=sys.stderr)
        return 2
    rep = await _build_snapshot(args)
    rendered = _render_json(rep) if args.json else _render_text(rep)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(rendered)
            fh.write("\n")
    else:
        print(rendered)
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Phase P (Λ + Langevin) read-only dry-run projection. Reports "
            "per-hub Λ accel, global Langevin σ, and headline ratios. "
            "Use BEFORE flipping Stage 1.5/2.5 env opt-in."
        ),
    )
    sub = parser.add_subparsers(dest="subcommand", required=True)
    snap = sub.add_parser("snapshot", help="one-shot snapshot of Λ + Langevin scaling")
    snap.add_argument(
        "--data-dir", default=None,
        help="Data directory (default: GaOTTTConfig default)",
    )
    snap.add_argument(
        "--top-k-hubs", type=int, default=20,
        help="Number of top-mass hubs to project per call (default 20)",
    )
    snap.add_argument(
        "--neighbor-k", type=int, default=50,
        help="FAISS top-K neighbors per hub for Λ scope (default 50)",
    )
    snap.add_argument(
        "--lambda-h", type=float, default=None,
        help="Hubble-flow rate H to project (default: config value)",
    )
    snap.add_argument(
        "--langevin-t0", type=float, default=None,
        help="Langevin temperature T₀ to project (default: config value)",
    )
    snap.add_argument(
        "--json", action="store_true",
        help="Emit machine-readable JSON (Observer C input)",
    )
    snap.add_argument(
        "--out", default=None,
        help="Write to file instead of stdout",
    )
    args = parser.parse_args()
    # Defaults from config (resolved lazily so --data-dir override applies)
    if args.lambda_h is None or args.langevin_t0 is None:
        from gaottt.config import GaOTTTConfig as _C
        default_cfg = _C()
        if args.lambda_h is None:
            args.lambda_h = default_cfg.cosmological_lambda_h
        if args.langevin_t0 is None:
            args.langevin_t0 = default_cfg.langevin_temperature_t0
    sys.exit(asyncio.run(main_async(args)))


if __name__ == "__main__":
    main()
