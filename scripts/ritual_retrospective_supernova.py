"""Retrospective supernova ritual — backfill Phase K cohort physics
onto memories that were indexed before Phase K Stage 1 existed (or
that were remembered one at a time, below ``supernova_min_cohort_size``).

Phase K Stage 1 fires only at index time. Memories born before Phase K
remain "orphan dust": no mutual co-occurrence edges, no explosion
velocity. They cannot compete for FAISS top-K entry against mature
clusters from prior sessions. This script retroactively applies the
same cohort physics — for a set of related memories (typically
identified by tag), insert all-pairs co-occurrence edges and write
outward initial velocities from the cohort centroid.

⚠️ Bidirectional cache overwrite trap (CLAUDE.md / Architecture-Concurrency.md):
This script writes directly to SQLite. A running MCP server holds an
in-memory cache and periodically flushes its (stale) state back to
disk, which will overwrite this script's edits. The script refuses to
``--apply`` while ``python -m gaottt.server.mcp_server`` is detected.

Recommended sequence:
  1. Stop the gaottt MCP server (and any other long-running gaottt
     processes that share this DB).
  2. ``python scripts/ritual_retrospective_supernova.py
         --tag <tag> --dry-run`` to preview the cohort.
  3. ``--apply`` to write edges + velocities.
  4. Restart the MCP server (it reloads the cache from store on startup
     and will now see the new edges).

Usage examples:
  # Preview a cohort tagged ``harakiriworks-self-knowledge`` (most common
  # case: the 112-memory orphan from the 2026-05-13 session).
  python scripts/ritual_retrospective_supernova.py \\
      --tag harakiriworks-self-knowledge --dry-run

  # Apply (after the MCP server has been stopped):
  python scripts/ritual_retrospective_supernova.py \\
      --tag harakiriworks-self-knowledge --apply

  # Tune the cohort weight / velocity for a specific run:
  python scripts/ritual_retrospective_supernova.py \\
      --tag harakiriworks-self-knowledge --apply \\
      --weight 2.0 --velocity-alpha 0.04
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import subprocess
import sys
import time

import numpy as np

from gaottt.config import GaOTTTConfig
from gaottt.core.supernova import (
    compute_supernova_velocities,
    form_supernova_edges,
)
from gaottt.core.types import CooccurrenceEdge
from gaottt.index.faiss_index import FaissIndex
from gaottt.store.sqlite_store import SqliteStore


logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Retrospectively apply Phase K cohort physics to existing memories.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--tag",
        help=("Substring to match in documents.metadata. Typically a tag like "
              "'harakiriworks-self-knowledge'. Combine with --source for precision."),
    )
    p.add_argument(
        "--source",
        help="Exact source filter (e.g. 'agent'). Combined with --tag.",
    )
    p.add_argument(
        "--ids-file",
        help="Newline-separated id list (overrides --tag/--source).",
    )
    p.add_argument(
        "--weight", type=float, default=1.0,
        help="Initial co-occurrence edge weight (default 1.0 — matches Phase K).",
    )
    p.add_argument(
        "--velocity-alpha", type=float, default=0.03,
        help="Outward velocity α (default 0.03 — matches Phase K default).",
    )
    p.add_argument(
        "--max-cohort-size", type=int, default=200,
        help=("Safety limit. Cohort larger than this aborts (refuse to write "
              "thousands of edges by accident). Default 200."),
    )
    p.add_argument(
        "--dry-run", action="store_true",
        help="Show what would be written; perform no DB writes. Default mode.",
    )
    p.add_argument(
        "--apply", action="store_true",
        help="Actually write to the DB. MCP server must be stopped first.",
    )
    p.add_argument(
        "--verbose", "-v", action="store_true",
        help="Print every edge and velocity (default: sample of 3).",
    )
    args = p.parse_args()
    if not args.dry_run and not args.apply:
        p.error("Specify --dry-run or --apply (default would be ambiguous).")
    if args.dry_run and args.apply:
        p.error("--dry-run and --apply are mutually exclusive.")
    if not (args.tag or args.source or args.ids_file):
        p.error("Specify at least one of --tag, --source, --ids-file.")
    return args


def check_no_mcp_running() -> None:
    """Refuse to apply while the gaottt MCP server is running — the
    bidirectional cache overwrite trap would clobber our writes."""
    try:
        result = subprocess.run(
            ["pgrep", "-f", "gaottt.server.mcp_server"],
            capture_output=True, text=True, timeout=5,
        )
    except (subprocess.SubprocessError, FileNotFoundError):
        # pgrep missing or failed — emit a warning but don't block
        print("WARN: could not run pgrep to detect MCP server. Proceed at your own risk.")
        return
    pids = [p for p in result.stdout.strip().split("\n") if p.strip()]
    if pids:
        print(
            "ERROR: gaottt MCP server is running (PID(s): "
            + ", ".join(pids)
            + "). Stop it first to avoid the bidirectional cache overwrite trap "
              "(CLAUDE.md / Architecture-Concurrency.md)."
        )
        sys.exit(2)


def select_ids_from_metadata(
    db_path: str, tag: str | None, source: str | None,
) -> list[str]:
    """Query documents.metadata for substring matches. Returns ids of
    *active* (non-archived) nodes only."""
    import sqlite3

    db = sqlite3.connect(db_path)
    clauses: list[str] = ["n.is_archived = 0"]
    params: list = []
    if tag:
        clauses.append("d.metadata LIKE ?")
        params.append(f"%{tag}%")
    if source:
        clauses.append('d.metadata LIKE ?')
        params.append(f'%"source": "{source}"%')
    where = " AND ".join(clauses)
    cur = db.execute(
        f"SELECT d.id FROM documents d JOIN nodes n ON d.id = n.id WHERE {where}",
        params,
    )
    ids = [row[0] for row in cur.fetchall()]
    db.close()
    return ids


def load_ids_file(path: str) -> list[str]:
    with open(path) as fh:
        return [line.strip() for line in fh if line.strip() and not line.startswith("#")]


async def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    args = parse_args()

    if args.apply:
        check_no_mcp_running()

    # Build config (uses real production paths)
    config = GaOTTTConfig()
    config.supernova_initial_weight = args.weight
    config.supernova_velocity_alpha = args.velocity_alpha
    config.supernova_min_cohort_size = 2
    config.supernova_enabled = True

    print(f"DB:    {config.db_path}")
    print(f"FAISS: {config.faiss_index_path}")
    print(f"Mode:  {'APPLY' if args.apply else 'DRY-RUN'}")
    print()

    # 1. Resolve candidate ids
    if args.ids_file:
        ids = load_ids_file(args.ids_file)
        source_label = f"ids_file={args.ids_file}"
    else:
        ids = select_ids_from_metadata(config.db_path, args.tag, args.source)
        source_label = f"tag={args.tag!r} source={args.source!r}"
    print(f"Selector: {source_label}")
    print(f"Matched ids: {len(ids)}")

    if len(ids) < 2:
        print("Need at least 2 ids for a supernova cohort. Nothing to do.")
        return 1
    if len(ids) > args.max_cohort_size:
        print(
            f"Cohort size {len(ids)} exceeds --max-cohort-size {args.max_cohort_size}. "
            "Refusing to proceed. Increase the limit explicitly if intentional."
        )
        return 1

    # 2. Open store + load FAISS to get embeddings
    store = SqliteStore(db_path=config.db_path)
    await store.initialize()
    try:
        faiss = FaissIndex(dimension=config.embedding_dim)
        faiss.load(config.faiss_index_path)
        if faiss._index.ntotal == 0:
            print(f"FAISS index empty (or load failed): {config.faiss_index_path}")
            return 1
        emb_map = faiss.get_vectors(ids)
        valid_ids = [nid for nid in ids if nid in emb_map]
        missing = len(ids) - len(valid_ids)
        if missing:
            print(f"WARN: {missing} ids missing from FAISS index, skipping them.")
        if len(valid_ids) < 2:
            print("After FAISS filter, fewer than 2 valid ids. Nothing to do.")
            return 1
        embs = np.stack([emb_map[nid] for nid in valid_ids])

        # 3. Compute edges and outward velocities (reuse production code path)
        edges_pairs = form_supernova_edges(valid_ids, config)
        velocities = compute_supernova_velocities(valid_ids, embs, config)

        # 4. Preview
        print()
        print(f"Cohort size:       {len(valid_ids)}")
        print(f"Edges to write:    {len(edges_pairs)} unique pairs "
              f"({len(edges_pairs) * 2} record rows after both directions)")
        print(f"Velocities:        {len(velocities)}")
        print(f"Edge weight:       {args.weight}")
        print(f"Velocity α:        {args.velocity_alpha}, "
              f"clamp: {config.orbital_max_velocity}")

        sample_n = len(edges_pairs) if args.verbose else min(3, len(edges_pairs))
        print()
        print(f"Edges sample (first {sample_n}):")
        for src, dst, w in edges_pairs[:sample_n]:
            print(f"  {src[:8]} -- {dst[:8]}  w={w}")
        vel_sample = list(velocities.items())[: (len(velocities) if args.verbose else 3)]
        print()
        print(f"Velocity sample (first {len(vel_sample)} of {len(velocities)}):")
        for nid, v in vel_sample:
            print(f"  {nid[:8]}  |v|={float(np.linalg.norm(v)):.4f}")

        if not args.apply:
            print()
            print("[DRY RUN] No writes performed. Re-run with --apply to commit.")
            return 0

        # 5. Apply
        # 5a. Merge edges with existing (mimic cache.set_edge: bidirectional
        #     record + INSERT OR REPLACE behaviour).
        now = time.time()
        existing_edges = await store.get_all_edges()
        existing_weights: dict[tuple[str, str], float] = {
            (e.src, e.dst): e.weight for e in existing_edges
        }
        new_edge_objs: list[CooccurrenceEdge] = []
        for src, dst, w in edges_pairs:
            # Forward + reverse (the cache stores both directions; mimic that)
            for s, d in ((src, dst), (dst, src)):
                prev = existing_weights.get((s, d))
                new_weight = (prev + w) if prev is not None else w
                new_edge_objs.append(
                    CooccurrenceEdge(src=s, dst=d, weight=new_weight, last_update=now)
                )
        await store.save_edges(new_edge_objs)

        # 5b. Merge velocities (add to existing, clamp to orbital_max_velocity).
        existing_vel = await store.load_velocities(valid_ids)
        final_vel: dict[str, np.ndarray] = {}
        for nid, v_new in velocities.items():
            existing = existing_vel.get(nid)
            if existing is not None:
                v_combined = existing.astype(np.float32) + v_new.astype(np.float32)
            else:
                v_combined = v_new.astype(np.float32)
            norm = float(np.linalg.norm(v_combined))
            if norm > config.orbital_max_velocity:
                v_combined = v_combined * (config.orbital_max_velocity / norm)
            final_vel[nid] = v_combined.astype(np.float32)
        await store.save_velocities(final_vel)

        print()
        print(f"[APPLIED] {len(new_edge_objs)} edge records + "
              f"{len(final_vel)} velocities written.")
        print("Restart MCP server now so it reloads the cache from the store.")
        return 0

    finally:
        await store.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
