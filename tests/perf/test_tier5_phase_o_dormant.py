"""Tier 5 — Phase O Stage 5 dormant counter-importance sampling, both branches.

Two contracts on ``explore(mode='dormant')``:

A. **Match branch** — when the corpus has memos satisfying
   ``age ≥ dormant_age_threshold_seconds AND mass ≤ dormant_mass_threshold
   AND source ∈ dormant_source_classes``, the formatter emits
   ``💭 Dormant memories surfaced (N):`` and returns up to ``top_k`` items.

B. **Empty branch** — when nothing satisfies the triple, the formatter
   emits ``💭 No dormant memories to surface (none match age + mass +
   source-class conditions).`` and the service returns ``count=0``.

Both branches matter: GLM's 2026-05-15 production playthrough hit the
empty branch (the well-tuned 33k corpus has no qualifying memos), which
is the *correct* user-visible signal that the mechanism is alive but
the thresholds don't match the field's current distribution
(``project_phase_o_stage_5_production_observation``). A regression that
swaps the two branches, or silently returns empty for both, would erase
that distinction.

To exercise the match branch deterministically, this test sets
``dormant_age_threshold_seconds=0`` so freshly-ingested ``source=agent``
memos qualify immediately. That's the same knob production will use to
re-tune Stage 5 alongside Phase M Stage 2.
"""
from __future__ import annotations

import pytest

from gaottt.server import mcp_server as srv
from gaottt.services import memory as mem_svc
from tests.perf._helpers import make_engine


# Match-branch engine: age threshold = 0 makes everything age-qualified
# immediately. Mass starts at 1.0 (< default 2.0 threshold), source=agent
# is in default dormant_source_classes.
MATCH_OVERRIDES = dict(dormant_age_threshold_seconds=0.0)

# Empty-branch engine: dormant_source_classes restricted to a class no
# new memo will have, so nothing matches even though age=0 qualifies.
EMPTY_OVERRIDES = dict(
    dormant_age_threshold_seconds=0.0,
    dormant_source_classes=("class-that-no-memo-has",),
)


@pytest.mark.asyncio
async def test_dormant_match_branch_returns_items_and_header(tmp_path, monkeypatch):
    """Match branch — services returns items, formatter emits ``Dormant memories surfaced``."""
    eng = make_engine(tmp_path, **MATCH_OVERRIDES)
    await eng.startup()
    monkeypatch.setattr(srv, "_engine", eng)
    try:
        # Seed 3 agent memos so the field has dormant candidates.
        for i in range(3):
            await srv.remember(
                content=f"Dormant smoke memo {i}: a quiet thought waiting in the cold cosmos",
                source="agent",
            )

        # Service path — structural assertion on the response payload.
        svc_result = await mem_svc.explore(
            engine=eng, query="_ignored", top_k=5, mode="dormant", auto_route=False,
        )
        assert svc_result.count >= 1, (
            f"dormant match branch returned count={svc_result.count}, expected ≥1"
        )
        assert svc_result.count <= 3
        assert all(i.source == "agent" for i in svc_result.items)

        # Formatter path — substring assertion on the MCP output.
        out = await srv.explore(query="_ignored", top_k=5, mode="dormant")
        assert "💭 Dormant memories surfaced" in out, (
            f"Stage 5 match-branch header missing. Got: {out[:300]!r}"
        )
        assert "No dormant memories" not in out
    finally:
        monkeypatch.setattr(srv, "_engine", None)
        await eng.shutdown()


@pytest.mark.asyncio
async def test_dormant_empty_branch_returns_zero_and_no_match_header(tmp_path, monkeypatch):
    """Empty branch — when no memo matches, formatter emits the diagnostic message.

    Critical because GLM's production playthrough hit *this* branch, and the
    message must be the actionable one ("none match age + mass + source-class
    conditions") not a silent empty string.
    """
    eng = make_engine(tmp_path, **EMPTY_OVERRIDES)
    await eng.startup()
    monkeypatch.setattr(srv, "_engine", eng)
    try:
        # Seed memos that *would* qualify under defaults — but our overrides
        # restrict source_classes so none match.
        for i in range(3):
            await srv.remember(
                content=f"Dormant empty-branch memo {i}: should not surface",
                source="agent",
            )

        svc_result = await mem_svc.explore(
            engine=eng, query="_ignored", top_k=5, mode="dormant", auto_route=False,
        )
        assert svc_result.count == 0, (
            f"dormant empty branch returned count={svc_result.count}, expected 0 "
            "(source-class override should have excluded all candidates)"
        )

        out = await srv.explore(query="_ignored", top_k=5, mode="dormant")
        assert "💭 No dormant memories to surface" in out, (
            f"Stage 5 empty-branch header missing. Got: {out[:300]!r}"
        )
        assert "none match age + mass + source-class" in out, (
            "Empty-branch diagnostic detail dropped — caller loses tuning signal"
        )
    finally:
        monkeypatch.setattr(srv, "_engine", None)
        await eng.shutdown()


@pytest.mark.asyncio
async def test_dormant_skips_wave_and_routing(tmp_path):
    """Mode=dormant bypasses wave entirely — no training_delta, no routing_hint.

    This is the structural sanity check that the dormant branch in
    ``services.explore`` early-returns *before* the wave / routing path.
    A regression that lets it fall through would surface a misleading
    training_delta (zeros from a wave that wasn't relevant).
    """
    eng = make_engine(tmp_path, **MATCH_OVERRIDES)
    await eng.startup()
    try:
        await mem_svc.remember(engine=eng, content="dormant skip-path memo", source="agent")

        result = await mem_svc.explore(
            engine=eng, query="_ignored", top_k=3, mode="dormant", auto_route=True,
        )
        # mode='dormant' early-returns before training_delta is collected and
        # before _build_routing_hint is called.
        assert result.training_delta is None, (
            "Stage 5 dormant branch emitted training_delta — wave path leaked through"
        )
        assert result.routing_hint is None, (
            "Stage 5 dormant branch emitted routing_hint — routing path leaked through"
        )
    finally:
        await eng.shutdown()
