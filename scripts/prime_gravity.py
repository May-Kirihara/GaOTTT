#!/usr/bin/env python3
"""Phase G — Stage 0 priming: one-shot primordial gravity activation.

Walks every active node in the database and applies a single gravity-kick
step (the same physics genesis kick uses on fresh remember()) so that
documents indexed before Phase G existed pick up initial displacement,
velocity, and mass derived from the field they have always inhabited.

Why bother — without this, only nodes that have been recall()-ed have
ever felt the simulation step. On a 23k-node DB roughly 90% are still
mass=1.0 / displacement=0 / velocity=0.

What it does

    For each active node N:
      1. Find top-K heaviest FAISS neighbors (excluding N itself).
      2. compute_gravity_kick(N, neighbors) → (Δd, Δv, m_boost).
      3. cache.set_displacement(N, clamp(existing_d + Δd, max_norm)).
      4. cache.set_velocity(N, clamp(existing_v + Δv, max_v)).
      5. state.mass = max(state.mass, 1.0 + m_boost).
    Existing displacement / velocity are *added to*, not overwritten,
    so historical orbits are preserved. mass is monotonic via max().

How to run safely

    Bidirectional cache overwrite (Architecture-Concurrency.md): any other
    long-running gaottt process holding a stale cache will overwrite this
    script's writes during its own write-behind tick. Stop all MCP servers
    first:

        pkill -f gaottt.server.mcp_server
        # confirm with: ps -ef | grep gaottt
        cp -a $GAOTTT_DATA_DIR ${GAOTTT_DATA_DIR}.backup-$(date +%Y%m%d-%H%M%S)
        .venv/bin/python scripts/prime_gravity.py --apply
        # then restart MCP servers

Defaults: dry-run. Pass --apply to commit. Expect ~11 nodes/sec on
single-core CPU; a 23k-node DB takes ~35 min.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import time

import numpy as np

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))

from gaottt.config import GaOTTTConfig  # noqa: E402
from gaottt.core.gravity import clamp_vector, compute_gravity_kick  # noqa: E402
from gaottt.services.runtime import build_engine  # noqa: E402


def top_k_heavy_neighbors(engine, vec, k, pool_size, exclude_id):
    """Variant of engine._top_k_heavy_neighbors that excludes self_id.

    Pool from FAISS top-N by raw cosine, then rerank by cached mass.
    Skip self and any archived node.
    """
    pool = engine.faiss_index.search(vec.reshape(1, -1), pool_size)
    if not pool:
        return []
    candidates = []
    for nid, _cos in pool:
        if nid == exclude_id:
            continue
        state = engine.cache.get_node(nid)
        if state is None or state.is_archived:
            continue
        candidates.append((nid, state.mass))
    if not candidates:
        return []
    candidates.sort(key=lambda t: t[1], reverse=True)
    candidates = candidates[:k]
    ids_only = [nid for nid, _ in candidates]
    vec_map = engine.faiss_index.get_vectors(ids_only)
    out = []
    for nid, mass in candidates:
        v = vec_map.get(nid)
        if v is not None:
            out.append((v, mass))
    return out


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Apply primordial gravity activation across all active nodes.",
    )
    parser.add_argument("--apply", action="store_true",
                        help="Actually write through cache + persist (default: dry-run)")
    parser.add_argument("--limit", type=int, default=0,
                        help="Process only N nodes (0 = all). Useful for chunked runs.")
    parser.add_argument("--neighbor-k", type=int, default=None,
                        help="Heaviest K neighbors to kick from "
                             "(default: config.genesis_kick_neighbor_k)")
    parser.add_argument("--pool-size", type=int, default=None,
                        help="FAISS top-N pool size before mass rerank "
                             "(default: config.genesis_kick_pool_size)")
    args = parser.parse_args()

    config = GaOTTTConfig.from_config_file()
    # Disable side-effects irrelevant to the priming pass.
    config.dream_enabled = False
    config.faiss_save_interval_seconds = 0.0
    neighbor_k = args.neighbor_k or config.genesis_kick_neighbor_k
    pool_size = args.pool_size or config.genesis_kick_pool_size

    engine = build_engine(config)
    await engine.startup()
    print(
        f"engine startup: {len(engine.cache.node_cache)} nodes cached, "
        f"{engine.faiss_index.size} vectors\n"
    )
    print("=== Priming config ===")
    print(f"  neighbor_k    = {neighbor_k}")
    print(f"  pool_size     = {pool_size}")
    print(f"  mass_cap      = {config.genesis_mass_boost_cap}  "
          f"(applied inside compute_gravity_kick)")
    print(f"  apply         = {args.apply}")
    print()

    all_active = [
        s.id for s in engine.cache.get_all_nodes() if not s.is_archived
    ]
    if args.limit > 0:
        all_active = all_active[: args.limit]
    print(f"Active node candidates: {len(all_active)}")

    all_vecs = engine.faiss_index.get_vectors(all_active)
    skipped_no_vec = len(all_active) - len(all_vecs)
    print(
        f"Vectors resolved:        {len(all_vecs)} "
        f"(skipped {skipped_no_vec} that exist in cache but not FAISS)\n"
    )

    n_processed = 0
    n_kicked = 0
    n_no_neighbors = 0
    pre_existing_disp = 0
    pre_existing_mass_gt_1 = 0
    mass_boosts: list[float] = []
    new_disp_norms: list[float] = []
    pre_disp_norms: list[float] = []

    t0 = time.time()
    for i, nid in enumerate(all_active):
        new_vec = all_vecs.get(nid)
        if new_vec is None:
            continue
        n_processed += 1
        if (i + 1) % 2000 == 0:
            elapsed = time.time() - t0
            rate = (i + 1) / elapsed if elapsed > 0 else 0.0
            eta = (len(all_active) - i - 1) / rate if rate > 0 else 0.0
            print(
                f"  ... {i+1}/{len(all_active)} processed "
                f"({rate:.0f}/s, ETA {eta:.0f}s)",
                flush=True,
            )

        neighbors = top_k_heavy_neighbors(
            engine, new_vec, neighbor_k, pool_size, exclude_id=nid,
        )
        if not neighbors:
            n_no_neighbors += 1
            continue

        # compute_gravity_kick already applies genesis_mass_boost_cap
        # (gravity.py:compute_gravity_kick).
        disp_kick, vel_kick, m_boost = compute_gravity_kick(
            new_vec, neighbors, config,
        )

        existing_disp = engine.cache.get_displacement(nid)
        existing_vel = engine.cache.get_velocity(nid)
        existing_disp_norm = (
            float(np.linalg.norm(existing_disp))
            if existing_disp is not None else 0.0
        )
        if existing_disp_norm > 1e-9:
            pre_existing_disp += 1
            pre_disp_norms.append(existing_disp_norm)
        state = engine.cache.get_node(nid)
        if state is not None and state.mass > 1.0 + 1e-9:
            pre_existing_mass_gt_1 += 1

        if existing_disp is None:
            existing_disp = np.zeros_like(new_vec)
        if existing_vel is None:
            existing_vel = np.zeros_like(new_vec)

        new_disp = clamp_vector(
            existing_disp + disp_kick, config.max_displacement_norm,
        )
        new_vel = clamp_vector(
            existing_vel + vel_kick, config.orbital_max_velocity,
        )

        n_kicked += 1
        mass_boosts.append(m_boost)
        new_disp_norms.append(float(np.linalg.norm(new_disp)))

        if args.apply:
            engine.cache.set_displacement(nid, new_disp)
            engine.cache.set_velocity(nid, new_vel)
            if state is not None and m_boost > 0:
                state.mass = max(state.mass, 1.0 + m_boost)
                engine.cache.set_node(state, dirty=True)

    elapsed = time.time() - t0
    print(f"\n=== Summary ({'APPLY' if args.apply else 'DRY-RUN'}) ===")
    print(f"  processed:               {n_processed}")
    print(f"  kicked:                  {n_kicked}")
    print(f"  no qualifying neighbors: {n_no_neighbors}")
    print(f"  pre-existing mass > 1:   {pre_existing_mass_gt_1}")
    print(f"  pre-existing |disp| > 0: {pre_existing_disp}")
    print(f"  elapsed:                 {elapsed:.1f}s "
          f"({n_processed / max(elapsed, 1e-9):.0f}/s)")

    if mass_boosts:
        mb = np.array(mass_boosts)
        print(
            "  mass boost:              "
            f"min={mb.min():.4f} median={np.median(mb):.4f} "
            f"mean={mb.mean():.4f} max={mb.max():.4f}"
        )
    if new_disp_norms:
        dn = np.array(new_disp_norms)
        print(
            "  |displacement| (after):  "
            f"min={dn.min():.4f} median={np.median(dn):.4f} "
            f"mean={dn.mean():.4f} max={dn.max():.4f}"
        )
    if pre_disp_norms:
        pd = np.array(pre_disp_norms)
        print(
            "  |displacement| (before, non-zero only):  "
            f"min={pd.min():.4f} median={np.median(pd):.4f} "
            f"mean={pd.mean():.4f} max={pd.max():.4f}"
        )

    if args.apply:
        print("\n[apply] flushing cache to SQLite ...")
        await engine.cache.flush_to_store(engine.store)
        print("[apply] done")
    else:
        print("\n[dry-run] no writes. Pass --apply to commit.")

    await engine.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
