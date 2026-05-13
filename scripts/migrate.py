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
    scripts/migrate.py --apply               # apply (auto-backups data_dir first)
    scripts/migrate.py --apply --no-backup   # skip the automatic backup
    scripts/migrate.py --apply --step M001   # apply just one
    scripts/migrate.py --apply --force       # bypass running-server check

Safety rails:

* **Dry-run by default**. ``--apply`` is required to actually mutate state.
* **Auto-backup** — ``--apply`` automatically copies the entire data_dir to a
  timestamped sibling directory before any mutation. Pass ``--no-backup`` to
  skip (e.g. in CI where the dir is already under version control).
* **Server-running check** refuses to proceed if any GaOTTT server process is
  detected (MCP server OR REST server — both hold an in-memory cache whose
  write-back would overwrite migration changes; see Architecture-Overview.md
  "Bidirectional cache overwrite trap"). ``--force`` bypasses, but you should
  not need to in normal operation.
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

    ``critical=True`` flags a destructive / irreversible step (e.g., bulk
    state reset that loses accumulated history). The wizard pauses for an
    interactive confirmation before applying critical steps; safe steps
    are applied automatically. ``warning`` is the multi-line text shown
    in that confirmation prompt — concrete side effects, not philosophy.
    """

    version: str
    name: str
    description: str
    needs_apply: Callable[..., Awaitable[tuple[bool, str]]]
    apply: Callable[..., Awaitable[str]]
    verify: Callable[..., Awaitable[tuple[bool, str]]]
    critical: bool = False
    warning: str = ""


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
# M002 — Phase M Stage 1: legacy co-occurrence BH residue cleanup
# ---------------------------------------------------------------------
# The old ``compute_bh_acceleration`` term pulled each node toward the
# weighted centroid of its co-occurrence neighbors every recall step.
# That force lived in ``compute_acceleration`` 第 3 項 and was integrated
# into displacement / velocity through ``update_orbital_state``. Phase M
# replaced the term with a mass-threshold BH (dormant until ``mass >
# θ-2σ``), but the **runtime residue** — displacement and velocity that
# accumulated under the old pull — stays in the DB until something wipes
# it. M002 wipes it.

M002_RESIDUE_TRIGGER = 0.05      # mean(|d|) above this → residue is non-trivial
M002_VERIFY_THRESHOLD = 0.001    # mean(|d|) below this after apply → success


def _displacement_stats(engine) -> tuple[int, float, float]:
    """Return (active_count, mean_norm, max_norm) over active nodes' displacement."""
    total = 0
    sum_norm = 0.0
    max_norm = 0.0
    for state in engine.cache.get_all_nodes():
        if state.is_archived:
            continue
        total += 1
        disp = engine.cache.get_displacement(state.id)
        if disp is None:
            continue
        n = float(np.linalg.norm(disp))
        sum_norm += n
        if n > max_norm:
            max_norm = n
    mean_norm = sum_norm / total if total else 0.0
    return total, mean_norm, max_norm


async def _m002_needs_apply(engine, config):
    total, mean_norm, max_norm = _displacement_stats(engine)
    if total == 0:
        return False, "DB has no active nodes — nothing to clean"
    if mean_norm > M002_RESIDUE_TRIGGER:
        return True, (
            f"mean |displacement| = {mean_norm:.3f} across {total} nodes "
            f"(max {max_norm:.2f}) — legacy BH residue present"
        )
    return False, (
        f"mean |displacement| = {mean_norm:.3f} across {total} nodes "
        f"(max {max_norm:.2f}) — already below threshold {M002_RESIDUE_TRIGGER}"
    )


async def _m002_apply(engine, config):
    t0 = time.time()
    affected = await engine.reset_orbital_state()
    elapsed = time.time() - t0
    return (
        f"cleared displacement + velocity on {affected} node rows "
        f"({elapsed:.1f}s); virtual FAISS marked dirty for rebuild on next save"
    )


