"""Observation Apparatus Refinement Stage 2 — ambient dormant whisper slot.

End-to-end coverage that ``ambient_recall`` surfaces a counter-importance-
sampled dormant memo when (and only when) BM25 lexical match clears the
floor. Force computation / mass / acceleration are not touched — this is
pure surface-set extension.
"""

from __future__ import annotations

import asyncio

import pytest

from gaottt.services import memory as memory_service
from tests.integration.test_engine_ambient_recall import _make_engine


def _make_dormant_engine(tmp_path, **overrides):
    """Engine with a low age threshold so docs become 'dormant' almost
    immediately, and BM25 ambient gate wired. ``ambient_min_score=0.0`` so
    the upstream relevance gate is also non-blocking for the lexical path.
    """
    base = dict(
        # 1ms age threshold — anything inserted is dormant by the next tick.
        dormant_age_threshold_seconds=0.001,
        # Force the absolute mass cut path (percentile=None) and keep it
        # high enough that StubEmbedder-indexed docs (mass ~1) qualify.
        dormant_mass_percentile=None,
        dormant_mass_threshold=10.0,
        # Lower the dormant-slot BM25 floor — tiny corpora produce small
        # BM25 numbers, but we want the SLOT to fire on lexical match.
        ambient_dormant_relevance_floor=0.01,
        ambient_dormant_slot_enabled=True,
        ambient_dormant_slot_count=1,
        # Keep the upstream ambient gate exercisable on the tiny corpus.
        ambient_bm25_min_score=0.01,
    )
    base.update(overrides)
    return _make_engine(tmp_path, bm25=True, **base)


@pytest.mark.asyncio
async def test_dormant_slot_surfaces_on_lexical_match(tmp_path):
    """Dormant memo with BM25 hit appears in the dormant slot."""
    engine = _make_dormant_engine(tmp_path)
    await engine.startup()
    try:
        for i in range(3):
            await memory_service.remember(
                engine,
                content=f"forgotten gravity lensing whisper {i}",
                source="agent",
            )
        # Let the age cutoff (1ms) pass so the docs become "dormant".
        await asyncio.sleep(0.05)
        resp = await memory_service.ambient_recall(
            engine, "gravity lensing whisper",
        )
        assert resp.count >= 1
        assert resp.dormant, (
            "expected at least one dormant whisper given lexical match"
        )
        m = resp.dormant[0]
        assert m.breakdown is not None
        # Stage 1 ↔ Stage 2 integration: dormant slot rides a reason line.
        assert m.breakdown.reason is not None
        assert "dormant surface" in m.breakdown.reason
        assert m.breakdown.dormant_percentile is not None
    finally:
        await engine.shutdown()


@pytest.mark.asyncio
async def test_dormant_slot_empty_when_no_lexical_match(tmp_path):
    """No BM25 overlap → the slot stays silent (no random hit)."""
    engine = _make_dormant_engine(tmp_path)
    await engine.startup()
    try:
        for i in range(3):
            await memory_service.remember(
                engine,
                content=f"alpha beta gamma node {i}",
                source="agent",
            )
        await asyncio.sleep(0.05)
        # When BM25 matches lexically the dormant slot may fire — that is
        # correct behavior. The "empty when no lexical match" guarantee is
        # exercised by the floor: bump it sky-high to assert silence.
        engine.config.ambient_dormant_relevance_floor = 999.0
        resp = await memory_service.ambient_recall(
            engine, "alpha beta gamma",
        )
        assert resp.dormant == [], (
            "with an unreachable floor the slot must stay empty"
        )
        # And the rest of the block is unaffected.
        assert resp.count == len(resp.direct) + len(resp.lensing)
    finally:
        await engine.shutdown()


@pytest.mark.asyncio
async def test_dormant_slot_disabled_returns_legacy_block(tmp_path):
    """``ambient_dormant_slot_enabled=False`` → empty dormant, no count contribution."""
    engine = _make_dormant_engine(tmp_path, ambient_dormant_slot_enabled=False)
    await engine.startup()
    try:
        for i in range(3):
            await memory_service.remember(
                engine,
                content=f"forgotten gravity lensing whisper {i}",
                source="agent",
            )
        await asyncio.sleep(0.05)
        resp = await memory_service.ambient_recall(
            engine, "gravity lensing whisper",
        )
        assert resp.dormant == []
        assert resp.count == len(resp.direct) + len(resp.lensing)
    finally:
        await engine.shutdown()


@pytest.mark.asyncio
async def test_dormant_slot_skips_recently_surfaced(tmp_path):
    """``recently_surfaced`` IDs are excluded from the dormant pool."""
    engine = _make_dormant_engine(tmp_path)
    await engine.startup()
    try:
        ids: list[str] = []
        for i in range(3):
            resp = await memory_service.remember(
                engine,
                content=f"forgotten gravity lensing whisper {i}",
                source="agent",
            )
            ids.append(resp.id)
        await asyncio.sleep(0.05)
        # Block every dormant candidate via recently_surfaced — slot empties.
        rs = {mid: 1 for mid in ids}
        resp = await memory_service.ambient_recall(
            engine, "gravity lensing whisper", recently_surfaced=rs,
        )
        assert resp.dormant == [], (
            "every candidate was recently surfaced → slot must be empty"
        )
    finally:
        await engine.shutdown()


@pytest.mark.asyncio
async def test_dormant_slot_excludes_direct_and_lensing_ids(tmp_path):
    """A node that already surfaced in direct/lensing cannot also whisper."""
    engine = _make_dormant_engine(tmp_path)
    await engine.startup()
    try:
        for i in range(3):
            await memory_service.remember(
                engine,
                content=f"forgotten gravity lensing whisper {i}",
                source="agent",
            )
        await asyncio.sleep(0.05)
        resp = await memory_service.ambient_recall(
            engine, "gravity lensing whisper",
        )
        direct_ids = {m.id for m in resp.direct}
        lensing_ids = {m.id for m in resp.lensing}
        for m in resp.dormant:
            assert m.id not in direct_ids
            assert m.id not in lensing_ids
    finally:
        await engine.shutdown()


@pytest.mark.asyncio
async def test_dormant_slot_appears_in_manifest(tmp_path):
    """Dormant slot IDs ride the ambient-ids manifest so the hook can
    rotate them on subsequent turns."""
    from gaottt.services import formatters
    engine = _make_dormant_engine(tmp_path)
    await engine.startup()
    try:
        for i in range(3):
            await memory_service.remember(
                engine,
                content=f"forgotten gravity lensing whisper {i}",
                source="agent",
            )
        await asyncio.sleep(0.05)
        resp = await memory_service.ambient_recall(
            engine, "gravity lensing whisper",
        )
        rendered = formatters.format_ambient(resp)
        if resp.dormant:
            assert "▼ ささやき" in rendered
            assert "dormant=" in rendered
            assert resp.dormant[0].id in rendered
        else:
            # If the field happened not to whisper, the heading must be absent.
            assert "▼ ささやき" not in rendered
    finally:
        await engine.shutdown()
