"""Production-DB read-only acceptance: compare two GaOTTTConfig overrides
on the same snapshot, recording top-K with content excerpts so a reviewer
can both diff IDs *and* judge qualitative shift.

Use case: Phase I Stage 4 (or any future physics tweak) needs to be
verified on the real 23k-active corpus, not a 30-doc unit fixture. We
snapshot production once, then iterate fast on different β values
without disturbing the running MCP backend.

The script disables dream loop and write-behind so the snapshot is
effectively read-only at the OS level (only in-memory state of this
process changes — never the source DB / FAISS files we copied from).

Usage::

    python scripts/diag_production_acceptance.py \\
        --snapshot ./.acceptance-snapshot \\
        --label-a "beta0" --overrides-a '{"mass_anchor_extra_strength": 0.0}' \\
        --label-b "beta1" --overrides-b '{"mass_anchor_extra_strength": 1.0}' \\
        --out ./.acceptance-report.json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import sys
import time
from pathlib import Path
from statistics import mean

import numpy as np

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from gaottt.config import GaOTTTConfig  # noqa: E402
from gaottt.core.engine import GaOTTTEngine  # noqa: E402
from gaottt.embedding.ruri import RuriEmbedder  # noqa: E402
from gaottt.index.faiss_index import FaissIndex  # noqa: E402
from gaottt.store.cache import CacheLayer  # noqa: E402
from gaottt.store.sqlite_store import SqliteStore  # noqa: E402


# Production-realistic query set. Hits the source classes we know matter
# in this DB: agent (Phase docs / design judgments), persona (value /
# intention / commitment), failure stories, niceboat / harakiriworks
# self-knowledge, and surface-form queries that exercise BM25.
QUERIES = [
    # Design / phase knowledge
    "Articulation as Carrier の物理実装",
    "Stage 3 mass-gated query attraction の機序",
    "Phase L hybrid retrieval BM25 RRF の判定根拠",
    "Phase M mass conservation で source 偏在を直す",
    # Persona / commitment
    "GaOTTT の人格設計の核",
    "現在 active な commitment は何",
    "持っている value と intention",
    # Failure stories / corrections
    "StubEmbedder で性能評価が失敗した話",
    "FAISS 0-byte で startup が壊れる罠",
    # Workflow / operations
    "本番 acceptance test を opencode で回す理由",
    "MCP と REST の parity 鉄則",
    # Surface-form (BM25 が効くべき)
    "harakiriworks Eleventy Pipeline",
    "niceboat boat_transformer FT",
    # Open-ended / 肌感を見やすい
    "今日の作業で印象に残った設計判断",
    "Five-Layer Philosophy",
]


def _build_engine(data_dir: Path, overrides: dict, embedder: RuriEmbedder) -> GaOTTTEngine:
    """Mirror engine factory in tests/perf/_helpers, but disable background
    loops so the snapshot is read-only in practice.
    """
    defaults = dict(
        data_dir=str(data_dir),
        # Kill all background writers: dream loop / write-behind / virtual
        # save loop all OFF so the snapshot stays untouched on disk.
        dream_enabled=False,
        faiss_save_interval_seconds=0.0,
        virtual_faiss_save_interval_seconds=0.0,
        flush_interval_seconds=999999.0,
        flush_threshold=999999,
    )
    defaults.update(overrides)
    config = GaOTTTConfig(**defaults)
    return GaOTTTEngine(
        config=config,
        embedder=embedder,
        faiss_index=FaissIndex(dimension=config.embedding_dim),
        cache=CacheLayer(
            flush_interval=config.flush_interval_seconds,
            flush_threshold=config.flush_threshold,
        ),
        store=SqliteStore(db_path=config.db_path),
    )


async def _run_config(
    snapshot: Path,
    overrides: dict,
    embedder: RuriEmbedder,
    queries: list[str],
    top_k: int,
) -> dict:
    """Run all queries against the snapshot with given overrides.

    Returns a dict with per-query top-K (id, score, content excerpt, source,
    mass, displacement_norm) plus latency stats.
    """
    # Each variant gets its own dir copy so cache state can't bleed.
    work_dir = snapshot.parent / f"acceptance-work-{int(time.time()*1000)}"
    work_dir.mkdir(parents=True, exist_ok=True)
    for f in snapshot.iterdir():
        if f.is_file():
            shutil.copy2(f, work_dir / f.name)

    engine = _build_engine(work_dir, overrides, embedder)
    await engine.startup()
    results: list[dict] = []
    latencies_ms: list[float] = []
    try:
        for q in queries:
            t0 = time.perf_counter()
            res = await engine.query(text=q, top_k=top_k)
            latencies_ms.append((time.perf_counter() - t0) * 1000.0)
            entries = []
            for r in res:
                state = engine.cache.get_node(r.id)
                if state is None:
                    states_map = await engine.store.get_node_states([r.id])
                    state = states_map.get(r.id)
                disp = engine.cache.get_displacement(r.id)
                if disp is None and state is not None:
                    disp_states = await engine.store.get_node_states([r.id])
                    disp_state = disp_states.get(r.id)
                    disp = disp_state.displacement if disp_state else None
                mass = state.mass if state else 0.0
                disp_norm = 0.0 if disp is None else float(np.linalg.norm(disp))
                content_excerpt = (r.content or "")[:160].replace("\n", " ")
                entries.append({
                    "id": r.id,
                    "final_score": float(r.final_score),
                    "virtual_score": float(r.raw_score),
                    "source": (r.metadata or {}).get("source"),
                    "mass": round(mass, 3),
                    "displacement_norm": round(disp_norm, 4),
                    "content": content_excerpt,
                })
            results.append({"query": q, "top_k": entries})
    finally:
        await engine.shutdown()
        shutil.rmtree(work_dir, ignore_errors=True)

    return {
        "queries": results,
        "latency_ms": {
            "p50": _pct(latencies_ms, 50),
            "p95": _pct(latencies_ms, 95),
            "p99": _pct(latencies_ms, 99),
            "mean": mean(latencies_ms),
        },
    }


def _pct(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    return s[int(round((p / 100.0) * (len(s) - 1)))]


def _jaccard(a: list[str], b: list[str]) -> float:
    sa, sb = set(a), set(b)
    if not sa and not sb:
        return 1.0
    return len(sa & sb) / max(1, len(sa | sb))


def _ordered_match(a: list[str], b: list[str]) -> int:
    """Count of position-aligned identical entries."""
    return sum(1 for x, y in zip(a, b) if x == y)


async def _main_async(args):
    snapshot = Path(args.snapshot).resolve()
    if not (snapshot / "gaottt.db").exists():
        raise SystemExit(f"snapshot not found: {snapshot}/gaottt.db")
    overrides_a = json.loads(args.overrides_a) if args.overrides_a else {}
    overrides_b = json.loads(args.overrides_b) if args.overrides_b else {}

    print(f"[acceptance] embedder warmup (real RURI v3 310m)...")
    embedder = RuriEmbedder()

    print(f"[acceptance] running A ({args.label_a}) — {len(QUERIES)} queries")
    a = await _run_config(snapshot, overrides_a, embedder, QUERIES, args.top_k)
    print(f"[acceptance] running B ({args.label_b}) — {len(QUERIES)} queries")
    b = await _run_config(snapshot, overrides_b, embedder, QUERIES, args.top_k)

    # Per-query diff
    diffs: list[dict] = []
    for qa, qb in zip(a["queries"], b["queries"]):
        ids_a = [e["id"] for e in qa["top_k"]]
        ids_b = [e["id"] for e in qb["top_k"]]
        diffs.append({
            "query": qa["query"],
            "jaccard": round(_jaccard(ids_a, ids_b), 3),
            "positionally_identical_topk": _ordered_match(ids_a, ids_b),
            "top1_same": ids_a[:1] == ids_b[:1],
            "top3_same_set": set(ids_a[:3]) == set(ids_b[:3]),
            "ids_a": ids_a,
            "ids_b": ids_b,
            # full entries kept so opencode can read content excerpts side-by-side
            "top_k_a": qa["top_k"],
            "top_k_b": qb["top_k"],
        })

    jaccards = [d["jaccard"] for d in diffs]
    positional = [d["positionally_identical_topk"] for d in diffs]
    top1_same = sum(1 for d in diffs if d["top1_same"])
    top3_same_set = sum(1 for d in diffs if d["top3_same_set"])

    report = {
        "snapshot": str(snapshot),
        "label_a": args.label_a,
        "label_b": args.label_b,
        "overrides_a": overrides_a,
        "overrides_b": overrides_b,
        "top_k": args.top_k,
        "summary": {
            "n_queries": len(QUERIES),
            "jaccard_mean": round(mean(jaccards), 3),
            "jaccard_min": round(min(jaccards), 3),
            "top1_same_count": top1_same,
            "top3_same_set_count": top3_same_set,
            "positional_match_mean": round(mean(positional), 2),
            "latency_a_ms": a["latency_ms"],
            "latency_b_ms": b["latency_ms"],
        },
        "per_query": diffs,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"\n[acceptance] report written: {out}")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--snapshot", required=True, help="Path to dir containing gaottt.db + gaottt.faiss copies")
    parser.add_argument("--label-a", default="A")
    parser.add_argument("--label-b", default="B")
    parser.add_argument("--overrides-a", default="")
    parser.add_argument("--overrides-b", default="")
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--out", default=str(_PROJECT_ROOT / ".acceptance-report.json"))
    args = parser.parse_args()
    asyncio.run(_main_async(args))


if __name__ == "__main__":
    main()
