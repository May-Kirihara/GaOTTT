"""Diagnostic recall — JSON snapshot of engine.query state, per Tier 4-7 axis.

Promoted from the ad-hoc ``/tmp/diag_seed_pool.py`` workflow used during
Phase L acceptance. Captures, for each query:

  - The engine.query top-K (id / source / tags / final_score / displacement_norm)
  - The BM25 top-K (id / score)
  - The raw FAISS top-K (id / cosine score)

Output is one JSON object per query, plus a top-level header. Compare
two snapshots with::

    python scripts/diag_recall.py snapshot --out /tmp/before.json
    # … make a change …
    python scripts/diag_recall.py snapshot --out /tmp/after.json
    python scripts/diag_recall.py diff /tmp/before.json /tmp/after.json

The diff highlights queries whose top-K composition changed.

This is a **read-only** tool. It uses the same `build_engine` factory as
the production server but disables write-behind loops, so it won't race
with a live MCP server. (It will, however, share the FAISS / SQLite
files — make sure no other process is in the middle of a `compact`.)

Usage::

    # One-off snapshot of a single query
    python scripts/diag_recall.py snapshot --query "Eleventy Pipeline" --top-k 5

    # Snapshot a list of queries to a JSON file
    python scripts/diag_recall.py snapshot \\
        --queries-file tests/perf/golden_corpus/queries.json \\
        --out /tmp/diag_before.json

    # Compare two snapshots
    python scripts/diag_recall.py diff /tmp/diag_before.json /tmp/diag_after.json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

# Allow direct invocation. Mirrors the bootstrap_report.py pattern so the
# tool works even if the editable install path went stale.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from gaottt.config import GaOTTTConfig  # noqa: E402
from gaottt.core.engine import GaOTTTEngine  # noqa: E402
from gaottt.services.runtime import build_engine  # noqa: E402


async def _load_engine(data_dir: str | None = None) -> GaOTTTEngine:
    if data_dir is not None:
        # Isolated test directory — never touches the production DB.
        config = GaOTTTConfig(data_dir=data_dir)
    else:
        config = GaOTTTConfig.from_config_file()
    config.faiss_save_interval_seconds = 0.0
    config.virtual_faiss_save_interval_seconds = 0.0
    config.dream_enabled = False
    engine = build_engine(config)
    await engine.startup()
    return engine


async def _snapshot_query(
    engine: GaOTTTEngine, query: str, top_k: int,
) -> dict:
    engine_results = await engine.query(text=query, top_k=top_k)

    bm25_top: list[dict] = []
    if engine.bm25_index is not None and engine.bm25_index.size > 0:
        for nid, score in engine.bm25_index.search(query, top_k=top_k):
            bm25_top.append({"id": nid, "score": float(score)})

    raw_faiss_top: list[dict] = []
    if engine.faiss_index.size > 0:
        q_vec = engine.embedder.encode_query(query)
        # FaissIndex.search returns (id, score) tuples in score-desc order.
        for nid, score in engine.faiss_index.search(q_vec, top_k=top_k):
            raw_faiss_top.append({"id": nid, "cosine": float(score)})

    engine_top: list[dict] = []
    for r in engine_results:
        meta = r.metadata or {}
        engine_top.append({
            "id": r.id,
            "source": meta.get("source"),
            "tags": meta.get("tags") or [],
            "raw_score": float(r.raw_score),
            "final_score": float(r.final_score),
            "displacement_norm": float(engine.get_displacement_norm(r.id)),
        })

    return {
        "query": query,
        "engine_top": engine_top,
        "bm25_top": bm25_top,
        "raw_faiss_top": raw_faiss_top,
    }


async def _do_snapshot(args: argparse.Namespace) -> None:
    queries: list[str] = []
    if args.query:
        queries.append(args.query)
    if args.queries_file:
        with Path(args.queries_file).expanduser().open(encoding="utf-8") as f:
            data = json.load(f)
        for q in data:
            queries.append(q["query"] if isinstance(q, dict) else str(q))
    if not queries:
        raise SystemExit("No queries provided. Pass --query or --queries-file.")

    engine = await _load_engine(data_dir=args.data_dir)
    try:
        snapshots = []
        for q in queries:
            snapshots.append(await _snapshot_query(engine, q, args.top_k))
        output = {
            "captured_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "top_k": args.top_k,
            "n_queries": len(snapshots),
            "engine_faiss_size": engine.faiss_index.size,
            "engine_bm25_size": engine.bm25_index.size if engine.bm25_index else 0,
            "queries": snapshots,
        }
    finally:
        await engine.shutdown()

    if args.out:
        out_path = Path(args.out).expanduser()
        out_path.write_text(json.dumps(output, ensure_ascii=False, indent=2))
        print(f"Snapshot written to {out_path} ({len(snapshots)} queries)")
    else:
        print(json.dumps(output, ensure_ascii=False, indent=2))


def _diff_id_lists(before: list[dict], after: list[dict]) -> dict:
    b_ids = [r["id"] for r in before]
    a_ids = [r["id"] for r in after]
    return {
        "added": [i for i in a_ids if i not in b_ids],
        "removed": [i for i in b_ids if i not in a_ids],
        "reordered": (
            b_ids != a_ids and set(b_ids) == set(a_ids)
        ),
        "before": b_ids,
        "after": a_ids,
    }


def _do_diff(args: argparse.Namespace) -> None:
    with Path(args.before).expanduser().open(encoding="utf-8") as f:
        before = json.load(f)
    with Path(args.after).expanduser().open(encoding="utf-8") as f:
        after = json.load(f)

    if before["top_k"] != after["top_k"]:
        print(
            f"WARNING: snapshots have different top_k "
            f"({before['top_k']} vs {after['top_k']}); diff may be noisy."
        )

    before_by_query = {q["query"]: q for q in before["queries"]}
    after_by_query = {q["query"]: q for q in after["queries"]}

    queries = sorted(set(before_by_query) | set(after_by_query))
    diffs: list[dict] = []
    for q in queries:
        if q not in before_by_query:
            diffs.append({"query": q, "status": "new", "after_top": [r["id"] for r in after_by_query[q]["engine_top"]]})
            continue
        if q not in after_by_query:
            diffs.append({"query": q, "status": "removed", "before_top": [r["id"] for r in before_by_query[q]["engine_top"]]})
            continue
        diffs.append({
            "query": q,
            "status": "compared",
            "engine_top_diff": _diff_id_lists(before_by_query[q]["engine_top"], after_by_query[q]["engine_top"]),
            "bm25_top_diff": _diff_id_lists(before_by_query[q]["bm25_top"], after_by_query[q]["bm25_top"]),
            "raw_faiss_top_diff": _diff_id_lists(before_by_query[q]["raw_faiss_top"], after_by_query[q]["raw_faiss_top"]),
        })

    changed = sum(
        1 for d in diffs
        if d["status"] != "compared"
        or d["engine_top_diff"]["added"]
        or d["engine_top_diff"]["removed"]
        or d["engine_top_diff"]["reordered"]
    )
    print(json.dumps({"changed_queries": changed, "total_queries": len(queries), "details": diffs}, ensure_ascii=False, indent=2))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("snapshot", help="Capture engine.query / BM25 / FAISS state per query")
    s.add_argument("--query", help="Single query string")
    s.add_argument("--queries-file", help="JSON file containing a list of {query: ...} records (e.g. tests/perf/golden_corpus/queries.json)")
    s.add_argument("--top-k", type=int, default=5)
    s.add_argument("--out", help="Output JSON path. If omitted, prints to stdout.")
    s.add_argument("--data-dir", help="Override data_dir (use a /tmp path to avoid the production DB).")

    d = sub.add_parser("diff", help="Diff two snapshots")
    d.add_argument("before")
    d.add_argument("after")

    args = parser.parse_args(argv)
    if args.cmd == "snapshot":
        asyncio.run(_do_snapshot(args))
    elif args.cmd == "diff":
        _do_diff(args)


if __name__ == "__main__":
    main()
