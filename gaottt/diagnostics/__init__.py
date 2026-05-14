"""Startup-time self-diagnostics for GaOTTT.

Stage 1 (commitment id=aaa6e7cc): catch the three failure modes
observed 2026-05-14 — FAISS empty / WAL bloat residue / 0-byte
virtual.faiss — at engine.startup() so they surface immediately
rather than after a session of mysteriously empty recall results.

Public entry point: ``run_startup_checks(engine, config)``.
"""
from gaottt.diagnostics.startup import (
    DiagnosticLevel,
    DiagnosticReport,
    DiagnosticResult,
    run_startup_checks,
)

__all__ = [
    "DiagnosticLevel",
    "DiagnosticReport",
    "DiagnosticResult",
    "run_startup_checks",
]
