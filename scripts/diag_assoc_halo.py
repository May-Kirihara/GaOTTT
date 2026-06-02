"""Accretion Recall go/no-go — associative-halo reachability diagnostic.

Read-only measurement that answers the ONE question gating the proposed
``explore(mode="associative")`` (Accretion Recall, ``降着想起``) feature:

  For a recollection query ("〇〇ってなんだっけ"), do the strongest hits
  (the recollection *anchors*) have co-occurrence neighbors that the
  geometric wave would NOT reach because they sit far from the query in
  embedding space?

  - If YES (many "novel-far" halo members)  → the wave's geometric
    traversal cannot surface them, so an association-conducted pull has
    something real to summon. Accretion Recall earns its keep.
  - If NO (halo ⊆ geometric reach)          → co-occurrence is redundant
    with the embedding sky; the existing ``explore`` already covers it and
    co-occurrence stays a trust-layer signal. Don't build the mode.

Why this is the honest first step (not code): the whole feature is a bet
that "association reaches where geometry can't". This script measures that
gap directly, against the production gravity field, before a line of the
mode is written. See ``docs/wiki/Plans-Accretion-Recall.md``.

Definitions (per query)
-----------------------
  anchors      engine.query(query, top_k=--anchor-k, passive=True) — the
               recollection centre's strongest hits.
  raw halo     ∪ over anchors of cache.get_neighbors(anchor) — the
               co-occurrence neighbourhood (minus the anchors themselves).
  kept halo    raw halo MINUS same-original / same-cohort siblings, dropped
               via ``is_self_force_by_id`` — exactly the gate Accretion
               Recall would apply so a 1-chunk book hit does not drag its
               637 sibling chunks (ingest artifact) into the summon.
  reach pool   raw FAISS top-``--reach-n`` of the query vector — a proxy for
               "what the geometric wave would seed". (Proxy: the live wave
               also seeds from virtual FAISS + BM25 and expands neighbours;
               raw cosine is the first-order static-sky reach. A halo member
               outside this pool may still be reached via virtual/BM25 — so
               novel-far is an UPPER bound on accretion's unique catch.)
  reach floor  cosine of the ``--reach-n``-th raw hit — the weakest cosine
               that still entered the seed pool.
  NOVEL-FAR    kept-halo members that are (a) outside the reach pool AND
               (b) below the reach floor in cosine to the query. These are
               the nodes accretion would uniquely summon.

This is a **read-only** tool. It uses the same ``build_engine`` factory as
the production server but disables the write-behind loops and the dream
loop, and runs the anchor query with ``passive=True`` (no mass update, no
displacement nudge, no co-occurrence write). It shares the FAISS / SQLite
files read-only — do not run it while another process is mid-``compact``.

Usage::

    # Single recollection-style probe against the production DB
    .venv/bin/python scripts/diag_assoc_halo.py --query "あの重力の探索の話なんだっけ"

    # A list of probes (JSON list of strings or {"query": ...} records)
    .venv/bin/python scripts/diag_assoc_halo.py \\
        --queries-file tests/perf/golden_corpus/queries.json

    # Machine-readable output for snapshotting
    .venv/bin/python scripts/diag_assoc_halo.py --queries-file q.json --json

    # Isolated DB (never touches production)
    .venv/bin/python scripts/diag_assoc_halo.py --query "..." --data-dir /tmp/xxx
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

import numpy as np

# Allow direct invocation even if the editable install path went stale
# (mirrors scripts/diag_recall.py).
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from gaottt.config import GaOTTTConfig  # noqa: E402
from gaottt.core.engine import GaOTTTEngine  # noqa: E402
from gaottt.core.gravity import is_self_force_by_id  # noqa: E402
from gaottt.services.runtime import build_engine  # noqa: E402


def _normalize(v: np.ndarray) -> np.ndarray:
    """L2-normalize so an inner product reads as cosine. FAISS stores
    normalized vectors (IndexFlatIP used as cosine), but encode_query and
    reconstructed vectors are normalized defensively here regardless."""
    n = float(np.linalg.norm(v))
    return v if n < 1e-12 else v / n


async def _load_engine(data_dir: str | None) -> GaOTTTEngine:
    if data_dir is not None:
        config = GaOTTTConfig(data_dir=data_dir)
    else:
        config = GaOTTTConfig.from_config_file()
    # Read-only: never let this diagnostic's process write the field back.
    config.faiss_save_interval_seconds = 0.0
    config.virtual_faiss_save_interval_seconds = 0.0
    config.dream_enabled = False
    engine = build_engine(config)
    await engine.startup()
    return engine


def _percentile(sorted_vals: list[float], p: float) -> float:
    """Linear-interp percentile of a SORTED list. p in [0, 100]."""
    if not sorted_vals:
        return float("nan")
    if p <= 0:
        return sorted_vals[0]
    if p >= 100:
        return sorted_vals[-1]
    pos = (p / 100.0) * (len(sorted_vals) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = pos - lo
    return sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac


async def _analyze_query(
    engine: GaOTTTEngine,
    query: str,
    anchor_k: int,
    reach_n: int,
    far_threshold: float | None,
    examples: int,
    source_filter: list[str] | None = None,
    assoc_mode: str = "none",
    hub_cut: float | None = None,
    decay_half_life: float | None = None,
) -> dict:
    cache = engine.cache
    # encode_query returns a (1, dim) batch; flatten so np.dot reads as a
    # scalar cosine against the (dim,) reconstructed halo vectors.
    qv = _normalize(np.asarray(engine.embedder.encode_query(query)).reshape(-1))

    # 1. Anchors — recollection centre's strongest hits (passive = read-only).
    #    ``source_filter`` lets a run pin anchors to self-authored classes
    #    (agent / value / ...), which carry the cross-document co-occurrence
    #    edges; without it, dense bulk-ingest clusters win anchor selection on
    #    a corpus-heavy DB and the halo is all same-cohort artifact.
    anchors = await engine.query(
        text=query, top_k=anchor_k, passive=True, source_filter=source_filter,
    )
    anchor_ids = [a.id for a in anchors]
    anchor_set = set(anchor_ids)

    # 2. Geometric reach pool — proxy for "what the wave would seed".
    raw_hits = (
        engine.faiss_index.search(qv.reshape(1, -1), reach_n)
        if engine.faiss_index.size > 0 else []
    )
    reach_set = {nid for nid, _ in raw_hits}
    reach_floor = raw_hits[-1][1] if raw_hits else 0.0
    floor = far_threshold if far_threshold is not None else reach_floor

    # 3. Gather the co-occurrence halo of the anchors, applying the
    #    self-force gate per (anchor, neighbour) pair. A halo member is
    #    "kept" iff at least one anchor links to it across a document /
    #    cohort boundary (a genuine cross-domain association, not an
    #    internal-trade ingest artifact). ``weight`` is the Stage 8
    #    association strength under ``assoc_mode`` ("none" = raw co-recall
    #    count, identical to the legacy gather); ``hub_cut`` drops high-
    #    degree neighbours before they enter the halo at all.
    halo: dict[str, dict] = {}
    for aid in anchor_ids:
        assoc = cache.get_association_strength(
            aid, mode=assoc_mode, hub_degree_cut=hub_cut,
            decay_half_life=decay_half_life,
        )
        for nid, w in assoc.items():
            if nid in anchor_set:
                continue  # anchor-anchor edges are not halo
            rec = halo.setdefault(
                nid, {"weight": 0.0, "nonself": False, "links": 0, "self_links": 0},
            )
            rec["links"] += 1
            if is_self_force_by_id(cache, aid, nid):
                rec["self_links"] += 1
            else:
                rec["nonself"] = True
                rec["weight"] = max(rec["weight"], w)

    raw_halo_n = len(halo)
    kept = {nid: r for nid, r in halo.items() if r["nonself"]}

    # 4. cosine(query, halo member) via reconstructed FAISS vectors.
    vecs = engine.faiss_index.get_vectors(list(kept.keys())) if kept else {}
    rows: list[dict] = []
    for nid, r in kept.items():
        v = vecs.get(nid)
        cos = float(np.dot(qv, _normalize(v))) if v is not None else None
        in_reach = nid in reach_set
        far = cos is not None and cos < floor
        rows.append({
            "id": nid,
            "weight": r["weight"],
            "degree": cache.get_degree(nid, decay_half_life=decay_half_life),
            "cosine": cos,
            "in_reach": in_reach,
            "far": far,
            "novel_far": (not in_reach) and far,
        })

    cosines = sorted(x["cosine"] for x in rows if x["cosine"] is not None)
    novel_far = [x for x in rows if x["novel_far"]]
    novel_far.sort(key=lambda x: x["weight"], reverse=True)

    # 5. Content previews for the strongest novel-far summons, so a human
    #    can eyeball whether they are meaningful lateral associations.
    example_rows: list[dict] = []
    for x in novel_far[:examples]:
        doc = await engine.store.get_document(x["id"])
        preview = (doc.get("content", "")[:80] if doc else "?").replace("\n", " ")
        example_rows.append({
            "id": x["id"], "weight": round(x["weight"], 4),
            "degree": round(x["degree"], 1),
            "cosine": round(x["cosine"], 4), "preview": preview,
        })

    return {
        "query": query,
        "assoc_mode": assoc_mode,
        "anchors": len(anchor_ids),
        "raw_halo": raw_halo_n,
        "artifact_dropped": raw_halo_n - len(kept),
        "kept_halo": len(kept),
        "reach_floor": round(reach_floor, 4),
        "halo_in_reach": sum(1 for x in rows if x["in_reach"]),
        "novel_far": len(novel_far),
        "cosine_dist": {
            "min": round(cosines[0], 4) if cosines else None,
            "p25": round(_percentile(cosines, 25), 4) if cosines else None,
            "median": round(_percentile(cosines, 50), 4) if cosines else None,
            "p75": round(_percentile(cosines, 75), 4) if cosines else None,
            "max": round(cosines[-1], 4) if cosines else None,
        },
        "examples": example_rows,
    }


def _print_query(d: dict, reach_n: int) -> None:
    print(f"\nQuery: {d['query']!r}  (assoc_mode={d.get('assoc_mode', 'none')})")
    print(f"  anchors:                  {d['anchors']}")
    art = d["artifact_dropped"]
    raw = d["raw_halo"]
    pct = (art / raw * 100.0) if raw else 0.0
    print(f"  raw halo:                 {raw}  "
          f"(self-force artifacts dropped: {art}, {pct:.0f}%)")
    print(f"  kept halo:                {d['kept_halo']}")
    cd = d["cosine_dist"]
    if cd["median"] is not None:
        print(f"  halo cosine→q:            min={cd['min']}  p25={cd['p25']}  "
              f"median={cd['median']}  p75={cd['p75']}  max={cd['max']}")
    print(f"  geometric reach floor:    {d['reach_floor']}  "
          f"(raw top-{reach_n} weakest cosine)")
    print(f"  halo already in reach:    {d['halo_in_reach']} / {d['kept_halo']}")
    print(f"  >> NOVEL-FAR:             {d['novel_far']} / {d['kept_halo']}  "
          f"(outside reach pool AND below floor — accretion's unique catch)")
    for ex in d["examples"]:
        print(f"       [w={ex['weight']} deg={ex['degree']} cos={ex['cosine']}] "
              f"{ex['preview']}")


async def main_async(args: argparse.Namespace) -> None:
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

    engine = await _load_engine(args.data_dir)
    try:
        decay_hl = (
            args.decay_half_life_days * 86400.0
            if args.decay_half_life_days else None
        )
        results = []
        for q in queries:
            results.append(await _analyze_query(
                engine, q, args.anchor_k, args.reach_n,
                args.far_threshold, args.examples, args.source_filter,
                args.assoc_mode, args.hub_degree_cut, decay_hl,
            ))
        faiss_size = engine.faiss_index.size
    finally:
        await engine.shutdown()

    if args.json:
        print(json.dumps({
            "n_queries": len(results),
            "faiss_size": faiss_size,
            "anchor_k": args.anchor_k,
            "reach_n": args.reach_n,
            "far_threshold": args.far_threshold,
            "assoc_mode": args.assoc_mode,
            "hub_degree_cut": args.hub_degree_cut,
            "decay_half_life_days": args.decay_half_life_days,
            "queries": results,
        }, ensure_ascii=False, indent=2))
        return

    print(f"FAISS size: {faiss_size:,}   anchor-k: {args.anchor_k}   "
          f"reach-n: {args.reach_n}   assoc-mode: {args.assoc_mode}"
          + (f"   hub-cut: p{args.hub_degree_cut}" if args.hub_degree_cut else "")
          + (f"   decay-T½: {args.decay_half_life_days}d" if args.decay_half_life_days else ""))
    for d in results:
        _print_query(d, args.reach_n)

    # ---- Aggregate go/no-go reading ----
    total_kept = sum(d["kept_halo"] for d in results)
    total_novel = sum(d["novel_far"] for d in results)
    with_novel = sum(1 for d in results if d["novel_far"] > 0)
    mean_novel = total_novel / len(results) if results else 0.0
    print("\n" + "=" * 64)
    print(f"AGGREGATE over {len(results)} queries")
    print("=" * 64)
    print(f"  total kept halo:                {total_kept}")
    print(f"  total novel-far:                {total_novel}")
    print(f"  queries with >=1 novel-far:     {with_novel} / {len(results)}")
    print(f"  mean novel-far per query:       {mean_novel:.1f}")
    print(
        "\nGo/No-go reading:\n"
        "  novel-far consistently >0 (say mean >=2, most queries hit)\n"
        "      → association REACHES where geometry can't. The mechanism\n"
        "        premise holds: there are embedding-far nodes the wave would\n"
        "        not seed. Necessary, but NOT sufficient (see quality caveat).\n"
        "  novel-far ~0 across queries\n"
        "      → the kept halo is already inside the geometric reach pool;\n"
        "        co-occurrence is redundant with the embedding sky. Leave it\n"
        "        as a trust-layer signal, don't build the mode → NO-GO.\n"
        "\n  QUALITY CAVEAT — this count measures reachability, NOT whether the\n"
        "  summons are MEANINGFUL associations. Read the per-query examples:\n"
        "  if the same high-weight node surfaces across unrelated queries, the\n"
        "  halo is hub-dominated (promiscuous co-occurrence / bulk-session\n"
        "  artifact), and accretion would amplify hubs, not surface '〇〇と\n"
        "  いえば〜'. A real GO needs novel-far high AND examples that read as\n"
        "  query-specific lateral associations → otherwise the prerequisite is\n"
        "  co-occurrence-graph hygiene (degree-normalized association strength /\n"
        "  anti-hub on the gather), not the mode itself.\n"
        "\n  Also: novel-far is an UPPER bound (reach pool = raw FAISS only; the\n"
        "  live wave also seeds via virtual FAISS + BM25), and anchor class is\n"
        "  decisive — pin --source-filter to self-authored classes, since bulk-\n"
        "  ingest anchors carry only same-cohort (self-force) halo. See\n"
        "  Plans-Accretion-Recall.md 'Measurement' section."
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--query", help="Single recollection-style query string")
    parser.add_argument(
        "--queries-file",
        help="JSON file: a list of strings or {\"query\": ...} records "
             "(e.g. tests/perf/golden_corpus/queries.json)",
    )
    parser.add_argument(
        "--anchor-k", type=int, default=5,
        help="Top-K hits treated as recollection anchors (default 5)",
    )
    parser.add_argument(
        "--reach-n", type=int, default=200,
        help="Raw FAISS top-N treated as the geometric seed-pool reach "
             "(default 200, ~ wave_seed_pool_size)",
    )
    parser.add_argument(
        "--far-threshold", type=float, default=None,
        help="Absolute cosine below which a halo member counts as 'far'. "
             "Default: per-query dynamic reach floor (the reach-n-th cosine). "
             "Set a fixed value for cross-query-comparable aggregation.",
    )
    parser.add_argument(
        "--examples", type=int, default=3,
        help="How many strongest novel-far summons to preview per query "
             "(default 3, 0 to disable)",
    )
    parser.add_argument(
        "--source-filter", nargs="+", default=None,
        help="Restrict anchors to these source classes (e.g. agent value "
             "intention commitment). Use to pin anchors to self-authored "
             "memos, which carry the cross-document co-occurrence edges.",
    )
    parser.add_argument(
        "--assoc-mode", choices=("none", "cosine", "pmi"), default="none",
        help="Stage 8 association-strength normalization for the halo gather. "
             "'none' = raw co-recall count (legacy). 'cosine'/'pmi' demote "
             "promiscuous hubs by degree — compare examples vs --assoc-mode none "
             "to see whether hubs drop out and query-specific associations rise "
             "(the go/no-go re-check after Stage 8).",
    )
    parser.add_argument(
        "--hub-degree-cut", type=float, default=None,
        help="Drop halo neighbours whose co-occurrence degree exceeds this "
             "percentile of the active degree distribution (explicit anti-hub).",
    )
    parser.add_argument(
        "--decay-half-life-days", type=float, default=None,
        help="Synaptic Pruning: age co-recall weights (and degrees) by this "
             "half-life in days before gather. None = no decay. Lets a run "
             "preview how stale bulk-session cliques fade (read-only, the "
             "store last_update = last reinforcement, so decay is retroactive).",
    )
    parser.add_argument(
        "--data-dir",
        help="Override data_dir (use a /tmp path to avoid the production DB).",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Emit machine-readable JSON instead of the human report.",
    )
    args = parser.parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
