#!/usr/bin/env python3
"""Rebuild the FAISS index from SQLite document content (disaster recovery).

Use this when FAISS has desynced from the DB — e.g. the on-disk index holds
only a handful of vectors while ``documents`` has tens of thousands of rows.
This happens when a process with a near-empty in-memory FAISS keeps running the
write-behind save loop and overwrites the good on-disk index with its empty one
(the "reverse overwrite trap" documented in CLAUDE.md).

What it does
------------
1. Builds an engine against the configured data dir and runs ``startup()``,
   which loads ALL node states + displacements + velocities from SQLite into
   cache (no cap), then loads whatever is left in the (corrupt) FAISS.
2. Runs ``compact(rebuild_faiss=True)``. ``_rebuild_faiss_index`` keeps the
   vectors already present in FAISS and re-embeds every active node that is
   missing — re-encoding its ``documents.content`` with RURI. RURI is
   deterministic, so the recovered raw vectors are bit-for-bit what they were.
   Mass / displacement / velocity / temperature live in SQLite cache state and
   are untouched — only the vector index is rebuilt.
3. ``shutdown()`` persists the rebuilt raw + virtual FAISS to disk.

CRITICAL — run this with NO other gaottt process alive
------------------------------------------------------
If any MCP/REST/proxy-backend process is running, its stale in-memory FAISS will
overwrite the index you just rebuilt within ``faiss_save_interval_seconds``.
Kill every ``gaottt.server.mcp_server`` process first (see the steps printed by
``--check``), then run this, then let the next agent activity respawn a fresh
backend that loads the good index.

Usage
-----
    .venv/bin/python scripts/rebuild_faiss_from_db.py --check    # read-only diagnosis
    .venv/bin/python scripts/rebuild_faiss_from_db.py --apply    # do the rebuild
"""
from __future__ import annotations

import argparse
import asyncio
import sqlite3
import sys

from gaottt.config import GaOTTTConfig
from gaottt.index.faiss_index import FaissIndex
from gaottt.services.runtime import build_engine


def _on_disk_counts(config: GaOTTTConfig) -> tuple[int, int, int]:
    raw = FaissIndex(dimension=config.embedding_dim)
    raw.load(config.faiss_index_path)
    raw_n = raw.size
    try:
        v = FaissIndex(dimension=config.embedding_dim)
        v.load(config.virtual_faiss_index_path)
        virt_n = v.size
    except Exception:
        virt_n = -1
    con = sqlite3.connect(f"file:{config.db_path}?mode=ro", uri=True)
    try:
        docs = con.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    finally:
        con.close()
    return raw_n, virt_n, docs


def _check(config: GaOTTTConfig) -> None:
    raw_n, virt_n, docs = _on_disk_counts(config)
    print("Data dir (from config):")
    print(f"  db     : {config.db_path}")
    print(f"  faiss  : {config.faiss_index_path}")
    print(f"  virtual: {config.virtual_faiss_index_path}")
    print()
    print(f"  SQLite documents      : {docs:,}")
    print(f"  raw FAISS vectors     : {raw_n:,}")
    print(f"  virtual FAISS vectors : {virt_n:,}")
    gap = docs - raw_n
    if gap > 1000:
        print()
        print(f"  DESYNC: FAISS is missing ~{gap:,} vectors that exist in the DB.")
        print("  Recover with --apply AFTER killing all gaottt processes:")
        print("    ps -ef | grep 'gaottt.server.mcp_server' | grep -v grep")
        print("    kill <each pid>   # incl. the streamable-http backend on :7878")
    else:
        print()
        print("  FAISS and DB are roughly in sync; no rebuild needed.")


async def _apply(config: GaOTTTConfig) -> int:
    raw_n, virt_n, docs = _on_disk_counts(config)
    print(f"Before: raw FAISS={raw_n:,}  virtual={virt_n:,}  DB documents={docs:,}")
    if raw_n >= docs:
        print("Nothing to do — FAISS already holds at least as many vectors as the DB.")
        return 0

    print("Building engine + startup (loads all node states into cache)...")
    engine = build_engine(config)
    await engine.startup()
    print(f"  cache nodes loaded: {len(engine.cache.node_cache):,}")
    print(f"  FAISS at startup  : {engine.faiss_index.size:,}")

    print("Re-embedding missing nodes from documents.content (this can take a while)...")
    report = await engine.compact(
        expire_ttl=False,      # do not touch TTL during a recovery
        rebuild_faiss=True,    # the whole point
        auto_merge=False,      # never silently collapse nodes during recovery
    )
    print(f"  compact report: {report}")
    print(f"  FAISS after rebuild: {engine.faiss_index.size:,}")

    print("Shutting down (persists rebuilt raw + virtual FAISS to disk)...")
    await engine.shutdown()

    raw_n2, virt_n2, _docs = _on_disk_counts(config)
    print(f"After:  raw FAISS={raw_n2:,}  virtual={virt_n2:,} on disk")
    if raw_n2 < docs - 1000:
        print("  WARNING: still well below the document count — inspect logs above.")
        return 1
    print("  Rebuild persisted. Verify with scripts/verify_faiss_recovery.py")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    g = parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--check", action="store_true", help="Read-only desync diagnosis")
    g.add_argument("--apply", action="store_true", help="Rebuild FAISS from the DB")
    args = parser.parse_args()

    config = GaOTTTConfig.from_config_file()
    if args.check:
        _check(config)
        return 0
    return asyncio.run(_apply(config))


if __name__ == "__main__":
    sys.exit(main())
