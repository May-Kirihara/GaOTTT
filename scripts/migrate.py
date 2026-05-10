#!/usr/bin/env python3
"""GaOTTT user-facing migration tool.

Orchestrates one-time data migrations needed when upgrading across breaking
gravity-physics changes. Each migration is registered as a versioned step
(M001, M002, ...) with idempotent detect / apply / verify functions. Applied
versions are recorded in the ``_migrations`` SQLite table inside gaottt.db
so re-runs are safe — already-applied steps are skipped.

Usage::

    scripts/migrate.py                       # dry-run, show plan
    scripts/migrate.py --list                # list all known migrations + status
    scripts/migrate.py --apply               # apply all pending migrations
    scripts/migrate.py --apply --step M001   # apply just one
    scripts/migrate.py --apply --backup      # auto-backup data_dir first
    scripts/migrate.py --apply --force       # bypass MCP-running check

Safety rails:

* **Dry-run by default**. ``--apply`` is required to actually mutate state.
* **MCP-running check** refuses to proceed if a ``gaottt.server.mcp_server``
  process is detected (cache write-back would overwrite our changes — see
  Architecture-Concurrency.md "Bidirectional cache overwrite"). ``--force``
  bypasses, but you should not need to.
* **Backup** (``--backup``) copies the entire data_dir to a sibling directory
  with a timestamp suffix before any mutation.
* **Idempotent**. Running ``--apply`` twice does nothing the second time;
  each migration's ``needs_apply`` is a strong detector independent of the
  ``_migrations`` ledger, so even a wiped ledger does the right thing.

Adding a new migration:

1. Implement a Migration subclass in this module with a unique ``version``
   ("M002", "M003", ...) and ``async`` ``needs_apply`` / ``apply`` / ``verify``.
2. Append it to ``MIGRATIONS`` in order.
3. Add a row in ``docs/wiki/Operations-Migration.md``.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import shutil
import sqlite3
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable

import numpy as np

# Ensure parent dir is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gaottt.config import GaOTTTConfig  # noqa: E402
from gaottt.core.gravity import clamp_vector, compute_gravity_kick  # noqa: E402
from gaottt.services.runtime import build_engine  # noqa: E402

logger = logging.getLogger("gaottt.migrate")


# =====================================================================
# Migration framework
# =====================================================================

@dataclass
class MigrationResult:
    applied: bool
    notes: str
    duration_seconds: float = 0.0


@dataclass
class Migration:
    """A single versioned migration step.

    needs_apply / apply / verify are async callables taking (engine, config).
    needs_apply returns (bool, reason_str). apply returns notes_str. verify
    returns (ok, reason_str).
    """

    version: str
    name: str
    description: str
    needs_apply: Callable[..., Awaitable[tuple[bool, str]]]
    apply: Callable[..., Awaitable[str]]
    verify: Callable[..., Awaitable[tuple[bool, str]]]


# ---------------------------------------------------------------------
# M001 — Phase G Stage 0 priming
# ---------------------------------------------------------------------

ZERO_DISP_TOLERANCE = 1e-6
M001_TRIGGER_FRACTION = 0.5  # if > 50% of active nodes have |d| < tol → apply


def _zero_displacement_stats(engine) -> tuple[int, int]:
    """Return (total_active, zero_displacement_count)."""
    total = 0
    zero = 0
    for state in engine.cache.get_all_nodes():
        if state.is_archived:
            continue
        total += 1
        disp = engine.cache.get_displacement(state.id)
        if disp is None or float(np.linalg.norm(disp)) < ZERO_DISP_TOLERANCE:
            zero += 1
    return total, zero


def _top_k_heavy_neighbors(engine, vec, k, pool_size, exclude_id):
    """Pool FAISS top-N by raw cosine, then rerank by cached mass.
    Skip self and any archived node. Same logic as prime_gravity.py."""
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


async def _m001_needs_apply(engine, config):
    total, zero = _zero_displacement_stats(engine)
    if total == 0:
        return False, "DB has no active nodes — nothing to prime"
    frac = zero / total
    msg = f"{zero}/{total} ({frac:.0%}) active nodes have |displacement| < {ZERO_DISP_TOLERANCE}"
    if frac > M001_TRIGGER_FRACTION:
        return True, msg
    return False, msg + " — already primed"


async def _m001_apply(engine, config):
    """Apply a one-step gravity-kick to every active node.

    Existing displacement / velocity are *added to*, not overwritten, so any
    history accumulated by recall() is preserved. Mass is monotonic via
    max(state.mass, 1.0 + m_boost).
    """
    neighbor_k = config.genesis_kick_neighbor_k
    pool_size = config.genesis_kick_pool_size

    all_active = [s.id for s in engine.cache.get_all_nodes() if not s.is_archived]
    all_vecs = engine.faiss_index.get_vectors(all_active)

    n_kicked = 0
    n_no_neighbors = 0
    t0 = time.time()
    last_report = t0

    for i, nid in enumerate(all_active):
        new_vec = all_vecs.get(nid)
        if new_vec is None:
            continue
        now = time.time()
        if now - last_report > 5.0:
            rate = (i + 1) / max(now - t0, 1e-9)
            eta = (len(all_active) - i - 1) / max(rate, 1e-9)
            print(
                f"    ... {i + 1}/{len(all_active)} processed "
                f"({rate:.0f}/s, ETA {eta:.0f}s)",
                flush=True,
            )
            last_report = now

        neighbors = _top_k_heavy_neighbors(
            engine, new_vec, neighbor_k, pool_size, exclude_id=nid,
        )
        if not neighbors:
            n_no_neighbors += 1
            continue

        disp_kick, vel_kick, m_boost = compute_gravity_kick(new_vec, neighbors, config)

        existing_disp = engine.cache.get_displacement(nid)
        existing_vel = engine.cache.get_velocity(nid)
        if existing_disp is None:
            existing_disp = np.zeros_like(new_vec)
        if existing_vel is None:
            existing_vel = np.zeros_like(new_vec)

        new_disp = clamp_vector(existing_disp + disp_kick, config.max_displacement_norm)
        new_vel = clamp_vector(existing_vel + vel_kick, config.orbital_max_velocity)

        engine.cache.set_displacement(nid, new_disp)
        engine.cache.set_velocity(nid, new_vel)

        state = engine.cache.get_node(nid)
        if state is not None and m_boost > 0:
            state.mass = max(state.mass, 1.0 + m_boost)
            engine.cache.set_node(state, dirty=True)

        n_kicked += 1

    await engine.cache.flush_to_store(engine.store)
    elapsed = time.time() - t0
    return (
        f"primed {n_kicked}/{len(all_active)} nodes "
        f"(skipped {n_no_neighbors} with no qualifying neighbors), "
        f"{elapsed:.1f}s"
    )


async def _m001_verify(engine, config):
    total, zero = _zero_displacement_stats(engine)
    frac = zero / total if total else 0.0
    if frac <= M001_TRIGGER_FRACTION:
        return True, f"zero-displacement now {zero}/{total} ({frac:.0%}) — below trigger threshold {M001_TRIGGER_FRACTION:.0%}"
    return False, f"zero-displacement still {zero}/{total} ({frac:.0%}) — above trigger; priming did not take"


M001 = Migration(
    version="M001",
    name="phase-g-priming",
    description=(
        "Apply Phase G genesis-kick physics to every active node so documents "
        "indexed before Phase G existed pick up initial displacement, velocity, "
        "and mass. Without this ~90% of legacy nodes stay at mass=1/d=0/v=0 "
        "and lose recall ranking to anything Phase G touched. Idempotent — "
        "re-running skips nodes that already have displacement."
    ),
    needs_apply=_m001_needs_apply,
    apply=_m001_apply,
    verify=_m001_verify,
)


# ---------------------------------------------------------------------
# Registry (add new migrations here, in order)
# ---------------------------------------------------------------------

MIGRATIONS: list[Migration] = [
    M001,
]


# =====================================================================
# _migrations ledger
# =====================================================================

LEDGER_SCHEMA = """
CREATE TABLE IF NOT EXISTS _migrations (
    version    TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    applied_at REAL NOT NULL,
    notes      TEXT
)
"""


def _open_ledger(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute(LEDGER_SCHEMA)
    conn.commit()
    return conn


def _ledger_applied(conn: sqlite3.Connection) -> dict[str, tuple[float, str]]:
    """Return {version: (applied_at, notes)} for all recorded migrations."""
    out: dict[str, tuple[float, str]] = {}
    for row in conn.execute("SELECT version, applied_at, notes FROM _migrations"):
        out[row[0]] = (row[1], row[2] or "")
    return out


def _ledger_record(conn: sqlite3.Connection, m: Migration, notes: str) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO _migrations (version, name, applied_at, notes) "
        "VALUES (?, ?, ?, ?)",
        (m.version, m.name, time.time(), notes),
    )
    conn.commit()


# =====================================================================
# Safety helpers
# =====================================================================

def _running_mcp_pids() -> list[int]:
    """pgrep-style check for live gaottt.server.mcp_server processes."""
    try:
        out = subprocess.check_output(
            ["pgrep", "-f", "gaottt.server.mcp_server"],
            stderr=subprocess.DEVNULL,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []
    pids = []
    for line in out.decode().splitlines():
        line = line.strip()
        if line.isdigit():
            pids.append(int(line))
    return pids


def _backup_data_dir(data_dir: Path) -> Path:
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    dst = data_dir.with_name(f"{data_dir.name}.backup-{timestamp}")
    if dst.exists():
        raise FileExistsError(f"Backup destination already exists: {dst}")
    print(f"  Copying {data_dir} → {dst} ...", flush=True)
    shutil.copytree(data_dir, dst)
    print(f"  Backup OK at {dst}\n")
    return dst


# =====================================================================
# Plan rendering
# =====================================================================

def _render_plan(
    db_path: str,
    applied: dict[str, tuple[float, str]],
    pending_detected: list[tuple[Migration, bool, str]],
) -> None:
    """Print a human-readable status table.

    pending_detected: list of (migration, needs_apply, reason).
    """
    print(f"GaOTTT migration plan for {db_path}")
    print("=" * 78)
    print(f"{'VER':5}  {'NAME':24}  STATUS    DETAIL")
    print("-" * 78)
    for m in MIGRATIONS:
        if m.version in applied:
            ts, notes = applied[m.version]
            ts_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))
            print(f"{m.version:5}  {m.name:24}  APPLIED   {ts_str}")
            if notes:
                print(f"{'':5}  {'':24}            {notes}")
        else:
            needed, reason = next(
                ((nd, rs) for mm, nd, rs in pending_detected if mm.version == m.version),
                (None, ""),
            )
            if needed is True:
                print(f"{m.version:5}  {m.name:24}  PENDING   {reason}")
            elif needed is False:
                print(f"{m.version:5}  {m.name:24}  SKIP      {reason}")
            else:
                print(f"{m.version:5}  {m.name:24}  UNKNOWN   (detection failed)")
    print("=" * 78)


# =====================================================================
# Main
# =====================================================================

async def main_async(args: argparse.Namespace) -> int:
    config = GaOTTTConfig.from_config_file()
    db_path = config.db_path
    data_dir = Path(config.data_dir).resolve()

    if not Path(db_path).exists():
        print(
            f"ERROR: no GaOTTT database at {db_path}.\n"
            "  - If this is a fresh install, just start the MCP server and remember() something first.\n"
            "  - If you have a GER-RAG legacy DB, run scripts/migrate-from-ger-rag.sh first.",
            file=sys.stderr,
        )
        return 2

    # Pre-flight: MCP-running check (only when we'll actually mutate state)
    if args.apply:
        pids = _running_mcp_pids()
        if pids and not args.force:
            print(
                f"ERROR: detected gaottt.server.mcp_server processes: {pids}.\n"
                "  Stop them first (cache write-back would overwrite this script's changes):\n"
                "    pkill -f gaottt.server.mcp_server\n"
                "  Then re-run. Pass --force to bypass at your own risk.",
                file=sys.stderr,
            )
            return 3

    # Disable startup side-effects irrelevant to migration
    config.dream_enabled = False
    config.faiss_save_interval_seconds = 0.0

    engine = build_engine(config)
    await engine.startup()
    try:
        ledger = _open_ledger(db_path)
        try:
            applied = _ledger_applied(ledger)

            # Compute pending detection for everything not in ledger
            pending_detected: list[tuple[Migration, bool, str]] = []
            for m in MIGRATIONS:
                if m.version in applied:
                    continue
                if args.step and args.step != m.version:
                    continue
                try:
                    needed, reason = await m.needs_apply(engine, config)
                except Exception as exc:
                    logger.exception("needs_apply failed for %s", m.version)
                    needed, reason = None, f"detect error: {exc}"
                pending_detected.append((m, needed, reason))

            if args.list:
                _render_plan(db_path, applied, pending_detected)
                return 0

            if not args.apply:
                _render_plan(db_path, applied, pending_detected)
                pending_count = sum(1 for _, n, _ in pending_detected if n)
                if pending_count:
                    print(
                        f"\n[dry-run] {pending_count} migration(s) would be applied. "
                        "Re-run with --apply to commit."
                    )
                else:
                    print("\n[dry-run] no migrations to apply.")
                return 0

            # --apply path
            if args.backup:
                print("=== Backup ===")
                _backup_data_dir(data_dir)

            print(f"=== Apply ({time.strftime('%Y-%m-%d %H:%M:%S')}) ===\n")
            already_applied = [m.version for m in MIGRATIONS if m.version in applied]
            if already_applied:
                for v in already_applied:
                    ts, notes = applied[v]
                    ts_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))
                    print(f"[{v}] already APPLIED at {ts_str} — {notes}")
                print()

            applied_now = 0
            failed = 0
            for m, needed, reason in pending_detected:
                if args.step and args.step != m.version:
                    continue
                if needed is False:
                    print(f"[{m.version}] {m.name}: SKIP — {reason}")
                    continue
                if needed is None:
                    print(f"[{m.version}] {m.name}: SKIP — detect error: {reason}")
                    failed += 1
                    continue
                print(f"[{m.version}] {m.name}: APPLYING — {reason}")
                t0 = time.time()
                try:
                    apply_notes = await m.apply(engine, config)
                except Exception as exc:  # noqa: BLE001
                    logger.exception("apply failed for %s", m.version)
                    print(f"[{m.version}] FAILED: {exc}")
                    failed += 1
                    continue
                t_apply = time.time() - t0
                try:
                    ok, verify_msg = await m.verify(engine, config)
                except Exception as exc:  # noqa: BLE001
                    ok = False
                    verify_msg = f"verify error: {exc}"
                if ok:
                    print(f"[{m.version}] OK in {t_apply:.1f}s — {apply_notes}")
                    print(f"[{m.version}] VERIFY: {verify_msg}")
                    _ledger_record(ledger, m, apply_notes)
                    applied_now += 1
                else:
                    print(f"[{m.version}] VERIFY FAILED — {verify_msg}")
                    print(f"[{m.version}] ledger NOT updated; investigate manually.")
                    failed += 1

            print("\n=== Result ===")
            print(f"  applied: {applied_now}   failed: {failed}")
            if applied_now > 0:
                print("\nNext steps:")
                print("  1. Restart MCP server so new physics takes effect.")
                print("  2. Optional smoke check:")
                print("       .venv/bin/python scripts/mcp_smoke.py")
            return 1 if failed > 0 else 0
        finally:
            ledger.close()
    finally:
        await engine.shutdown()


def main() -> None:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(
        prog="migrate.py",
        description=(
            "GaOTTT data migration tool. Detects and applies one-time data "
            "migrations needed for upgrading across breaking gravity-physics "
            "changes. Dry-run by default; pass --apply to commit."
        ),
    )
    parser.add_argument(
        "--apply", action="store_true",
        help="Actually apply pending migrations. Without this, the script "
             "runs as dry-run and only prints what it would do.",
    )
    parser.add_argument(
        "--list", action="store_true",
        help="List all known migrations + their status and exit (implies dry-run).",
    )
    parser.add_argument(
        "--step", metavar="VERSION",
        help="Apply only this specific migration (e.g. M001).",
    )
    parser.add_argument(
        "--backup", action="store_true",
        help="Before applying, copy the entire data_dir to "
             "<data_dir>.backup-<timestamp>/. Recommended for production DBs.",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Bypass the running-MCP-process check. Don't use unless you "
             "know cache overwrite cannot affect this DB (Architecture-"
             "Concurrency.md).",
    )
    args = parser.parse_args()
    try:
        rc = asyncio.run(main_async(args))
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        rc = 130
    sys.exit(rc)


if __name__ == "__main__":
    main()
