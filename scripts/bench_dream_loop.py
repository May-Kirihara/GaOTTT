#!/usr/bin/env python3
"""Dream loop quantification benchmark — Phase G Stage 2.

Measures the operational effect of the dream consolidation loop on a
fresh isolated DB by comparing co-occurrence edges, node mass, and
sample-query top-K stability before vs after N synthetic dream ticks.

The real dream loop runs in the background on a wall-clock cadence
(`dream_interval_seconds`). This script bypasses the timer and triggers
the same loop body (`_pick_dream_candidates` → `_query_internal(...,
_is_synthetic=True)`) directly, so a 30-tick experiment finishes in a
few seconds instead of half an hour. Same code path, deterministic
schedule.

Output: human-readable summary + optional JSON for trend tracking.

Usage::

    # default — 100 docs, 20 ticks, 5 sample queries
    .venv/bin/python scripts/bench_dream_loop.py

    # bigger experiment
    .venv/bin/python scripts/bench_dream_loop.py --docs 300 --ticks 50 --batch 10

    # write a JSON report
    .venv/bin/python scripts/bench_dream_loop.py --output /tmp/dream.json

    # keep the tmp data dir around for poking afterwards
    .venv/bin/python scripts/bench_dream_loop.py --keep

Never touches your production DB — uses a fresh `/tmp/gaottt-dream-bench-*`
data dir which is wiped at the end unless `--keep` is given.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import statistics
import sys
import tempfile
import time
from pathlib import Path

import numpy as np

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from gaottt.config import GaOTTTConfig  # noqa: E402
from gaottt.services.runtime import build_engine  # noqa: E402

# Real-world-ish content pool. Real RURI embeddings give the dream loop
# realistic neighborhoods; stub embeddings would not produce honest
# consolidation effects. ~50 short Japanese sentences across loose
# topical clusters so co-occurrence has structure to find.
CONTENT_POOL: list[str] = [
    # AI / programming cluster
    "人工知能の進化と将来の社会への影響について考える。",
    "機械学習モデルの精度を上げるためのデータ前処理の重要性。",
    "Python と Rust の使い分けについて最近思うこと。",
    "深層学習の transformer アーキテクチャの直感的理解。",
    "コード品質を保つためのレビュー文化の作り方。",
    "GitHub Actions で CI/CD パイプラインを組む基本。",
    "Vector database を自前で実装する場合の設計判断。",
    "RAG (Retrieval Augmented Generation) の限界と工夫。",
    "LLM の幻覚を抑えるプロンプトエンジニアリング。",
    "Embedding の cosine 距離が意味するもの。",
    # daily life cluster
    "朝のコーヒーを淹れる時間が一日で最も静かなとき。",
    "雨の日の散歩は晴れの日とは違う発見がある。",
    "深夜に書くメモは翌朝読み返すと別人のように感じる。",
    "好きな本を再読すると前回見逃した行に気づく。",
    "新しい街を歩くときの方向感覚を頼りにする楽しさ。",
    "料理は手順より気分の方が味に影響する気がする。",
    "週末の朝寝坊は罪悪感と幸福感が同居している。",
    "猫がそばに来るとなぜか集中力が上がる現象。",
    "音楽を聴きながら歩くと景色が変わって見える。",
    "古いノートを整理していると過去の自分と会話できる。",
    # culture / reading cluster
    "村上春樹の小説に出てくる料理シーンが好きだ。",
    "宮崎駿のアニメで一番好きなシーンを思い出す。",
    "SF 小説における時間旅行のロジック比較。",
    "詩を読むときの呼吸とリズムについて。",
    "ジャズの即興演奏は会話に似ている。",
    "映画館で観るのと家で観るのは別の体験。",
    "短編小説の終わり方が作品全体を決める。",
    "歴史小説の取材ノートが読みたい。",
    "翻訳された言葉の選び方に感心する瞬間。",
    "推理小説の伏線回収の心地よさ。",
    # work / craft cluster
    "良い質問は答えよりも価値があることが多い。",
    "ドキュメントを書くことは自分のためでもある。",
    "リファクタリングは静かな勇気を必要とする。",
    "デバッグは自分の思い込みとの対話だ。",
    "プロトタイプを早く出すと議論が具体的になる。",
    "技術的負債は気づいたときが返済の好機。",
    "設計判断を残すと半年後の自分に感謝される。",
    "コミットメッセージは未来の同僚への手紙。",
    "テストを先に書くと設計の歪みが見える。",
    "ペアプロは集中力の総量が増える不思議。",
    # reflective / philosophical cluster
    "記憶は思い出すたびに少しずつ書き換わる。",
    "対話によって考えが整理されることがある。",
    "毎日同じ景色を見ても気づきが変わる。",
    "言葉にできない感情こそ手帳に書きとめたい。",
    "他人の視点で世界を見るのは知的な運動だ。",
    "余白のある一日に新しいアイデアが浮かぶ。",
    "夢の中の論理は起きてから読み返したい。",
    "良い問いを抱えたまま眠ることの効用。",
    "退屈は創造性の前段階かもしれない。",
    "歩きながら考える方が机より深くなる時間がある。",
]


def _percentile(xs: list[float], p: float) -> float:
    return float(np.percentile(np.array(xs), p)) if xs else 0.0


def _node_mass_distribution(engine) -> dict:
    masses = [s.mass for s in engine.cache.get_all_nodes()]
    if not masses:
        return {"n": 0, "mean": 0.0, "p50": 0.0, "p90": 0.0, "max": 0.0,
                "gt_1_1": 0, "gt_1_5": 0, "gt_2_0": 0}
    return {
        "n": len(masses),
        "mean": statistics.mean(masses),
        "p50": _percentile(masses, 50),
        "p90": _percentile(masses, 90),
        "max": max(masses),
        "gt_1_1": sum(1 for m in masses if m > 1.1),
        "gt_1_5": sum(1 for m in masses if m > 1.5),
        "gt_2_0": sum(1 for m in masses if m > 2.0),
    }


def _edge_weight_distribution(engine) -> dict:
    """Edge weights are what the dream loop actually moves once Phase K
    supernova cohort has already saturated the *count* at index time.
    Count alone is a blunt instrument; weight tells the real story."""
    edges = engine.cache.get_all_edges()
    weights = [e.weight for e in edges]
    if not weights:
        return {"n": 0, "mean": 0.0, "p50": 0.0, "p90": 0.0, "max": 0.0,
                "gt_2_0": 0, "gt_5_0": 0}
    return {
        "n": len(weights),
        "mean": statistics.mean(weights),
        "p50": _percentile(weights, 50),
        "p90": _percentile(weights, 90),
        "max": max(weights),
        "gt_2_0": sum(1 for w in weights if w > 2.0),
        "gt_5_0": sum(1 for w in weights if w > 5.0),
    }


async def _sample_queries_topk(engine, queries: list[str], k: int) -> dict:
    """Run a stable set of probe queries and capture top-K id+score."""
    snapshots: dict[str, list[tuple[str, float]]] = {}
    for q in queries:
        results = await engine.query(text=q, top_k=k)
        snapshots[q] = [(r.id, r.final_score) for r in results]
    return snapshots


def _compare_topk(before: dict, after: dict) -> dict:
    """Per-query: top-K id Jaccard overlap, ordering change, score drift."""
    per_query: list[dict] = []
    for q, before_list in before.items():
        after_list = after.get(q, [])
        bset = {nid for nid, _ in before_list}
        aset = {nid for nid, _ in after_list}
        inter = bset & aset
        union = bset | aset
        jaccard = (len(inter) / len(union)) if union else 1.0

        score_drift = 0.0
        if inter:
            bmap = {nid: s for nid, s in before_list}
            amap = {nid: s for nid, s in after_list}
            drifts = [amap[nid] - bmap[nid] for nid in inter]
            score_drift = statistics.mean(drifts)

        # ordering change: count ids in both lists whose rank moved
        ordering_changes = 0
        if inter:
            b_rank = {nid: i for i, (nid, _) in enumerate(before_list)}
            a_rank = {nid: i for i, (nid, _) in enumerate(after_list)}
            for nid in inter:
                if b_rank[nid] != a_rank[nid]:
                    ordering_changes += 1

        per_query.append({
            "query": q[:40],
            "jaccard": jaccard,
            "common_count": len(inter),
            "before_only": len(bset - aset),
            "after_only": len(aset - bset),
            "ordering_changes": ordering_changes,
            "score_drift": score_drift,
        })

    jaccards = [pq["jaccard"] for pq in per_query]
    drifts = [pq["score_drift"] for pq in per_query]
    return {
        "per_query": per_query,
        "avg_jaccard": statistics.mean(jaccards) if jaccards else 1.0,
        "avg_score_drift": statistics.mean(drifts) if drifts else 0.0,
        "total_ordering_changes": sum(pq["ordering_changes"] for pq in per_query),
        "total_after_only": sum(pq["after_only"] for pq in per_query),
    }


async def _run_dream_tick(engine, batch_size: int) -> int:
    """Trigger one dream tick body. Same code path as the wall-clock loop
    minus the timer wait. Returns the number of candidates synthesized."""
    candidates = engine._pick_dream_candidates(limit=batch_size)
    for nid in candidates:
        doc = await engine.store.get_document(nid)
        if not doc:
            continue
        await engine._query_internal(
            text=doc["content"],
            top_k=engine.config.dream_top_k,
            wave_depth=None,
            wave_k=None,
            _is_synthetic=True,
        )
    return len(candidates)


async def run_bench(args: argparse.Namespace) -> dict:
    data_dir = Path(tempfile.mkdtemp(prefix="gaottt-dream-bench-"))
    print(f"[bench] tmp data dir: {data_dir}")

    config = GaOTTTConfig.from_config_file()
    config.data_dir = str(data_dir)
    config.db_path = str(data_dir / "bench.db")
    config.faiss_index_path = str(data_dir / "bench.faiss")
    config.virtual_faiss_index_path = str(data_dir / "bench.virtual.faiss")
    # Real dream loop off — we drive the tick by hand for determinism.
    config.dream_enabled = False
    # Write-behind loops only slow the benchmark down; final state lives
    # only in memory anyway since we wipe the tmp dir at the end.
    config.faiss_save_interval_seconds = 0.0
    config.virtual_faiss_save_interval_seconds = 0.0
    # Let every just-indexed doc qualify as a dream candidate immediately.
    # The real loop wants min_idle to keep hot nodes out; the benchmark
    # wants the maximum effect-size signal we can measure.
    config.dream_min_idle_seconds = 0.0
    config.dream_mass_ceiling = 10.0
    config.dream_batch_size = args.batch
    # The dream loop's top_k controls how many neighbors get co-recalled
    # per synthetic query — co-occurrence edges form between them.
    config.dream_top_k = args.dream_top_k

    engine = build_engine(config)
    await engine.startup()
    t_start = time.perf_counter()

    try:
        # ---- Index ----
        contents = [CONTENT_POOL[i % len(CONTENT_POOL)] + f"  // doc-{i}"
                    for i in range(args.docs)]
        docs_to_add = [
            {"content": c, "metadata": {"source": "bench"}} for c in contents
        ]
        await engine.index_documents(docs_to_add)
        print(f"[bench] indexed {args.docs} docs "
              f"(pool size {len(CONTENT_POOL)})")

        # Probe queries — sample from the pool (not the indexed-with-suffix
        # variants) so the embedding lands near multiple cluster members.
        rng = np.random.default_rng(args.seed)
        probe_indices = rng.choice(
            len(CONTENT_POOL),
            size=min(args.queries, len(CONTENT_POOL)),
            replace=False,
        )
        probe_queries = [CONTENT_POOL[i] for i in probe_indices]

        # ---- Snapshot 0 ----
        s0_edges = len(engine.cache.get_all_edges())
        s0_edge_w = _edge_weight_distribution(engine)
        s0_mass = _node_mass_distribution(engine)
        s0_probes = await _sample_queries_topk(
            engine, probe_queries, args.probe_topk,
        )
        print(f"[bench] snapshot 0  edges={s0_edges} "
              f"(w_mean={s0_edge_w['mean']:.3f})  "
              f"mean_mass={s0_mass['mean']:.3f}  "
              f"|m>1.1|={s0_mass['gt_1_1']}")

        # ---- Dream ticks ----
        total_synth = 0
        for tick in range(args.ticks):
            n = await _run_dream_tick(engine, args.batch)
            total_synth += n
            if (tick + 1) % max(1, args.ticks // 5) == 0:
                print(f"[bench]   tick {tick + 1}/{args.ticks} "
                      f"({n} synthetic recalls)")

        # ---- Snapshot 1 ----
        s1_edges = len(engine.cache.get_all_edges())
        s1_edge_w = _edge_weight_distribution(engine)
        s1_mass = _node_mass_distribution(engine)
        s1_probes = await _sample_queries_topk(
            engine, probe_queries, args.probe_topk,
        )
        topk_diff = _compare_topk(s0_probes, s1_probes)

        elapsed = time.perf_counter() - t_start
        print(f"[bench] done in {elapsed:.1f}s, "
              f"{total_synth} synthetic recalls across {args.ticks} ticks")

        return {
            "config": {
                "docs": args.docs,
                "ticks": args.ticks,
                "batch": args.batch,
                "dream_top_k": args.dream_top_k,
                "probe_queries": len(probe_queries),
                "probe_topk": args.probe_topk,
            },
            "elapsed_seconds": elapsed,
            "total_synthetic_recalls": total_synth,
            "before": {
                "edges": s0_edges, "edge_weight": s0_edge_w, "mass": s0_mass,
            },
            "after": {
                "edges": s1_edges, "edge_weight": s1_edge_w, "mass": s1_mass,
            },
            "delta": {
                "edges": s1_edges - s0_edges,
                "edge_weight_mean": s1_edge_w["mean"] - s0_edge_w["mean"],
                "edge_weight_max": s1_edge_w["max"] - s0_edge_w["max"],
                "edges_gt_2_0": s1_edge_w["gt_2_0"] - s0_edge_w["gt_2_0"],
                "mean_mass": s1_mass["mean"] - s0_mass["mean"],
                "max_mass": s1_mass["max"] - s0_mass["max"],
                "nodes_gt_1_1": s1_mass["gt_1_1"] - s0_mass["gt_1_1"],
            },
            "topk_stability": topk_diff,
        }
    finally:
        await engine.shutdown()
        if not args.keep:
            shutil.rmtree(data_dir, ignore_errors=True)
        else:
            print(f"[bench] kept tmp data dir: {data_dir}")


def _print_human_summary(report: dict) -> None:
    cfg = report["config"]
    d = report["delta"]
    print()
    print("=" * 72)
    print(f"  Dream loop effect — {cfg['docs']} docs × {cfg['ticks']} ticks "
          f"× batch={cfg['batch']}")
    print("=" * 72)
    print(f"  Elapsed:                {report['elapsed_seconds']:.1f}s "
          f"({report['total_synthetic_recalls']} synthetic recalls)")
    print()
    print("  Edges (count + weight):")
    print(f"    count before → after: {report['before']['edges']} "
          f"→ {report['after']['edges']}    (Δ {d['edges']:+d})")
    bw, aw = report["before"]["edge_weight"], report["after"]["edge_weight"]
    print(f"    weight mean:          {bw['mean']:.3f} → {aw['mean']:.3f}  "
          f"(Δ {d['edge_weight_mean']:+.3f})")
    print(f"    weight max:           {bw['max']:.2f} → {aw['max']:.2f}  "
          f"(Δ {d['edge_weight_max']:+.2f})")
    print(f"    |weight > 2.0|:       {bw['gt_2_0']} → {aw['gt_2_0']}    "
          f"(Δ {d['edges_gt_2_0']:+d})")
    print(f"    |weight > 5.0|:       {bw['gt_5_0']} → {aw['gt_5_0']}")
    print()
    print("  Mass distribution:")
    b, a = report["before"]["mass"], report["after"]["mass"]
    print(f"    mean:                 {b['mean']:.3f} → {a['mean']:.3f}  "
          f"(Δ {d['mean_mass']:+.3f})")
    print(f"    p50 / p90 / max:      {a['p50']:.2f} / {a['p90']:.2f} / "
          f"{a['max']:.2f}")
    print(f"    |mass > 1.1|:         {b['gt_1_1']} → {a['gt_1_1']}    "
          f"(Δ {d['nodes_gt_1_1']:+d})")
    print(f"    |mass > 1.5|:         {b['gt_1_5']} → {a['gt_1_5']}")
    print(f"    |mass > 2.0|:         {b['gt_2_0']} → {a['gt_2_0']}")
    print()
    print("  Probe-query top-K stability:")
    s = report["topk_stability"]
    print(f"    avg jaccard:          {s['avg_jaccard']:.3f}  "
          f"(1.0 = identical top-K, 0.0 = totally different)")
    print(f"    avg score drift:      {s['avg_score_drift']:+.4f}")
    print(f"    total ordering moves: {s['total_ordering_changes']}")
    print(f"    new ids surfaced:     {s['total_after_only']}  "
          f"(in after-set but not before-set)")
    print("=" * 72)
    # quick judgement hint
    expectations = []
    # Phase K supernova saturates edge count at index time, so a Δ count
    # of zero is normal — the meaningful signal is edge weight growth.
    if d["edge_weight_mean"] > 0 or d["edges"] > 0:
        expectations.append("✓ edges reinforced")
    else:
        expectations.append("⚠ edges did not reinforce (dream may be inert)")
    if d["mean_mass"] > 0:
        expectations.append("✓ mean mass grew")
    if s["avg_score_drift"] != 0.0:
        expectations.append("✓ probe scores drifted")
    print(f"  {'   '.join(expectations)}")


def main() -> int:
    p = argparse.ArgumentParser(
        description=(
            "Quantify Phase G Stage 2 dream loop effect on a fresh "
            "isolated DB. Never writes to production data dir."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--docs", type=int, default=100,
                   help="Number of documents to seed the DB with (default 100).")
    p.add_argument("--ticks", type=int, default=20,
                   help="Number of dream ticks to run (default 20).")
    p.add_argument("--batch", type=int, default=5,
                   help="dream_batch_size = candidates per tick (default 5).")
    p.add_argument("--dream-top-k", type=int, default=10,
                   help="top_k each synthetic recall returns; co-occurrence "
                        "edges form between these (default 10).")
    p.add_argument("--queries", type=int, default=5,
                   help="How many probe queries to track top-K stability for "
                        "(default 5).")
    p.add_argument("--probe-topk", type=int, default=5,
                   help="top_k for the probe queries (default 5).")
    p.add_argument("--seed", type=int, default=42,
                   help="RNG seed for probe-query selection (default 42).")
    p.add_argument("--output", default=None,
                   help="Write the JSON report to this path.")
    p.add_argument("--keep", action="store_true",
                   help="Don't delete the tmp data dir after the run "
                        "(useful for poking at the resulting DB).")
    args = p.parse_args()

    report = asyncio.run(run_bench(args))
    _print_human_summary(report)

    if args.output:
        with open(args.output, "w") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        print(f"\n  Report saved to {args.output}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
