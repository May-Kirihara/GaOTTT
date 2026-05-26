"""Observation Apparatus Refinement Stage 3 — compare-retrieval CLI smoke.

Asserts ``scripts/compare_retrieval.py`` exits 0 against a seeded
isolated data directory and that its JSON mode is valid JSON with the
four expected columns. Read-only by construction (the script uses
``passive=True`` recall and disables training_delta on explore).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from tests.perf._helpers import make_engine


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "compare_retrieval.py"


@pytest.mark.asyncio
async def test_compare_retrieval_script_exits_zero(tmp_path):
    """Seed an isolated DB, invoke the script, check exit 0 + JSON shape."""
    eng = make_engine(tmp_path)
    await eng.startup()
    try:
        await eng.index_documents([
            {"content": "alpha gravity wave note", "metadata": {"source": "agent"}},
            {"content": "beta gravity field memo", "metadata": {"source": "agent"}},
            {"content": "gamma unrelated text", "metadata": {"source": "agent"}},
        ])
    finally:
        await eng.shutdown()

    result = subprocess.run(
        [
            sys.executable, str(SCRIPT_PATH), "gravity wave",
            "--data-dir", str(tmp_path),
            "--top-k", "3",
            "--json",
        ],
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, (
        f"compare_retrieval failed: stderr={result.stderr!r}"
    )
    payload = json.loads(result.stdout)
    labels = {c["label"] for c in payload["columns"]}
    assert "recall (passive)" in labels
    assert "explore diversity=0.9" in labels
    assert "explore mode=dormant" in labels
    assert "ambient_recall" in labels


@pytest.mark.asyncio
async def test_compare_retrieval_text_mode_includes_sections(tmp_path):
    """Text rendering shows the four column headings and the summary."""
    eng = make_engine(tmp_path)
    await eng.startup()
    try:
        await eng.index_documents([
            {"content": "alpha gravity wave note", "metadata": {"source": "agent"}},
        ])
    finally:
        await eng.shutdown()

    result = subprocess.run(
        [
            sys.executable, str(SCRIPT_PATH), "gravity wave",
            "--data-dir", str(tmp_path),
            "--top-k", "3",
        ],
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0
    out = result.stdout
    assert "=== recall (passive)" in out
    assert "=== explore diversity=0.9" in out
    assert "=== explore mode=dormant" in out
    assert "=== ambient_recall" in out
    assert "=== overlap / dominance warning" in out
