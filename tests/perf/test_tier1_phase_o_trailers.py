"""Tier 1 smoke — Phase O observability trailers actually appear.

Substring-level contracts on the MCP formatter output. These complement
the structural assertions in Tier 4 (which read the Pydantic payload
directly) by guarding the *user-visible* surface: if the trailer goes
missing or the wording silently changes, this fires.

Two trailers are exercised:

  - Stage 1 score breakdown: ``breakdown: cos=...`` line per item
  - Stage 2 training delta:  ``## 訓練差分`` section, including the
    ``(cache hit — no simulation ran; ...)`` variant for prefetch hits.

The cache-hit substring is verbatim from CLAUDE.md ("MCP formatter の
出力文字列を変えない") — substring assertions are how that contract is
machine-enforced.
"""
from __future__ import annotations

import pytest

from gaottt.server import mcp_server as srv
from tests.perf._helpers import make_engine


@pytest.fixture
async def engine_singleton(tmp_path, monkeypatch):
    eng = make_engine(tmp_path, query_kick_enabled=True, query_kick_strength=0.05)
    await eng.startup()
    monkeypatch.setattr(srv, "_engine", eng)
    try:
        yield eng
    finally:
        monkeypatch.setattr(srv, "_engine", None)
        await eng.shutdown()


async def test_recall_emits_score_breakdown_line(engine_singleton):
    """Phase O Stage 1 — every recall item carries a breakdown line."""
    await srv.remember(content="Phase O smoke: gravity field observability layer", source="agent")
    out = await srv.recall(query="observability", top_k=3)
    assert "breakdown: cos=" in out, (
        "Phase O Stage 1 score breakdown line missing from recall output. "
        f"Got: {out[:500]!r}"
    )


async def test_recall_emits_training_delta_trailer(engine_singleton):
    """Phase O Stage 2 — recall output ends with a ``## 訓練差分`` section."""
    await srv.remember(content="Phase O smoke: backward-pass delta visibility", source="agent")
    out = await srv.recall(query="backward-pass delta", top_k=3)
    assert "## 訓練差分" in out, (
        "Phase O Stage 2 training-delta trailer missing from recall output. "
        f"Got: {out[:500]!r}"
    )
    assert "wave_reached=" in out, (
        "Stage 2 trailer present but wave_reached telemetry missing"
    )


async def test_prefetch_then_recall_emits_cache_hit_phrase(engine_singleton):
    """Prefetch → recall(same query) → trailer shows the cache-hit phrase.

    The exact phrase ``(cache hit — no simulation ran; mass / displacement
    unchanged)`` is a contract: tooling parses it as the *no-perturbation*
    signal. Substring match guards both the routing and the wording.
    """
    await srv.remember(content="Phase O smoke: cache hit no perturbation contract", source="agent")
    await srv.prefetch(query="cache hit perturbation", top_k=3)
    # Drain so the background prefetch task actually finishes before recall.
    await engine_singleton.prefetch_pool.drain(timeout=5.0)

    out = await srv.recall(query="cache hit perturbation", top_k=3)
    assert "cache hit — no simulation ran" in out, (
        "Phase O Stage 2 cache-hit phrase missing from prefetch→recall output. "
        f"Got: {out[:500]!r}"
    )
    # And the trailer header should still be present.
    assert "## 訓練差分" in out
