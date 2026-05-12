#!/usr/bin/env python3
"""Phase H Stage 5 — Production acceptance test.

Quantifies the effect of ``wave_neighbor_use_virtual`` on the 24k-node
production DB by running the *same* representative queries through the
*same* engine state with the flag toggled True vs False, and reporting
how top-K composition and wave reach differ.

Why not opencode sub-agent here:
    Stage 5's correctness claim is **structural** ("per-frontier
    search_by_id should now use virtual cosine, so displacement-driven
    geometry reaches the wave"). That's a quantitative comparison best
    measured directly. The CLAUDE.md opencode workflow is for semantic-
    judgment acceptance (does this *feel* right to an LLM observer);
    Stage 5 acceptance is "did the reached set change in the expected
    direction" — a counting question.

Safety:
    Never touches the production data dir. Always copies prod ->
    /tmp/gaottt-acceptance-h5-<ts>/ first, then runs against the copy
    with all write-behind / dream / save loops disabled. Live MCP
    servers are not disturbed.

Usage::

    .venv/bin/python scripts/acceptance_phase_h_stage5.py

    # custom query set from a file (one per line, # for comments)
    .venv/bin/python scripts/acceptance_phase_h_stage5.py --queries my_queries.txt

    # JSON output for trend tracking
    .venv/bin/python scripts/acceptance_phase_h_stage5.py --json out.json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import sys
import time
from dataclasses import dataclass
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from gaottt.config import GaOTTTConfig  # noqa: E402
from gaottt.services.runtime import build_engine  # noqa: E402

# Representative queries spanning the user's actual domains. Mix of:
#   - sparse-class targets (agent self-knowledge)
#   - dense file-source domains (niceboat / KaoUgoku / harakiriworks / lms)
#   - philosophical/abstract (Articulation as Carrier)
#   - explicit Stage 5 self-references (displacement / Phase I / Phase J)
DEFAULT_QUERIES: list[str] = [
    "Phase H Stage 5 wave neighbor virtual FAISS",
    "niceboat の予測モデル採用判断 Sortino",
    "KaoUgoku 共有メモリ Named Event 仮想カメラ",
    "harakiriworks レトロウェーブ visual identity 数式",
    "LMS マルチテナント認証 JWT",
    "Articulation as Carrier 言葉にすることで重力を持つ",
    "displacement 重力井戸 query attraction Phase I",
]


@dataclass
class QueryResult:
    query: str
    flag: bool
    top_ids: list[str]
    top_final_scores: list[float]
    top_gravity_scores: list[float]  # = QueryResultItem.raw_score (query · virtual_pos cosine)
    top_sources: list[str]
    top_tags_first: list[str]
    latency_ms: float


def _copy_prod_to_tmp() -> Path:
    src_cfg = GaOTTTConfig.from_config_file()
    src = Path(src_cfg.data_dir)
    ts = time.strftime("%Y%m%d-%H%M%S")
    dst = Path(f"/tmp/gaottt-acceptance-h5-{ts}")
    dst.mkdir(parents=True, exist_ok=True)
    for name in [
        "gaottt.db",
        "gaottt.faiss",
        "gaottt.faiss.ids",
        "gaottt.virtual.faiss",
        "gaottt.virtual.faiss.ids",
    ]:
        s = src / name
        if s.exists():
            shutil.copy2(s, dst / name)
    # WAL/SHM are not strictly required (sqlite will reconstruct), but
    # copy them too so we see the live state, not a stale checkpoint.
    for name in ["gaottt.db-wal", "gaottt.db-shm"]:
        s = src / name
        if s.exists():
            shutil.copy2(s, dst / name)
    return dst


def _read_only_config(data_dir: Path) -> GaOTTTConfig:
    cfg = GaOTTTConfig.from_config_file()
    cfg.data_dir = str(data_dir)
    cfg.db_path = str(data_dir / "gaottt.db")
    cfg.faiss_index_path = str(data_dir / "gaottt.faiss")
    cfg.virtual_faiss_index_path = str(data_dir / "gaottt.virtual.faiss")
    # Read-only intent: no write-behind, no dream, no save loops.
    cfg.faiss_save_interval_seconds = 0.0
    cfg.virtual_faiss_save_interval_seconds = 0.0
    cfg.dream_enabled = False
    cfg.genesis_kick_enabled = False
    # Disable Phase I Stage 2 query attraction so toggling the wave flag
    # is the *only* difference between runs (otherwise repeated recall
    # would drift displacement and contaminate the comparison).
    cfg.query_kick_strength = 0.0
    return cfg


async def _run_one(engine, query: str, flag: bool, top_k: int) -> QueryResult:
    engine.config.wave_neighbor_use_virtual = flag
    t0 = time.perf_counter()
    results = await engine.query(text=query, top_k=top_k)
    dt = (time.perf_counter() - t0) * 1000
    return QueryResult(
        query=query,
        flag=flag,
        top_ids=[r.id for r in results],
        top_final_scores=[float(r.final_score) for r in results],
        top_gravity_scores=[float(r.raw_score) for r in results],
        top_sources=[
            (r.metadata or {}).get("source", "?") for r in results
        ],
        top_tags_first=[
            ((r.metadata or {}).get("tags") or ["-"])[0] for r in results
        ],
        latency_ms=dt,
    )


def _jaccard(a: list[str], b: list[str]) -> float:
    sa, sb = set(a), set(b)
    if not sa and not sb:
        return 1.0
    return len(sa & sb) / max(1, len(sa | sb))


def _render_markdown(
    pairs: list[tuple[QueryResult, QueryResult]], top_k: int,
) -> str:
    out: list[str] = []
    out.append(f"# Phase H Stage 5 acceptance — {time.strftime('%Y-%m-%d %H:%M:%S')}")
    out.append("")
    out.append(
        "Comparison of `wave_neighbor_use_virtual=True` (new default) vs "
        "`=False` (legacy) on the production corpus, against a /tmp copy.\n"
    )

    # Overview table
    out.append("## Overview\n")
    out.append("| # | Query | Top-K jaccard | Top1 same? | Δ top1 final | Latency T/F (ms) |")
    out.append("|---|---|---|---|---|---|")
    for i, (t, f) in enumerate(pairs, 1):
        jac = _jaccard(t.top_ids[:top_k], f.top_ids[:top_k])
        same_top1 = "✅" if (t.top_ids and f.top_ids and t.top_ids[0] == f.top_ids[0]) else "❌"
        delta = (
            t.top_final_scores[0] - f.top_final_scores[0]
            if t.top_final_scores and f.top_final_scores else 0.0
        )
        q_short = t.query[:42] + ("…" if len(t.query) > 42 else "")
        out.append(
            f"| {i} | `{q_short}` | {jac*100:.0f}% | {same_top1} | "
            f"{delta:+.4f} | {t.latency_ms:.0f} / {f.latency_ms:.0f} |"
        )
    out.append("")

    # Per-query detail
    for i, (t, f) in enumerate(pairs, 1):
        out.append(f"## {i}. `{t.query}`")
        out.append("")
        out.append("| Rank | virtual=True (new) | virtual=False (legacy) |")
        out.append("|---|---|---|")
        for r in range(top_k):
            tn = (
                f"`{t.top_ids[r][:8]}` "
                f"final={t.top_final_scores[r]:.3f} "
                f"grav={t.top_gravity_scores[r]:.3f} "
                f"src={t.top_sources[r]} [{t.top_tags_first[r]}]"
                if r < len(t.top_ids) else "—"
            )
            fn = (
                f"`{f.top_ids[r][:8]}` "
                f"final={f.top_final_scores[r]:.3f} "
                f"grav={f.top_gravity_scores[r]:.3f} "
                f"src={f.top_sources[r]} [{f.top_tags_first[r]}]"
                if r < len(f.top_ids) else "—"
            )
            out.append(f"| {r+1} | {tn} | {fn} |")
        out.append("")

    # Aggregate stats
    out.append("## Aggregate")
    out.append("")
    same_top1 = sum(
        1 for t, f in pairs
        if t.top_ids and f.top_ids and t.top_ids[0] == f.top_ids[0]
    )
    avg_jac = sum(_jaccard(t.top_ids[:top_k], f.top_ids[:top_k]) for t, f in pairs) / max(1, len(pairs))
    avg_dt = sum(t.latency_ms for t, _ in pairs) / max(1, len(pairs))
    avg_df = sum(f.latency_ms for _, f in pairs) / max(1, len(pairs))
    out.append(f"- Top-1 stability: **{same_top1}/{len(pairs)}**")
    out.append(f"- Avg top-{top_k} Jaccard: **{avg_jac*100:.1f}%**")
    out.append(f"- Avg latency: True={avg_dt:.0f}ms / False={avg_df:.0f}ms")
    out.append("")
    out.append(
        "**Reading**: high Jaccard + same top1 means Stage 5 mostly preserves "
        "rank where it should. Low Jaccard with same top1 means Stage 5 "
        "reshuffled the *tail* through virtual neighbor expansion — exactly "
        "the expected behaviour for displacement-aware reach. Different top1 "
        "signals a query whose semantic neighbour was reachable only through "
        "virtual cosine."
    )
    return "\n".join(out)


async def main_async(args: argparse.Namespace) -> int:
    queries = (
        Path(args.queries).read_text().splitlines() if args.queries else DEFAULT_QUERIES
    )
    queries = [q.strip() for q in queries if q.strip() and not q.lstrip().startswith("#")]
    print(f"# Phase H Stage 5 acceptance — {len(queries)} queries", file=sys.stderr)

    print("# Copying prod data dir to /tmp ...", file=sys.stderr)
    tmp_dir = _copy_prod_to_tmp()
    print(f"# Copy ready: {tmp_dir}", file=sys.stderr)

    cfg = _read_only_config(tmp_dir)
    print("# Building engine (this loads FAISS, may take a few seconds) ...", file=sys.stderr)
    engine = build_engine(cfg)
    await engine.startup()

    pairs: list[tuple[QueryResult, QueryResult]] = []
    try:
        for i, q in enumerate(queries, 1):
            print(f"# Query {i}/{len(queries)}: {q[:60]}", file=sys.stderr)
            # alternate True/False per query against the same engine state
            t_res = await _run_one(engine, q, flag=True,  top_k=args.top_k)
            f_res = await _run_one(engine, q, flag=False, top_k=args.top_k)
            pairs.append((t_res, f_res))
    finally:
        await engine.shutdown()

    md = _render_markdown(pairs, top_k=args.top_k)
    print(md)

    if args.json:
        payload = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "top_k": args.top_k,
            "tmp_dir": str(tmp_dir),
            "results": [
                {
                    "query": t.query,
                    "true": t.__dict__,
                    "false": f.__dict__,
                    "jaccard_topk": _jaccard(t.top_ids[:args.top_k], f.top_ids[:args.top_k]),
                }
                for t, f in pairs
            ],
        }
        Path(args.json).write_text(json.dumps(payload, ensure_ascii=False, indent=2))
        print(f"# JSON saved: {args.json}", file=sys.stderr)

    if args.cleanup:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        print(f"# Cleaned up {tmp_dir}", file=sys.stderr)
    else:
        print(f"# /tmp dir kept for inspection: {tmp_dir}", file=sys.stderr)
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="Phase H Stage 5 production acceptance")
    p.add_argument("--queries", help="path to a file of newline-separated queries (# for comments)")
    p.add_argument("--top-k", type=int, default=5)
    p.add_argument("--json", help="also write a JSON record of all measurements")
    p.add_argument("--cleanup", action="store_true", help="remove the /tmp copy on exit")
    args = p.parse_args()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    sys.exit(main())
