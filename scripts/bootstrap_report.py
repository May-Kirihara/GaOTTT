"""Read-only post-ingest summary for a fresh GaOTTT store.

Run this once after a bulk `ingest` / `load_files` / `load_csv` pass to see
what the gravitational landscape looks like **before any recalls have
happened**. Nothing here writes to the DB and no LLM is called — it is a
snapshot of the embedding-space state, and a preview of the attractions
that will form once the user starts recalling.

Usage:
    # Default (reads the same data dir as the MCP server)
    .venv/bin/python scripts/bootstrap_report.py

    # Custom sample size / neighbor k / duplicate threshold
    .venv/bin/python scripts/bootstrap_report.py --sample 20 --neighbor-k 5 --dup-threshold 0.9

    # Reproducible sampling
    .venv/bin/python scripts/bootstrap_report.py --seed 42

Sections:
    1. Summary         — total memories + source distribution + displacement stats
    2. Duplicates      — near-duplicate clusters (threshold tunable)
    3. Neighbor preview — for N random nodes, show their top-K FAISS
                         neighbors in both raw and virtual (= raw +
                         displacement) embedding space. Raw is the static
                         sky; virtual reveals where each star has drifted
                         under recall attraction. Pairs that diverge
                         between the two views are nodes whose Phase I/J
                         displacement has reshaped their local geometry.
                         These pairs will form co-occurrence edges the
                         first time both get recalled together.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import sys
from pathlib import Path

import numpy as np

# Allow direct invocation (`python scripts/bootstrap_report.py`) as well as
# `python -m scripts.bootstrap_report`. The editable install can go stale
# if the project directory is renamed, so we fall back to the parent path.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from gaottt.config import GaOTTTConfig  # noqa: E402
from gaottt.core.engine import GaOTTTEngine  # noqa: E402
from gaottt.services.runtime import build_engine  # noqa: E402

SNIPPET_LEN = 80


async def _load_engine(use_virtual: bool) -> GaOTTTEngine:
    config = GaOTTTConfig.from_config_file()
    # Read-only diagnostic — never write back periodically. Disabling
    # both write-behind loops prevents this tool from racing with a live
    # MCP server (and saves the FAISS save thread we never need).
    config.faiss_save_interval_seconds = 0.0
    config.virtual_faiss_save_interval_seconds = 0.0
    config.dream_enabled = False
    if not use_virtual:
        config.virtual_faiss_enabled = False
    engine = build_engine(config)
    await engine.startup()
    return engine


def _snippet(text: str, limit: int = SNIPPET_LEN) -> str:
    return (text or "").replace("\n", " ")[:limit]


async def _print_summary(engine: GaOTTTEngine) -> int:
    nodes = engine.cache.get_all_nodes()
    edges = engine.cache.get_all_edges()
    sources: dict[str, int] = {}
    for n in nodes:
        doc = await engine.store.get_document(n.id)
        if doc:
            s = (doc.get("metadata") or {}).get("source", "unknown")
            sources[s] = sources.get(s, 0) + 1

    print("=" * 72)
    print("  Section 1 — Summary")
    print("=" * 72)
    print(f"  Total memories:     {len(nodes)}")
    print(f"  FAISS vectors:      {engine.faiss_index.size}")
    if engine.virtual_faiss_index is not None:
        print(f"  Virtual FAISS:      {engine.virtual_faiss_index.size}  "
              f"(raw + cached displacement, normalized)")
    else:
        print("  Virtual FAISS:      disabled")
    print(f"  Co-occurrence edges: {len(edges)}  "
          f"(will grow once `recall` is used)")
    print(f"  Sources:            {json.dumps(sources, ensure_ascii=False)}")

    # Displacement stats — Phase I/J query attraction accumulates here.
    # A healthy gravity model has small displacements (Hooke + decay keep
    # most nodes near raw embedding); p90 > 1.0 or a long tail signals
    # gravity-well territory (see scripts/reset_displacements.py).
    disps = [
        float(np.linalg.norm(d)) for d in engine.cache.displacement_cache.values()
        if d is not None
    ]
    if disps:
        arr = np.array(disps, dtype=np.float32)
        print(f"  Displacement norms (n={len(arr)}): "
              f"min={arr.min():.4f}  p50={np.median(arr):.4f}  "
              f"p90={np.percentile(arr, 90):.4f}  "
              f"p99={np.percentile(arr, 99):.4f}  max={arr.max():.4f}")
        print(f"    |d| > 0.3: {int((arr > 0.3).sum())}  "
              f"|d| > 1.0: {int((arr > 1.0).sum())}  "
              f"|d| > 3.0: {int((arr > 3.0).sum())}")
    else:
        print("  Displacement norms: (cache empty — no priming/attraction yet)")
    print()
    return len(nodes)


async def _print_duplicates(engine: GaOTTTEngine, threshold: float, limit: int) -> None:
    print("=" * 72)
    print(f"  Section 2 — Near-duplicate clusters (threshold {threshold})")
    print("=" * 72)
    clusters = engine.find_duplicates(threshold=threshold, top_n_by_mass=None)
    if not clusters:
        print(f"  No near-duplicate clusters above {threshold}.")
        print("  (Lower --dup-threshold if you expect soft duplicates to surface.)")
        print()
        return

    print(f"  Found {len(clusters)} cluster(s); showing top {min(limit, len(clusters))}.")
    print("  Use `merge(node_ids=[...])` via MCP if you want to collapse any of these.")
    print()
    for i, cluster in enumerate(clusters[:limit], start=1):
        print(f"  [Cluster {i}] {len(cluster.ids)} nodes, "
              f"avg_pairwise_sim={cluster.avg_pairwise_similarity:.3f}")
        for nid in cluster.ids:
            doc = await engine.store.get_document(nid)
            content = _snippet(doc.get("content", "") if doc else "?")
            print(f"    - {nid[:8]}.. | {content}")
        print()


async def _print_neighbor_preview(
    engine: GaOTTTEngine,
    total_nodes: int,
    sample_n: int,
    neighbor_k: int,
    seed: int | None,
) -> None:
    has_virtual = (
        engine.virtual_faiss_index is not None
        and engine.virtual_faiss_index.size > 0
    )
    label = "raw + virtual" if has_virtual else "raw"
    print("=" * 72)
    print(f"  Section 3 — Neighbor preview  "
          f"(sample {sample_n}, top-{neighbor_k} per node, {label})")
    print("=" * 72)
    print(
        "  Each block shows an anchor node and its closest embedding neighbors.\n"
        "  These pairs do not yet share a co-occurrence edge — they will the\n"
        "  first time they appear together in a `recall` result (edge weight\n"
        "  accumulates with every co-retrieval, until they're gravitationally\n"
        "  linked)."
    )
    if has_virtual:
        print(
            "  Both raw and virtual FAISS views are shown. Raw is the static\n"
            "  embedding sky; virtual = raw + cached displacement, so ids that\n"
            "  appear in virtual but not raw are nodes that drifted into the\n"
            "  anchor's neighborhood via Phase I/J recall attraction or Phase G\n"
            "  priming. The 'Δ' line lists those drift-in ids — those are the\n"
            "  edges Phase H Stage 5 wave propagation now sees that legacy\n"
            "  raw-only neighbor search missed."
        )
    print()

    if total_nodes == 0:
        print("  No memories in store yet — nothing to preview.")
        print()
        return

    rng = random.Random(seed)
    all_ids = [n.id for n in engine.cache.get_all_nodes()]
    if not all_ids:
        print("  Cache has no nodes (did ingest complete?).")
        print()
        return

    sample_ids = rng.sample(all_ids, min(sample_n, len(all_ids)))

    for i, nid in enumerate(sample_ids, start=1):
        anchor_doc = await engine.store.get_document(nid)
        anchor_text = _snippet(anchor_doc.get("content", "") if anchor_doc else "?")
        disp = engine.cache.get_displacement(nid)
        disp_tag = (
            f"  |d|={float(np.linalg.norm(disp)):.3f}"
            if disp is not None else ""
        )
        print(f"  [{i}] {nid[:8]}..{disp_tag} | {anchor_text}")

        raw_neighbors = engine.faiss_index.search_by_id(nid, neighbor_k + 1)
        raw_neighbors = [
            (nb_id, score) for nb_id, score in raw_neighbors if nb_id != nid
        ][:neighbor_k]

        if not raw_neighbors:
            print("      (no neighbors — is the FAISS index populated?)")
            print()
            continue

        print("    raw:")
        for nb_id, score in raw_neighbors:
            nb_doc = await engine.store.get_document(nb_id)
            nb_text = _snippet(nb_doc.get("content", "") if nb_doc else "?")
            print(f"      sim={score:.3f}  {nb_id[:8]}.. | {nb_text}")

        if has_virtual:
            virt_neighbors = engine.virtual_faiss_index.search_by_id(
                nid, neighbor_k + 1,
            )
            virt_neighbors = [
                (nb_id, score) for nb_id, score in virt_neighbors
                if nb_id != nid
            ][:neighbor_k]
            print("    virtual (raw + displacement):")
            if not virt_neighbors:
                print("      (no virtual neighbors — index empty for this id?)")
            else:
                for nb_id, score in virt_neighbors:
                    nb_doc = await engine.store.get_document(nb_id)
                    nb_text = _snippet(
                        nb_doc.get("content", "") if nb_doc else "?"
                    )
                    print(f"      sim={score:.3f}  {nb_id[:8]}.. | {nb_text}")

            raw_set = {nb_id for nb_id, _ in raw_neighbors}
            virt_set = {nb_id for nb_id, _ in virt_neighbors}
            drift_in = virt_set - raw_set
            drift_out = raw_set - virt_set
            if drift_in or drift_out:
                marks = []
                if drift_in:
                    marks.append(
                        "+" + ",".join(sorted(nid[:8] for nid in drift_in))
                    )
                if drift_out:
                    marks.append(
                        "-" + ",".join(sorted(nid[:8] for nid in drift_out))
                    )
                print(f"    Δ: {'  '.join(marks)}")
        print()


async def _readonly_close(engine: GaOTTTEngine) -> None:
    """Close resources without persisting state.

    We deliberately skip engine.shutdown() (which flushes cache + saves
    FAISS) because this tool reads only — rewriting the snapshot could
    race with a live MCP server writing newer state. Both write-behind
    loops are disabled in `_load_engine` so there's nothing periodic to
    stop here beyond the cache loop.
    """
    await engine.prefetch_pool.drain(timeout=5.0)
    await engine.cache.stop_write_behind()
    await engine.store.close()


async def run(args: argparse.Namespace) -> int:
    engine = await _load_engine(use_virtual=not args.no_virtual)
    try:
        total = await _print_summary(engine)
        await _print_duplicates(engine, args.dup_threshold, args.dup_limit)
        await _print_neighbor_preview(
            engine, total, args.sample, args.neighbor_k, args.seed,
        )

        print("=" * 72)
        print("  Done — no data written. The gravitational landscape above is")
        print("  the raw attraction potential. It starts filling in as soon as")
        print("  you begin `recall`ing: edges form, mass accretes, wells deepen.")
        print("=" * 72)
    finally:
        await _readonly_close(engine)
    return 0


def main() -> int:
    p = argparse.ArgumentParser(
        description="Read-only post-ingest summary of a GaOTTT store.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "This command never writes to the DB and never calls an LLM.\n"
            "Run it right after `ingest` to get a feel for what's in there,\n"
            "then start using the MCP tools and let the gravity build up."
        ),
    )
    p.add_argument("--sample", type=int, default=10,
                   help="Number of random anchors for neighbor preview (default 10).")
    p.add_argument("--neighbor-k", type=int, default=5,
                   help="Top-K neighbors to show per anchor (default 5).")
    p.add_argument("--dup-threshold", type=float, default=0.95,
                   help="Cosine-similarity threshold for duplicate detection (default 0.95).")
    p.add_argument("--dup-limit", type=int, default=10,
                   help="Max number of duplicate clusters to print (default 10).")
    p.add_argument("--seed", type=int, default=None,
                   help="Seed for sample-selection RNG (reproducible).")
    p.add_argument("--no-virtual", action="store_true",
                   help="Skip virtual FAISS load + comparison (raw only). "
                        "Useful when running against an old data dir that "
                        "has no gaottt.virtual.faiss yet.")
    args = p.parse_args()

    return asyncio.run(run(args))


if __name__ == "__main__":
    sys.exit(main())
