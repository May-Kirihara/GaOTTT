"""Ambient Recall — passive (read-only) recall (integration).

A passive recall (``engine.query(..., passive=True)``) runs the search in
full and returns the same results as an active recall, but must leave the
gravity field untouched: no mass update, no query-attraction displacement,
no co-occurrence edges. Default ``passive=False`` keeps recall a TTT step.

Every "passive leaves X unchanged" assertion is paired with a positive
control proving an *active* recall *does* change X — otherwise a silently
broken (no-op) recall path would let the test pass vacuously.
"""
from __future__ import annotations

import numpy as np
import pytest

from gaottt.config import GaOTTTConfig
from gaottt.core.engine import GaOTTTEngine
from gaottt.index.faiss_index import FaissIndex
from gaottt.store.cache import CacheLayer
from gaottt.store.sqlite_store import SqliteStore
from tests.integration.test_engine_query_kick import StubEmbedder


def _make_engine(tmp_path):
    config = GaOTTTConfig(
        embedding_dim=64,
        data_dir=str(tmp_path),
        db_path=str(tmp_path / "test.db"),
        faiss_index_path=str(tmp_path / "test.faiss"),
        # Query attraction on so an *active* recall visibly moves displacement.
        query_kick_strength=0.1,
        query_kick_enabled=True,
        mass_anchor_threshold=0.0,
        genesis_kick_enabled=False,
        dream_enabled=False,
        faiss_save_interval_seconds=0.0,
        flush_interval_seconds=0.05,
    )
    embedder = StubEmbedder(dim=config.embedding_dim)
    return GaOTTTEngine(
        config=config,
        embedder=embedder,
        faiss_index=FaissIndex(dimension=config.embedding_dim),
        cache=CacheLayer(
            flush_interval=config.flush_interval_seconds,
            flush_threshold=config.flush_threshold,
        ),
        store=SqliteStore(db_path=config.db_path),
    )


def _snapshot(engine, node_ids):
    """Capture (mass, displacement) for every node id."""
    masses, disps = {}, {}
    for nid in node_ids:
        state = engine.cache.get_node(nid)
        masses[nid] = float(state.mass) if state is not None else 0.0
        d = engine.cache.get_displacement(nid)
        disps[nid] = d.copy() if d is not None else None
    return masses, disps


def _disp_equal(a, b) -> bool:
    if a is None and b is None:
        return True
    if a is None:
        return float(np.linalg.norm(b)) == 0.0
    if b is None:
        return float(np.linalg.norm(a)) == 0.0
    return np.array_equal(a, b)


@pytest.mark.asyncio
async def test_passive_recall_does_not_perturb_field(tmp_path):
    """10 passive recalls move neither mass, displacement, nor co-occurrence;
    a single active recall (positive control) moves at least mass + edges."""
    engine = _make_engine(tmp_path)
    await engine.startup()
    try:
        await engine.index_documents([
            {"content": f"passive-doc-{i}", "metadata": {"source": "agent"}}
            for i in range(5)
        ])
        # One active recall so the field starts in a non-trivial state.
        first = await engine.query(text="passive-probe", top_k=5)
        ids = [r.id for r in first]
        assert ids, "setup: first recall must return results"

        masses_before, disps_before = _snapshot(engine, ids)
        cooc_before = sum(engine.graph._cooccurrence_counts.values())

        results = []
        for _ in range(10):
            results = await engine.query(
                text="passive-probe", top_k=5, passive=True,
            )
        assert results, "passive recall must still return results"

        masses_after, disps_after = _snapshot(engine, ids)
        cooc_after = sum(engine.graph._cooccurrence_counts.values())

        assert masses_after == masses_before, "passive recall changed mass"
        for nid in ids:
            assert _disp_equal(disps_before[nid], disps_after[nid]), (
                f"passive recall moved displacement of {nid}"
            )
        assert cooc_after == cooc_before, "passive recall wrote co-occurrence"

        # Positive control — an active recall MUST perturb the field,
        # otherwise the assertions above are vacuous.
        await engine.query(text="passive-probe", top_k=5)
        masses_ctrl, _ = _snapshot(engine, ids)
        cooc_ctrl = sum(engine.graph._cooccurrence_counts.values())
        assert masses_ctrl != masses_before, (
            "active recall did not change mass — passive test is vacuous"
        )
        assert cooc_ctrl > cooc_before, (
            "active recall did not write co-occurrence — passive test is vacuous"
        )
    finally:
        await engine.shutdown()


