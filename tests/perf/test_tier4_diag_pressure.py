"""Phase P diagnostic CLI smoke (Tier 4).

Verifies ``scripts/diag_pressure.py snapshot`` exits cleanly on a seeded
isolated DB and that its JSON mode is parseable + contains the expected
fields (hubs / lambda_accel_stats / langevin_sigma).

The script is read-only by construction (no mutation contract); we only
test that contract by running it against a tmp DB and checking exit code
+ JSON shape. End-to-end "Λ literal form" / "σ scale" / "noise added"
correctness is already covered by the unit suites under
``tests/unit/test_phase_p_lambda.py`` and ``tests/unit/test_phase_p_langevin.py``.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from tests.perf._helpers import make_engine


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "diag_pressure.py"


@pytest.mark.asyncio
async def test_diag_pressure_snapshot_exits_zero(tmp_path):
    """Seed a tiny isolated DB, run snapshot, expect exit 0 + parseable JSON."""
    eng = make_engine(tmp_path)
    await eng.startup()
    try:
        await eng.index_documents([
            {"content": "alpha gravity wave note", "metadata": {"source": "agent"}},
            {"content": "beta gravity field memo", "metadata": {"source": "agent"}},
            {"content": "gamma unrelated text", "metadata": {"source": "agent"}},
            {"content": "delta separate topic", "metadata": {"source": "agent"}},
            {"content": "epsilon another doc", "metadata": {"source": "agent"}},
        ])
    finally:
        await eng.shutdown()

    result = subprocess.run(
        [
            sys.executable, str(SCRIPT), "snapshot",
            "--data-dir", str(tmp_path),
            "--top-k-hubs", "3",
            "--neighbor-k", "4",
            "--lambda-h", "0.005",
            "--langevin-t0", "0.005",
            "--json",
        ],
        capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, (
        f"diag_pressure failed:\nstdout={result.stdout}\nstderr={result.stderr}"
    )
    payload = json.loads(result.stdout)
    assert payload["total_active_nodes"] >= 1
    assert payload["lambda_h"] == 0.005
    assert payload["langevin_t0"] == 0.005
    # σ = √(2·T₀) — within fp tolerance
    assert abs(payload["langevin_sigma"] - (2 * 0.005) ** 0.5) < 1e-6
    assert "hubs" in payload
    assert "lambda_accel_stats" in payload
    if payload["hubs"]:
        h0 = payload["hubs"][0]
        assert "lambda_accel_norm" in h0
        assert "langevin_expected_step_norm" in h0
        assert h0["langevin_expected_step_norm"] > 0


@pytest.mark.asyncio
async def test_diag_pressure_text_mode_has_headlines(tmp_path):
    """Text mode renders the headline summary and the per-hub table header."""
    eng = make_engine(tmp_path)
    await eng.startup()
    try:
        await eng.index_documents([
            {"content": f"gravity wave probe {i}", "metadata": {"source": "agent"}}
            for i in range(5)
        ])
    finally:
        await eng.shutdown()

    result = subprocess.run(
        [
            sys.executable, str(SCRIPT), "snapshot",
            "--data-dir", str(tmp_path),
            "--top-k-hubs", "3",
        ],
        capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0
    out = result.stdout
    assert "=== Phase P dry-run snapshot ===" in out
    assert "Λ  (P-α)" in out
    assert "Langevin (P-β)" in out
    assert "Top" in out and "mass hubs" in out
    assert "=== Headlines ===" in out


@pytest.mark.asyncio
async def test_diag_pressure_writes_out_file(tmp_path):
    """--out writes the report to a file, stdout stays quiet."""
    eng = make_engine(tmp_path)
    await eng.startup()
    try:
        await eng.index_documents([
            {"content": f"gravity wave probe {i}", "metadata": {"source": "agent"}}
            for i in range(3)
        ])
    finally:
        await eng.shutdown()

    out_path = tmp_path / "snap.json"
    result = subprocess.run(
        [
            sys.executable, str(SCRIPT), "snapshot",
            "--data-dir", str(tmp_path),
            "--top-k-hubs", "2",
            "--json",
            "--out", str(out_path),
        ],
        capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0
    assert out_path.exists()
    payload = json.loads(out_path.read_text())
    assert payload["total_active_nodes"] >= 1