async def _m002_verify(engine, config):
    total, mean_norm, max_norm = _displacement_stats(engine)
    if mean_norm < M002_VERIFY_THRESHOLD:
        return True, (
            f"mean |displacement| = {mean_norm:.4f} (< {M002_VERIFY_THRESHOLD}); "
            f"residue cleaned"
        )
    return False, (
        f"mean |displacement| = {mean_norm:.4f} (≥ {M002_VERIFY_THRESHOLD}); "
        f"reset did not take effect"
    )


M002 = Migration(
    version="M002",
    name="phase-m-bh-residue-cleanup",
    description=(
        "Zero displacement + velocity on every active node, wiping the runtime "
        "residue of the legacy co-occurrence BH (which pulled nodes toward "
        "neighbor centroids before Phase M replaced it with the mass-threshold "
        "BH). Mass is left untouched — see M003 for that."
    ),
    critical=True,
    warning=(
        "DESTRUCTIVE — clears Phase G genesis kicks and Phase I/J query-attraction\n"
        "  displacement along with the legacy BH residue (the three are intertwined\n"
        "  in the same displacement vector and cannot be separated post-hoc).\n"
        "  Virtual FAISS will rebuild from raw embeddings on the next save tick.\n"
        "  Recommended once when rolling Phase M Stage 1 out on a DB that ran\n"
        "  under the old co-occurrence BH physics."
    ),
    needs_apply=_m002_needs_apply,
    apply=_m002_apply,
    verify=_m002_verify,
)


# ---------------------------------------------------------------------
# M003 — Phase M Stage 1: mass reset
# ---------------------------------------------------------------------
# Pre-Phase-M masses were inflated by chunk-internal co-occurrence (one
# file = 91 chunks pumped each other's mass via "internal trade"). Phase M
# Stage 1 stops that loop but does not retroactively deflate. M003 sets
# every node's mass back to 1.0 so accretion under the new rule starts
# from a clean baseline.

# Pre-Phase-M inflation peaks were observed at max=49, p99=26 (see Plans
# §2.1). Natural post-Phase-M growth caps far below those values, so 5.0 is
# a clean dividing line — anything above is pre-rollout state that calls
# for the reset, anything below is normal Phase M operation.
M003_INFLATED_TRIGGER = 5.0
M003_VERIFY_TOLERANCE = 1e-6


def _mass_stats(engine) -> tuple[int, float, float]:
    """Return (active_count, max_mass, mean_mass)."""
    total = 0
    sum_mass = 0.0
    max_mass = 0.0
    for state in engine.cache.get_all_nodes():
        if state.is_archived:
            continue
        total += 1
        sum_mass += state.mass
        if state.mass > max_mass:
            max_mass = state.mass
    mean = sum_mass / total if total else 0.0
    return total, max_mass, mean


async def _m003_needs_apply(engine, config):
    total, max_mass, mean = _mass_stats(engine)
    if total == 0:
        return False, "DB has no active nodes"
    if max_mass > M003_INFLATED_TRIGGER:
        return True, (
            f"max mass = {max_mass:.2f}, mean = {mean:.2f} across {total} nodes "
            f"— pre-Phase-M inflation still present"
        )
    return False, (
        f"max mass = {max_mass:.2f}, mean = {mean:.2f} across {total} nodes "
        f"— already at clean baseline (threshold {M003_INFLATED_TRIGGER})"
    )


async def _m003_apply(engine, config):
    t0 = time.time()
    affected = await engine.reset_masses(1.0)
    elapsed = time.time() - t0
    return f"reset mass to 1.0 on {affected} node rows ({elapsed:.1f}s)"


async def _m003_verify(engine, config):
    total, max_mass, mean = _mass_stats(engine)
    if abs(max_mass - 1.0) < M003_VERIFY_TOLERANCE and abs(mean - 1.0) < M003_VERIFY_TOLERANCE:
        return True, f"max mass = {max_mass:.4f}, mean = {mean:.4f} (≈ 1.0)"
    return False, (
        f"max mass = {max_mass:.4f}, mean = {mean:.4f} — reset did not take"
    )


