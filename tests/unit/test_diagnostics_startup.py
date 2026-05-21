"""Unit tests for gaottt/diagnostics/startup.py.

Stage 1 (commitment id=aaa6e7cc). Each scenario isolates one Tier A/B
behaviour with a fresh engine + tmp_path data dir.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from gaottt.diagnostics.startup import (
    DiagnosticLevel,
    DiagnosticReport,
    _cleanup_tmp_residuals,
    _drift_fraction,
    run_startup_checks,
)
from tests.perf._helpers import make_engine


def test_drift_fraction_zero_expected_zero_observed():
    assert _drift_fraction(0, 0) == 0.0


def test_drift_fraction_zero_expected_positive_observed():
    # When SQLite says 0 but FAISS has entries, full drift.
    assert _drift_fraction(5, 0) == 1.0


def test_drift_fraction_normal():
    assert _drift_fraction(95, 100) == 0.05
    assert _drift_fraction(105, 100) == 0.05
    assert _drift_fraction(80, 100) == 0.20


def _dead_pid() -> int:
    """A pid that has certainly exited (reuse within the test window is
    negligible) — for asserting dead-owner cleanup."""
    import subprocess

    p = subprocess.Popen(["true"])
    p.wait()
    return p.pid


def test_cleanup_tmp_residuals_removes_dead_pid_orphans(tmp_path):
    """Tier A / H3 — a pid-scoped .tmp whose owning process is dead is an
    orphan from an interrupted atomic save and is deleted."""
    dead = _dead_pid()
    (tmp_path / f"gaottt.faiss.{dead}.tmp").write_bytes(b"partial")
    (tmp_path / f"gaottt.faiss.ids.{dead}.tmp").write_bytes(b"partial2")
    (tmp_path / "keep_me.txt").write_text("not a tmp")

    report = DiagnosticReport()
    _cleanup_tmp_residuals(tmp_path, report)

    assert not (tmp_path / f"gaottt.faiss.{dead}.tmp").exists()
    assert not (tmp_path / f"gaottt.faiss.ids.{dead}.tmp").exists()
    assert (tmp_path / "keep_me.txt").exists()
    cleaned = [r for r in report.results if "tmp_residual_cleaned" in r.name]
    assert len(cleaned) == 2


def test_cleanup_tmp_residuals_keeps_live_writer_scratch(tmp_path):
    """H3 regression — a pid-scoped .tmp owned by a LIVE process must NOT
    be deleted: that is a sibling backend mid-write, and unlinking it
    turns its os.replace into FileNotFoundError (lost index snapshot)."""
    import os

    live = os.getpid()  # this test process is, definitionally, alive
    scratch = tmp_path / f"gaottt.virtual.faiss.{live}.tmp"
    scratch.write_bytes(b"in-flight 100MB write...")

    report = DiagnosticReport()
    _cleanup_tmp_residuals(tmp_path, report)

    assert scratch.exists(), "live-process scratch file was wrongly deleted (H3 regression)"
    assert any("tmp_residual_skipped_live" in r.name for r in report.results)


def test_cleanup_tmp_residuals_unscoped_recent_kept_old_deleted(tmp_path):
    """Legacy unscoped <path>.tmp (pre-H3): recent ones may be a pre-H3
    writer mid-save → keep; clearly old ones are orphans → delete."""
    import os
    import time

    from gaottt.diagnostics.startup import _STALE_TMP_AGE_SECONDS

    recent = tmp_path / "gaottt.faiss.tmp"
    recent.write_bytes(b"maybe in-flight")
    old = tmp_path / "gaottt.virtual.faiss.tmp"
    old.write_bytes(b"definitely orphan")
    old_mtime = time.time() - (_STALE_TMP_AGE_SECONDS + 60)
    os.utime(old, (old_mtime, old_mtime))

    report = DiagnosticReport()
    _cleanup_tmp_residuals(tmp_path, report)

    assert recent.exists(), "recent unscoped tmp wrongly deleted (could be a pre-H3 writer)"
    assert not old.exists(), "stale unscoped orphan should have been cleaned"
    assert any("tmp_residual_skipped_recent" in r.name for r in report.results)
    assert any("tmp_residual_cleaned" in r.name for r in report.results)


def test_cleanup_tmp_residuals_silent_when_dir_missing(tmp_path):
    """No-op when the directory itself doesn't exist."""
    nonexistent = tmp_path / "does_not_exist"
    report = DiagnosticReport()
    _cleanup_tmp_residuals(nonexistent, report)
    assert report.results == []


