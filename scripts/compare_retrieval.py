"""Observation Apparatus Refinement Stage 3 — compare-retrieval CLI.

Read-only diagnostic that runs the SAME query through four retrieval modes
and prints them side-by-side, so dogfooding and regression diagnosis can
see at a glance how recall / serendipity-explore / dormant-explore /
ambient-recall disagree on the same input.

The script is read-only by construction:
  - ``recall`` is called with ``passive=True`` (no field perturbation)
  - ``explore`` is invoked with ``training_delta_enabled=False`` so no
    displacement / cooccurrence is written back
  - ``ambient_recall`` is passive by design

This is observation-layer only. Force computation is not touched. The
output also flags Heavy Persona Dominance candidates (any item whose
``ScoreBreakdown.reason`` contains ``dominance artifact``).

Typical usage::

    .venv/bin/python scripts/compare_retrieval.py "固定観念を崩す 柔軟性"
    .venv/bin/python scripts/compare_retrieval.py "..." --data-dir /tmp/snap --top-k 5
    .venv/bin/python scripts/compare_retrieval.py "..." --json

When ``--data-dir`` is omitted the script uses the same default data
directory the production server would (``./data`` relative to
``GaOTTTConfig`` defaults). Pass an isolated path when probing snapshots.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import asdict, dataclass, field
from typing import Any

from gaottt.config import GaOTTTConfig
from gaottt.services import memory as memory_service
from gaottt.services.runtime import build_engine


# --------------------------------------------------------------------- types

@dataclass
class Snippet:
    """One row in a side-by-side comparison column."""
    rank: int
    id: str
    source: str
    mass: float
    cosine: float
    final_score: float
    content: str
    reason: str | None = None
    dominance: bool = False


@dataclass
class ColumnReport:
    label: str
    snippets: list[Snippet] = field(default_factory=list)
    empty_reason: str | None = None


# --------------------------------------------------------------------- helpers

def _truncate(s: str, limit: int = 70) -> str:
    flat = (s or "").replace("\n", " ").replace("\r", " ").strip()
    return flat[:limit] + "…" if len(flat) > limit else flat


def _snippet_from_item(item: Any, *, rank: int, engine) -> Snippet:
    """Build a side-by-side row from a recall/explore ``MemoryItem``."""
    state = engine.cache.get_node(item.id)
    mass = float(state.mass) if state is not None else 0.0
    cosine = 0.0
    if item.score_breakdown is not None:
        cosine = float(item.score_breakdown.virtual_cosine)
    reason = (
        item.score_breakdown.reason
        if item.score_breakdown is not None
        else None
    )
    dominance = bool(reason and "dominance artifact" in reason)
    return Snippet(
        rank=rank,
        id=item.id,
        source=item.source,
        mass=mass,
        cosine=cosine,
        final_score=float(item.final_score),
        content=_truncate(item.content),
        reason=reason,
        dominance=dominance,
    )


def _snippet_from_ambient(
    m: Any, *, rank: int, slot: str,
) -> Snippet:
    """Build a row from an ``AmbientMemory`` (direct/lensing/dormant slot)."""
    reason = m.breakdown.reason if m.breakdown is not None else None
    cosine = float(m.breakdown.virtual_cosine) if m.breakdown is not None else 0.0
    mass = float(m.breakdown.node_mass) if m.breakdown is not None else 0.0
    dominance = bool(reason and "dominance artifact" in reason)
    return Snippet(
        rank=rank,
        id=m.id,
        source=f"{m.source}/{slot}",
        mass=mass,
        cosine=cosine,
        final_score=float(m.final_score),
        content=_truncate(m.content),
        reason=reason,
        dominance=dominance,
    )


# ------------------------------------------------------------- column builders

async def _column_recall(engine, query: str, top_k: int) -> ColumnReport:
    rep = ColumnReport(label="recall (passive)")
    resp = await memory_service.recall(
        engine, query=query, top_k=top_k, passive=True, auto_route=False,
    )
    if not resp.items:
        rep.empty_reason = "no hits"
        return rep
    for i, item in enumerate(resp.items, 1):
        rep.snippets.append(_snippet_from_item(item, rank=i, engine=engine))
    return rep


async def _column_explore_serendipity(
    engine, query: str, top_k: int,
) -> ColumnReport:
    rep = ColumnReport(label="explore diversity=0.9")
    # passive=True: engine.query skips _update_simulation + _update_cooccurrence
    # (engine.py L1073-1080), so mass / displacement / co-occurrence are not
    # written. This is the same read-only mode recall(passive=True) uses for
    # ambient_recall. Previously the script disabled training_delta_enabled
    # and assumed that meant read-only — but training_delta only gates
    # *reporting* of deltas, not the underlying mutation.
    resp = await memory_service.explore(
        engine, query=query, diversity=0.9, top_k=top_k,
        auto_route=False, mode="serendipity", passive=True,
    )
    if not resp.items:
        rep.empty_reason = "no hits"
        return rep
    for i, item in enumerate(resp.items, 1):
        rep.snippets.append(_snippet_from_item(item, rank=i, engine=engine))
    return rep


async def _column_explore_dormant(engine, top_k: int) -> ColumnReport:
    rep = ColumnReport(label="explore mode=dormant")
    resp = await memory_service.explore(
        engine, query="", diversity=0.5, top_k=top_k,
        auto_route=False, mode="dormant",
    )
    if not resp.items:
        rep.empty_reason = "dormant pool empty (no candidate under mass/age cut)"
        return rep
    for i, item in enumerate(resp.items, 1):
        rep.snippets.append(_snippet_from_item(item, rank=i, engine=engine))
    return rep


async def _column_ambient(engine, query: str) -> ColumnReport:
    rep = ColumnReport(label="ambient_recall")
    resp = await memory_service.ambient_recall(
        engine, query=query, direct_k=2, expose_breakdown=True,
    )
    if resp.count == 0:
        rep.empty_reason = "ambient gate suppressed (off-topic or empty corpus)"
        return rep
    rank = 1
    for m in resp.direct:
        rep.snippets.append(_snippet_from_ambient(m, rank=rank, slot="direct"))
        rank += 1
    for m in resp.lensing:
        rep.snippets.append(_snippet_from_ambient(m, rank=rank, slot="lensing"))
        rank += 1
    for m in resp.dormant:
        rep.snippets.append(_snippet_from_ambient(m, rank=rank, slot="dormant"))
        rank += 1
    return rep


# --------------------------------------------------------------------- summary

def _overlap_pct(a: list[Snippet], b: list[Snippet]) -> float:
    ids_a = {s.id for s in a}
    ids_b = {s.id for s in b}
    if not ids_a or not ids_b:
        return 0.0
    return 100.0 * len(ids_a & ids_b) / min(len(ids_a), len(ids_b))


def _source_dist(snips: list[Snippet]) -> dict[str, int]:
    out: dict[str, int] = {}
    for s in snips:
        # Trim "/slot" suffix from ambient sources so the summary lines up
        # with the other columns' source labels.
        key = s.source.split("/", 1)[0]
        out[key] = out.get(key, 0) + 1
    return out


def _summary_lines(columns: list[ColumnReport]) -> list[str]:
    by_label = {c.label: c for c in columns}
    lines = ["", "=== overlap / dominance warning ==="]
    rec = by_label.get("recall (passive)")
    exp = by_label.get("explore diversity=0.9")
    dor = by_label.get("explore mode=dormant")
    amb = by_label.get("ambient_recall")
    if rec and exp:
        pct = _overlap_pct(rec.snippets, exp.snippets)
        warn = " (high — explore not effectively widening)" if pct >= 60.0 else ""
        lines.append(f"- recall ∩ explore overlap: {pct:.0f}%{warn}")
    if rec and dor:
        pct = _overlap_pct(rec.snippets, dor.snippets)
        lines.append(f"- recall ∩ dormant overlap: {pct:.0f}% (expect 0 — dormant is counter-importance)")
    if rec and rec.snippets:
        top_mass = rec.snippets[0].mass
        warn = (
            " (>2.0, Heavy Persona Dominance candidate)"
            if top_mass > 2.0 else ""
        )
        lines.append(f"- recall top1 mass: {top_mass:.2f}{warn}")
    # Dominance flag count across all columns
    flagged = sum(
        1 for c in columns for s in c.snippets if s.dominance
    )
    if flagged:
        lines.append(
            f"- ⚠ dominance-artifact flags: {flagged} "
            "(see reason: lines in the columns above)"
        )
    # Source distribution per column
    for c in columns:
        if not c.snippets:
            continue
        dist = _source_dist(c.snippets)
        parts = " ".join(f"{k}={v}" for k, v in sorted(dist.items()))
        lines.append(f"- {c.label} source distribution: {parts}")
    if amb and amb.empty_reason is None:
        # When ambient fired, break down the slot membership.
        slot_counts: dict[str, int] = {}
        for s in amb.snippets:
            slot = s.source.split("/", 1)[1] if "/" in s.source else "?"
            slot_counts[slot] = slot_counts.get(slot, 0) + 1
        slot_parts = " ".join(f"{k}={v}" for k, v in sorted(slot_counts.items()))
        lines.append(f"- ambient slot membership: {slot_parts}")
    return lines


# --------------------------------------------------------------------- rendering

def _render_text(columns: list[ColumnReport]) -> str:
    out: list[str] = []
    for c in columns:
        out.append("")
        out.append(f"=== {c.label} ({len(c.snippets)} rows) ===")
        if c.empty_reason:
            out.append(f"(empty: {c.empty_reason})")
            continue
        for s in c.snippets:
            line = (
                f"{s.rank}. [{s.source:>14s}  "
                f"m={s.mass:5.2f} c={s.cosine:5.2f} f={s.final_score:5.2f}] "
                f"{s.content}"
            )
            if s.dominance:
                line += "  ⚠"
            out.append(line)
            if s.reason:
                out.append(f"     reason: {s.reason}")
    out.extend(_summary_lines(columns))
    return "\n".join(out)


def _render_json(columns: list[ColumnReport]) -> str:
    payload = {
        "columns": [
            {
                "label": c.label,
                "empty_reason": c.empty_reason,
                "snippets": [asdict(s) for s in c.snippets],
            }
            for c in columns
        ],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


# --------------------------------------------------------------------- main

async def main_async(args: argparse.Namespace) -> int:
    overrides: dict[str, Any] = {}
    if args.data_dir:
        overrides["data_dir"] = args.data_dir
        overrides["db_path"] = f"{args.data_dir}/gaottt.db"
        overrides["faiss_index_path"] = f"{args.data_dir}/gaottt.faiss"
    config = GaOTTTConfig(**overrides) if overrides else GaOTTTConfig()
    engine = build_engine(config)
    await engine.startup()
    try:
        columns = []
        columns.append(await _column_recall(engine, args.query, args.top_k))
        columns.append(await _column_explore_serendipity(engine, args.query, args.top_k))
        columns.append(await _column_explore_dormant(engine, args.top_k))
        columns.append(await _column_ambient(engine, args.query))
    finally:
        await engine.shutdown()

    if args.json:
        print(_render_json(columns))
    else:
        print(_render_text(columns))
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Compare retrieval modes side-by-side. Read-only — does not "
            "perturb mass / displacement / cooccurrence."
        ),
    )
    parser.add_argument("query", help="The query to run through all four modes")
    parser.add_argument(
        "--top-k", type=int, default=5,
        help="Rows per column (default 5)",
    )
    parser.add_argument(
        "--data-dir", default=None,
        help="Data directory (default: GaOTTTConfig default)",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Emit machine-readable JSON for diff-driven regression",
    )
    args = parser.parse_args()
    sys.exit(asyncio.run(main_async(args)))


if __name__ == "__main__":
    main()