M003 = Migration(
    version="M003",
    name="phase-m-mass-reset",
    description=(
        "Reset every active node's mass to 1.0, wiping the chunk-internal "
        "co-occurrence inflation accumulated under pre-Phase-M physics "
        "(observed: 1 file = ~91 chunks pumping each other's mass via "
        "'internal trade'). Phase M Stage 1 stops the inflation loop but "
        "does not retroactively deflate — that's what this step does."
    ),
    critical=True,
    warning=(
        "DESTRUCTIVE — Phase L acceptance baseline (Surface 7/7 / strict 6/7)\n"
        "  was achieved with the inflated mass distribution. Immediately after\n"
        "  reset the retrieval geometry regresses transiently while new mass\n"
        "  re-accumulates under the 'external pull only' rule. Plan §6.2\n"
        "  predicts 1-2 weeks of natural recall before the new mass gradient\n"
        "  is observable. Mass distribution becomes uniform mass=1.0; for\n"
        "  retrieval scoring this means mass_boost = α·log(2) for everyone\n"
        "  (no differentiation) until the new gradient forms."
    ),
    needs_apply=_m003_needs_apply,
    apply=_m003_apply,
    verify=_m003_verify,
)


# ---------------------------------------------------------------------
# Registry (add new migrations here, in order)
# ---------------------------------------------------------------------

