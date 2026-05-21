"""Regression: H2 — last-write-wins guard on node flush.

The DB is shared across processes, each with its own cache. A process
holding a STALE NodeState that keeps flushing must not reverse-overwrite a
value another process advanced further (the documented "逆方向上書き罠").
``save_node_states`` upserts conditionally on the monotonic ``rev``
(bumped by cache.set_node): only ``excluded.rev >= nodes.rev`` writes win.
A rejected stale flush is a no-op row, not silent corruption, and is
logged.
"""
from __future__ import annotations

import logging
import time

import pytest

from gaottt.core.types import NodeState
from gaottt.store.sqlite_store import SqliteStore


@pytest.fixture
async def store(tmp_path):
    s = SqliteStore(db_path=str(tmp_path / "ger.db"))
    await s.initialize()
    yield s
    await s.close()


async def _save(store, node_id, *, rev, mass):
    await store.save_node_states(
        [NodeState(id=node_id, mass=mass, last_access=time.time(), rev=rev)]
    )


async def test_stale_flush_does_not_overwrite_newer_rev(store, caplog):
    await store.save_documents([{"id": "n1", "content": "c", "metadata": None}])

    # Process A advances the node to rev=5, mass=100.
    await _save(store, "n1", rev=5, mass=100.0)
    assert (await store.get_node_states(["n1"]))["n1"].mass == pytest.approx(100.0)

    # Process B holds a STALE copy (rev=3) and flushes mass=1.0.
    with caplog.at_level(logging.WARNING, logger="gaottt.store.sqlite_store"):
        await _save(store, "n1", rev=3, mass=1.0)

    survivor = (await store.get_node_states(["n1"]))["n1"]
    assert survivor.mass == pytest.approx(100.0), (
        "a stale (lower-rev) flush overwrote a newer persisted value "
        "(H2 regression — last-write-wins guard not applied)"
    )
    assert survivor.rev == 5
    # The rejection must be observable, not silent.
    assert any("skipped" in r.message for r in caplog.records), (
        "stale-flush rejection should emit a WARNING (detectable skip)"
    )


async def test_newer_and_equal_rev_flush_wins(store):
    await store.save_documents([{"id": "n1", "content": "c", "metadata": None}])
    await _save(store, "n1", rev=5, mass=100.0)

    # Strictly newer rev → applied.
    await _save(store, "n1", rev=7, mass=50.0)
    s = (await store.get_node_states(["n1"]))["n1"]
    assert s.mass == pytest.approx(50.0)
    assert s.rev == 7

    # Equal rev → also applied (last-write-wins on tie is intended; two
    # processes that independently reached the same rev shouldn't deadlock
    # into a permanently unwritable row).
    await _save(store, "n1", rev=7, mass=60.0)
    assert (await store.get_node_states(["n1"]))["n1"].mass == pytest.approx(60.0)


async def test_fresh_insert_unaffected_by_guard(store):
    """The WHERE clause gates only the ON CONFLICT DO UPDATE branch; a
    brand-new node (no conflict) always inserts, even at rev=0."""
    await store.save_documents([{"id": "fresh", "content": "c", "metadata": None}])
    await _save(store, "fresh", rev=0, mass=2.0)
    s = (await store.get_node_states(["fresh"]))["fresh"]
    assert s.mass == pytest.approx(2.0)
    assert s.rev == 0


async def test_rev_round_trips_through_store(store):
    """rev must persist and reload so the guard works across processes
    (a restarted process must see the advanced rev, not reset to 0)."""
    await store.save_documents([{"id": "n1", "content": "c", "metadata": None}])
    await _save(store, "n1", rev=42, mass=9.0)
    # Simulate a fresh process loading state from the store.
    reloaded = (await store.get_all_node_states())
    by_id = {n.id: n for n in reloaded}
    assert by_id["n1"].rev == 42