@pytest.mark.asyncio
async def test_startup_checks_fresh_dir_clean_report(tmp_path):
    """Tier A + B on a fresh empty data_dir: only INFO results."""
    eng = make_engine(tmp_path)
    await eng.startup()
    try:
        report = await run_startup_checks(eng, eng.config)
    finally:
        await eng.shutdown()

    assert not report.has_errors, f"unexpected errors: {report.by_level(DiagnosticLevel.ERROR)}"
    assert not report.has_warnings, f"unexpected warnings: {report.by_level(DiagnosticLevel.WARN)}"


@pytest.mark.asyncio
async def test_startup_checks_after_ingest_size_ok(tmp_path):
    """After indexing N docs, faiss.size and bm25.size match SQLite — no drift WARN."""
    eng = make_engine(tmp_path)
    await eng.startup()
    try:
        await eng.index_documents([{"content": f"doc {i}"} for i in range(20)])
        await eng.cache.flush_to_store(eng.store)
        report = await run_startup_checks(eng, eng.config)
    finally:
        await eng.shutdown()

    size_warnings = [
        r for r in report.by_level(DiagnosticLevel.WARN)
        if "size_drift" in r.name or "virtual_faiss_empty" in r.name
    ]
    assert size_warnings == [], f"unexpected size warnings: {size_warnings}"


@pytest.mark.asyncio
async def test_startup_checks_zero_byte_faiss_triggers_rebuild(tmp_path):
    """Tier A — a 0-byte FAISS file gets detected and rebuilt on startup."""
    # Phase 1: populate the engine, then sabotage the saved FAISS file.
    eng = make_engine(tmp_path)
    await eng.startup()
    try:
        await eng.index_documents([{"content": f"doc {i}"} for i in range(5)])
        await eng.cache.flush_to_store(eng.store)
    finally:
        await eng.shutdown()

    faiss_path = Path(eng.config.faiss_index_path)
    assert faiss_path.exists(), "test setup failed: FAISS file not saved"
    # Truncate to 0 bytes (mimic interrupted save with empty result).
    faiss_path.write_bytes(b"")
    assert faiss_path.stat().st_size == 0

    # Phase 2: boot again — diagnostics should detect the zero-byte file
    # and rebuild the FAISS index from the SQLite content.
    eng2 = make_engine(tmp_path)
    await eng2.startup()
    try:
        report = await run_startup_checks(eng2, eng2.config)

        errors = report.by_level(DiagnosticLevel.ERROR)
        assert any(r.name == "tier_a_raw_zero_bytes" for r in errors), (
            f"expected zero_bytes error, got: {[r.name for r in errors]}"
        )
        rebuilt = [r for r in report.results if r.name == "tier_a_raw_rebuilt"]
        assert rebuilt, "expected a rebuild record after 0-byte detection"
        assert eng2.faiss_index.size == 5, (
            f"expected FAISS size to recover to 5 after rebuild, got {eng2.faiss_index.size}"
        )
    finally:
        await eng2.shutdown()


@pytest.mark.asyncio
async def test_startup_checks_tmp_residual_cleaned_after_startup(tmp_path):
    """Tier A — startup_checks cleans up residual .tmp files even when
    the rest of the system is healthy."""
    eng = make_engine(tmp_path)
    await eng.startup()
    try:
        # H3: only a clearly-orphaned scratch (dead owning pid) is cleaned;
        # a recent unscoped name is kept (could be a pre-H3 live writer).
        dead = _dead_pid()
        faiss_path = Path(eng.config.faiss_index_path)
        residual = faiss_path.with_name(f"{faiss_path.name}.{dead}.tmp")
        residual.write_bytes(b"stale partial save")
        assert residual.exists()

        report = await run_startup_checks(eng, eng.config)

        assert not residual.exists(), "dead-pid residual .tmp not cleaned"
        cleaned = [r for r in report.results if r.name == "tier_a_tmp_residual_cleaned"]
        assert cleaned, "expected a tmp_residual_cleaned record"
    finally:
        await eng.shutdown()


@pytest.mark.asyncio
async def test_engine_startup_invokes_diagnostics(tmp_path, caplog):
    """The engine.startup() hook actually runs the diagnostics module."""
    import logging
    caplog.set_level(logging.INFO, logger="gaottt.diagnostics.startup")

    eng = make_engine(tmp_path)
    await eng.startup()
    try:
        # The summary line is logged from inside run_startup_checks.
        summary_msgs = [
            rec for rec in caplog.records
            if "Startup diagnostics complete" in rec.getMessage()
        ]
        assert summary_msgs, (
            "engine.startup() did not trigger diagnostics summary log"
        )
    finally:
        await eng.shutdown()