@pytest.mark.asyncio
async def test_passive_recall_returns_same_results_as_active(tmp_path):
    """Read-only does not mean empty — a passive recall returns the same
    result ids as an active recall over the identical (cold) field."""
    engine = _make_engine(tmp_path)
    await engine.startup()
    try:
        await engine.index_documents([
            {"content": f"parity-doc-{i}", "metadata": {"source": "agent"}}
            for i in range(5)
        ])
        # Passive first (no mutation) → the active recall sees the identical
        # cold field, so retrieval and ordering must match exactly.
        passive = await engine.query(text="parity-probe", top_k=5, passive=True)
        active = await engine.query(text="parity-probe", top_k=5)
        assert len(passive) >= 1
        assert [r.id for r in passive] == [r.id for r in active]
    finally:
        await engine.shutdown()


@pytest.mark.asyncio
async def test_passive_recall_does_not_poison_prefetch_cache(tmp_path):
    """A passive recall reads the prefetch cache but never writes it — a
    cached passive result must not let a later active recall hit the cache
    and silently skip its simulation update."""
    engine = _make_engine(tmp_path)
    await engine.startup()
    try:
        await engine.index_documents([
            {"content": f"cache-doc-{i}", "metadata": {"source": "agent"}}
            for i in range(5)
        ])
        ids = [r.id for r in (await engine.query(text="cache-probe", top_k=5))]

        # Passive recall with caching enabled — must not populate the cache.
        await engine.query(
            text="cache-probe", top_k=5, use_cache=True, passive=True,
        )
        assert engine.prefetch_cache.get("cache-probe", 5, None, None) is None

        # Therefore an active cached recall still runs its simulation.
        masses_before, _ = _snapshot(engine, ids)
        await engine.query(text="cache-probe", top_k=5, use_cache=True)
        masses_after, _ = _snapshot(engine, ids)
        assert masses_after != masses_before, (
            "active recall hit a passive-populated cache and skipped its update"
        )
    finally:
        await engine.shutdown()


@pytest.mark.asyncio
async def test_passive_recall_does_not_change_return_count(tmp_path):
    """Lateral Association Stage 1 sub-step 0 (2026-05-25) — passive recall
    must not mutate ``return_count`` either.

    Before the gate fix, ``return_count`` was incremented for top-K and
    decayed for all reached even with ``passive=True``. Because saturation
    is ``1 / (1 + return_count * saturation_rate)`` and feeds final_score,
    ambient_recall (passive) was silently rotating the direct slot each
    turn via saturation drift — the "uncontrolled direct-slot variation"
    documented in Stage 6a baseline.

    See ``scripts/probe_ambient_nondeterminism.py`` for the literal probe
    that confirmed this. Paired positive control: an active recall MUST
    move return_count, otherwise the assertion below is vacuous.
    """
    engine = _make_engine(tmp_path)
    await engine.startup()
    try:
        await engine.index_documents([
            {"content": f"rc-doc-{i}", "metadata": {"source": "agent"}}
            for i in range(5)
        ])
        # One active recall first so the field has non-zero return_count.
        first = await engine.query(text="rc-probe", top_k=5)
        ids = [r.id for r in first]
        assert ids, "setup: first recall must return results"

        rc_before = {
            nid: engine.cache.get_node(nid).return_count for nid in ids
        }
        # 10 passive recalls — return_count must be byte-identical after.
        for _ in range(10):
            await engine.query(text="rc-probe", top_k=5, passive=True)
        rc_after = {
            nid: engine.cache.get_node(nid).return_count for nid in ids
        }
        for nid in ids:
            assert rc_after[nid] == rc_before[nid], (
                f"passive recall changed return_count for {nid}: "
                f"{rc_before[nid]} → {rc_after[nid]}"
            )

        # Positive control — an active recall MUST move return_count,
        # otherwise the assertion above could pass vacuously.
        await engine.query(text="rc-probe", top_k=5)
        rc_ctrl = {
            nid: engine.cache.get_node(nid).return_count for nid in ids
        }
        moved = any(rc_ctrl[nid] != rc_before[nid] for nid in ids)
        assert moved, (
            "active recall did not change return_count — passive test is vacuous"
        )
    finally:
        await engine.shutdown()