MIGRATIONS: list[Migration] = [
    M001,
    M002,
    M003,
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

def _running_gaottt_pids() -> list[tuple[int, str]]:
    """Return (pid, label) pairs for live GaOTTT server processes.

    Both MCP server and REST server hold an in-memory cache.  Either can
    flush stale cache entries back to SQLite after migration, undoing the
    migration's changes (bidirectional cache overwrite trap).
    """
    patterns = [
        ("gaottt.server.mcp_server", "MCP server"),
        ("gaottt.server.app",        "REST server"),
    ]
    found: list[tuple[int, str]] = []
    for pattern, label in patterns:
        try:
            out = subprocess.check_output(
                ["pgrep", "-f", pattern],
                stderr=subprocess.DEVNULL,
            )
        except (subprocess.CalledProcessError, FileNotFoundError):
            continue
        for line in out.decode().splitlines():
            line = line.strip()
            if line.isdigit():
                found.append((int(line), label))
    return found


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
    Critical migrations are marked with ``!`` so the user knows the
    wizard will pause for confirmation on them.
    """
    print(f"GaOTTT migration plan for {db_path}")
    print("=" * 78)
    print(f"{'VER':5}  {'NAME':30}  STATUS    DETAIL")
    print("-" * 78)
    for m in MIGRATIONS:
        name_label = f"{m.name}{' !' if m.critical else ''}"
        if m.version in applied:
            ts, notes = applied[m.version]
            ts_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))
            print(f"{m.version:5}  {name_label:30}  APPLIED   {ts_str}")
            if notes:
                print(f"{'':5}  {'':30}            {notes}")
        else:
            needed, reason = next(
                ((nd, rs) for mm, nd, rs in pending_detected if mm.version == m.version),
                (None, ""),
            )
            if needed is True:
                tag = "PENDING!" if m.critical else "PENDING "
                print(f"{m.version:5}  {name_label:30}  {tag}  {reason}")
            elif needed is False:
                print(f"{m.version:5}  {name_label:30}  SKIP      {reason}")
            else:
                print(f"{m.version:5}  {name_label:30}  UNKNOWN   (detection failed)")
    print("=" * 78)
    if any(m.critical for m in MIGRATIONS):
        print("  `!` marks CRITICAL / destructive migrations — wizard pauses for")
        print("      confirmation on these unless `--yes` is passed.\n")


# =====================================================================
# Wizard helpers
# =====================================================================

def _confirm_critical(m: Migration) -> bool:
    """Prompt the user about a critical migration. Returns True to apply.

    When stdin is not a TTY (CI / piped input), refuse and tell the user
    to pass ``--yes`` explicitly — silently auto-applying a destructive
    step in a non-interactive context is the worst-case behaviour.
    """
    if not sys.stdin.isatty():
        print(
            f"  [{m.version}] CRITICAL step but stdin is not a TTY. "
            "Pass --yes to apply without prompting, --skip-critical to skip.",
            file=sys.stderr,
        )
        return False

    print()
    print(f"  ⚠️  [{m.version}] {m.name}  (CRITICAL / DESTRUCTIVE)")
    print()
    # Indent the warning block by 6 spaces for visual separation.
    if m.warning:
        for line in m.warning.splitlines():
            print(f"      {line}")
        print()
    print(f"      Description: {m.description}")
    print()
    while True:
        try:
            answer = input(f"  Apply [{m.version}]? [y/N]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return False
        if answer in ("", "n", "no"):
            return False
        if answer in ("y", "yes"):
            return True
        print("  Please answer 'y' or 'n'.")


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

    # Pre-flight: server-running check (only when we'll actually mutate state)
    if args.apply:
        procs = _running_gaottt_pids()
        if procs and not args.force:
            desc = ", ".join(f"pid={pid} ({label})" for pid, label in procs)
            print(
                f"ERROR: detected running GaOTTT server processes: {desc}.\n"
                "  Stop them first (in-memory cache write-back would overwrite migration changes):\n"
                "    pkill -f gaottt.server.mcp_server\n"
                "    pkill -f gaottt.server.app\n"
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

            # --apply path — backup unless explicitly skipped
            if not args.no_backup:
                print("=== Backup ===")
                _backup_data_dir(data_dir)
            else:
                print("[backup skipped — --no-backup passed]\n")

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
            skipped_critical = 0
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
                # Wizard: critical migrations require confirmation unless
                # the user passed --yes (auto-accept) or --skip-critical
                # (auto-decline). Non-critical migrations are applied
                # automatically — that's the whole point of the wizard.
                if m.critical:
                    if args.skip_critical:
                        print(
                            f"[{m.version}] {m.name}: SKIP — critical, "
                            f"--skip-critical passed ({reason})"
                        )
                        skipped_critical += 1
                        continue
                    if not args.yes:
                        print(f"[{m.version}] {m.name}: PENDING — {reason}")
                        if not _confirm_critical(m):
                            print(f"[{m.version}] declined by user — skipping")
                            skipped_critical += 1
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
            print(
                f"  applied: {applied_now}   failed: {failed}   "
                f"skipped (critical): {skipped_critical}"
            )
            if applied_now > 0:
                print("\nNext steps:")
                print("  1. Restart MCP server so new physics takes effect.")
                print("  2. Optional smoke check:")
                print("       .venv/bin/python scripts/mcp_smoke.py")
            if skipped_critical > 0:
                print(
                    "\nNote: some critical migrations were skipped. Re-run with\n"
                    "       scripts/migrate.py --apply\n"
                    "       (and answer 'y' at the prompt) or with --yes\n"
                    "       to apply them later. They stay PENDING until applied."
                )
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
        "--no-backup", action="store_true",
        help="Skip the automatic data_dir backup that normally runs before "
             "--apply. Use only in CI environments where the directory is "
             "already under version control or backed up externally.",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Bypass the running-server check. Don't use unless you know "
             "neither MCP server nor REST server can flush stale cache to "
             "this DB (see Architecture-Overview.md).",
    )
    parser.add_argument(
        "--yes", "-y", action="store_true",
        help="Accept critical/destructive migrations without an interactive "
             "prompt. Required when stdin is not a TTY (CI / piped). Use "
             "carefully — equivalent to answering 'y' to every confirmation.",
    )
    parser.add_argument(
        "--skip-critical", action="store_true",
        help="Skip critical/destructive migrations even if they are pending. "
             "Non-critical migrations are still applied. Useful for staged "
             "rollouts where you want to land the safe steps now and revisit "
             "destructive ones manually.",
    )
    args = parser.parse_args()
    if args.yes and args.skip_critical:
        parser.error("--yes and --skip-critical are mutually exclusive")
    try:
        rc = asyncio.run(main_async(args))
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        rc = 130
    sys.exit(rc)


if __name__ == "__main__":
    main()
