"""Tier 5 integrity — FAISS↔SQLite size invariant.

This is the direct guard against the 2026-05-14 incident where the
production FAISS index ended up with 15 vectors while SQLite had 31 000
active documents.

Contract under test (after ``compact(rebuild_faiss=True)``):

    faiss.size == count(active documents in SQLite)

Plus the looser contract for non-compact paths:

    faiss.size grows by exactly N after ``index_documents(N docs)``.
    faiss.size never *shrinks* without a rebuild.
"""
from __future__ import annotations

import pytest

from tests.perf._helpers import active_doc_count, make_engine


async def _faiss_active_match(eng) -> tuple[int, int]:
    """Return ``(faiss_size, sqlite_active_count)`` after flushing the cache."""
    await eng.cache.flush_to_store(eng.store)
    return eng.faiss_index.size, await active_doc_count(eng)


@pytest.mark.asyncio
async def test_faiss_grows_with_remember(tmp_path):
    eng = make_engine(tmp_path)
    await eng.startup()
    try:
        assert eng.faiss_index.size == 0
        await eng.index_documents([{"content": f"doc {i}"} for i in range(5)])
        f, s = await _faiss_active_match(eng)
        assert f == 5 and s == 5

        await eng.index_documents([{"content": f"more doc {i}"} for i in range(3)])
        f, s = await _faiss_active_match(eng)
        assert f == 8 and s == 8
    finally:
        await eng.shutdown()


@pytest.mark.asyncio
async def test_faiss_matches_active_after_compact(tmp_path):
    """After compact(rebuild_faiss=True) the invariant is strict equality."""
    eng = make_engine(tmp_path)
    await eng.startup()
    try:
        ids = await eng.index_documents(
            [{"content": f"strict invariant doc {i}"} for i in range(10)]
        )
        await eng.compact(rebuild_faiss=True)
        f, s = await _faiss_active_match(eng)
        assert f == s == 10, f"After compact: faiss={f} sqlite_active={s}"

        # Soft-forget 3 → before compact FAISS still has them, after compact it does not
        await eng.forget(ids[:3], hard=False)
        await eng.compact(rebuild_faiss=True)
        f, s = await _faiss_active_match(eng)
        assert f == s == 7, f"After soft-forget+compact: faiss={f} sqlite_active={s}"

        # Restore them → counts return
        await eng.restore(ids[:3])
        await eng.compact(rebuild_faiss=True)
        f, s = await _faiss_active_match(eng)
        assert f == s == 10, f"After restore+compact: faiss={f} sqlite_active={s}"
    finally:
        await eng.shutdown()


@pytest.mark.asyncio
async def test_faiss_matches_active_after_hard_forget(tmp_path):
    """Hard delete + compact reduces both stores in lockstep."""
    eng = make_engine(tmp_path)
    await eng.startup()
    try:
        ids = await eng.index_documents(
            [{"content": f"hard-delete doc {i}"} for i in range(6)]
        )
        await eng.compact(rebuild_faiss=True)
        f0, s0 = await _faiss_active_match(eng)
        assert f0 == s0 == 6

        await eng.forget(ids[:2], hard=True)
        await eng.compact(rebuild_faiss=True)
        f, s = await _faiss_active_match(eng)
        assert f == s == 4, f"After hard-forget+compact: faiss={f} sqlite_active={s}"
    finally:
        await eng.shutdown()


@pytest.mark.asyncio
async def test_faiss_matches_active_after_merge(tmp_path):
    """Merge archives the absorbed nodes; compact must remove their vectors."""
    eng = make_engine(tmp_path)
    await eng.startup()
    try:
        ids = await eng.index_documents([
            {"content": "near-duplicate A — gravity collision test"},
            {"content": "near-duplicate B — gravity collision test variant"},
            {"content": "unrelated control document about pasta"},
        ])
        await eng.compact(rebuild_faiss=True)
        f0, s0 = await _faiss_active_match(eng)
        assert f0 == s0 == 3

        await eng.merge([ids[0], ids[1]])
        await eng.compact(rebuild_faiss=True)
        f, s = await _faiss_active_match(eng)
        assert f == s == 2, f"After merge+compact: faiss={f} sqlite_active={s}"
    finally:
        await eng.shutdown()


@pytest.mark.asyncio
async def test_faiss_survives_reboot_without_drift(tmp_path):
    """The dangerous failure mode — boot, persist, reboot, FAISS≠SQLite.

    Reproduces the 2026-05-14 incident's *symptom*: confirm the engine
    never lands in a state where the persisted FAISS index is smaller
    than the persisted SQLite document count.
    """
    eng1 = make_engine(tmp_path)
    await eng1.startup()
    try:
        await eng1.index_documents(
            [{"content": f"persist doc {i}"} for i in range(7)]
        )
        await eng1.cache.flush_to_store(eng1.store)
    finally:
        await eng1.shutdown()

    eng2 = make_engine(tmp_path)
    await eng2.startup()
    try:
        f, s = await _faiss_active_match(eng2)
        assert f >= s, (
            f"FAISS shrunk on reboot: faiss={f} < sqlite_active={s} "
            "— this is the production failure mode Tier 5 guards against"
        )
        # Tighter check: after a deterministic compact they must match.
        await eng2.compact(rebuild_faiss=True)
        f, s = await _faiss_active_match(eng2)
        assert f == s, f"Post-reboot compact: faiss={f} ≠ sqlite_active={s}"
    finally:
        await eng2.shutdown()
