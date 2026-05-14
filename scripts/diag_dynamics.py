"""Diff orbital dynamics (displacement / mass / top-5 stability) between two
GaOTTTConfig snapshots on a controlled corpus.

Used to verify Phase I Stage 4 (or any future physics tweak) end-to-end:
the perf baseline measures latency, but Stage 4 changes Hooke amplification
— the visible effect is displacement-distribution shift, not faster recall.

Compares two configs by:
  1. Ingesting the same N docs (real RURI, deterministic across runs).
  2. Hitting K queries (same query set, in the same order).
  3. Snapshotting per-node displacement L2 norm, mass, and the final top-5
     result id sets per query.
  4. Reporting summary diffs: displacement p50/p90/max, mass p50/p90/max,
     top-5 Jaccard overlap between the two runs (drift induced by the
     physics change).

Usage::

    python scripts/diag_dynamics.py \\
        --label-a "beta0-default" \\
        --label-b "beta1-active" \\
        --overrides-b '{"mass_anchor_extra_strength": 1.0}'
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from statistics import mean

import numpy as np

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from tests.perf._helpers import make_engine  # noqa: E402


CORPUS = [
    "メモリの永続化は SQLite WAL モードを使う",
    "FAISS IndexFlatIP で cosine 類似度の検索を行う",
    "RURI v3 310m は日本語 sentence-transformer",
    "BM25 と cosine の hybrid retrieval を Phase L で導入",
    "重力モデル Newton と Hooke の組合せで displacement を計算",
    "Phase I Stage 3 は kick を mass で gate する",
    "Phase I Stage 4 は Hooke を mass で amplify する",
    "Mass conservation: 内輪取引は mass を増やさない",
    "Black hole: mass が θ を超えると attractor 化",
    "Persona は declared value/intention/commitment で構成",
    "Dream loop は背景でリプレイを行う",
    "Genesis kick は新規ノードに初期 displacement を与える",
    "Supernova cohort は batch を超新星爆発として扱う",
    "RRF fusion は rank scale invariant な統合",
    "Co-occurrence graph は LLM が返した結果で更新",
    "Articulation as Carrier — 言葉にすることが重力を生む",
    "Stub embedder は md5 seed で決定論的",
    "Virtual FAISS は raw + displacement の正規化版",
    "Wave depth 3 で約 60-150 ノードに到達",
    "Tag filter は seed/final 両段階で force-inject",
    "Source filter は sparse class の seed 入場を救う",
    "Forced ordering は raw_score 順に並び替え",
    "Acceptance test は opencode で独立観察",
    "Five-Layer philosophy: 物理→生物→TTT→関係→人格",
    "compact(rebuild_faiss=True) は FAISS 全再構築",
    "Migration ledger は idempotent な版管理",
    "Dev branch から main への PR は merge commit",
    "Reflect aspect で persona/tasks を集計",
    "Bench は scripts/run_benchmark_isolated.sh で隔離",
    "Wave seed redesign で sparse class が seed 入場",
]

QUERIES = [
    "永続化はどう実装する",
    "BM25 の役割は",
    "Phase I Stage 4 の物理",
    "黒い穴の閾値",
    "夢の loop は何をする",
    "ペルソナの構成要素",
    "RRF の特徴は",
    "Wave の深さは",
]


async def _run(data_dir: Path, overrides: dict, recall_repeats: int) -> dict:
    """Ingest CORPUS once, run QUERIES `recall_repeats` times each, snapshot."""
    # Wipe leftovers so cold start
    if data_dir.exists():
        for f in data_dir.iterdir():
            if f.is_file():
                f.unlink()
    data_dir.mkdir(parents=True, exist_ok=True)

    engine = make_engine(data_dir, **overrides)
    await engine.startup()
    try:
        await engine.index_documents([{"content": c, "metadata": {"source": "agent"}} for c in CORPUS])
        await engine.cache.flush_to_store(engine.store)

        top5_per_query: list[list[str]] = []
        for q in QUERIES:
            contents: list[str] = []
            for _ in range(recall_repeats):
                results = await engine.query(text=q, top_k=5)
                # Compare by content — node IDs are UUIDs that differ per run.
                contents = [r.content for r in results]
            top5_per_query.append(contents)

        # Snapshot per-node dynamics
        displacements_norm: list[float] = []
        masses: list[float] = []
        # Force a flush so we read post-recall state
        await engine.cache.flush_to_store(engine.store)
        states = await engine.store.get_all_node_states()
        for s in states:
            if s.is_archived:
                continue
            masses.append(float(s.mass))
            disp = engine.cache.get_displacement(s.id)
            d_norm = 0.0 if disp is None else float(np.linalg.norm(disp))
            displacements_norm.append(d_norm)

        return {
            "n_active": len(masses),
            "displacement": _stats(displacements_norm),
            "mass": _stats(masses),
            "top5_per_query": top5_per_query,
        }
    finally:
        await engine.shutdown()


def _stats(values: list[float]) -> dict:
    if not values:
        return {"p50": 0.0, "p90": 0.0, "p99": 0.0, "max": 0.0, "mean": 0.0}
    s = sorted(values)

    def pct(p: float) -> float:
        idx = int(round((p / 100.0) * (len(s) - 1)))
        return s[idx]

    return {
        "p50": pct(50),
        "p90": pct(90),
        "p99": pct(99),
        "max": s[-1],
        "mean": mean(values),
    }


def _jaccard(a: list[str], b: list[str]) -> float:
    sa, sb = set(a), set(b)
    if not sa and not sb:
        return 1.0
    return len(sa & sb) / max(1, len(sa | sb))


async def _main_async(args):
    overrides_a = json.loads(args.overrides_a) if args.overrides_a else {}
    overrides_b = json.loads(args.overrides_b) if args.overrides_b else {}

    print(f"[diag_dynamics] running A ({args.label_a}) with overrides={overrides_a}")
    a = await _run(Path(args.data_dir_a), overrides_a, args.recall_repeats)
    print(f"[diag_dynamics] running B ({args.label_b}) with overrides={overrides_b}")
    b = await _run(Path(args.data_dir_b), overrides_b, args.recall_repeats)

    # Top-5 stability between A and B
    overlaps = []
    for ids_a, ids_b in zip(a["top5_per_query"], b["top5_per_query"]):
        overlaps.append(_jaccard(ids_a, ids_b))

    report = {
        "label_a": args.label_a,
        "label_b": args.label_b,
        "overrides_a": overrides_a,
        "overrides_b": overrides_b,
        "recall_repeats_per_query": args.recall_repeats,
        "corpus_size": len(CORPUS),
        "queries": len(QUERIES),
        "a": {
            "n_active": a["n_active"],
            "displacement": a["displacement"],
            "mass": a["mass"],
        },
        "b": {
            "n_active": b["n_active"],
            "displacement": b["displacement"],
            "mass": b["mass"],
        },
        "top5_jaccard": {
            "per_query": [round(o, 3) for o in overlaps],
            "mean": round(mean(overlaps), 3),
            "min": round(min(overlaps), 3),
        },
        "displacement_delta_pct": {
            k: _pct_change(a["displacement"][k], b["displacement"][k])
            for k in ("p50", "p90", "p99", "max", "mean")
        },
        "mass_delta_pct": {
            k: _pct_change(a["mass"][k], b["mass"][k])
            for k in ("p50", "p90", "p99", "max", "mean")
        },
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"\n[diag_dynamics] report written to {out}\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))


def _pct_change(before: float, after: float) -> str:
    if before == 0:
        return "—" if after == 0 else "+∞"
    return f"{(after - before) / before * 100.0:+.1f}%"


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--label-a", default="A")
    parser.add_argument("--label-b", default="B")
    parser.add_argument("--overrides-a", default="", help="JSON config overrides for run A")
    parser.add_argument("--overrides-b", default="", help="JSON config overrides for run B")
    parser.add_argument("--data-dir-a", default=str(_PROJECT_ROOT / ".diag-dynamics-a"))
    parser.add_argument("--data-dir-b", default=str(_PROJECT_ROOT / ".diag-dynamics-b"))
    parser.add_argument("--recall-repeats", type=int, default=5, help="how many times to repeat each query")
    parser.add_argument("--out", default=str(_PROJECT_ROOT / ".diag-dynamics-report.json"))
    args = parser.parse_args()
    asyncio.run(_main_async(args))


if __name__ == "__main__":
    main()
