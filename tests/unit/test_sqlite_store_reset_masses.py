"""Phase M Stage 1 — ``SqliteStore.reset_masses`` unit tests.

Verifies the SQL update changes only the ``mass`` column and reports the
correct row count, leaving displacement / velocity / edges / metadata
intact (those are inspected in the integration suite).
"""
from __future__ import annotations

import time

import pytest

from gaottt.core.types import NodeState
from gaottt.store.sqlite_store import SqliteStore


@pytest.fixture
async def store(tmp_path):
    s = SqliteStore(db_path=str(tmp_path / "gaottt.db"))
    await s.initialize()
    yield s
    await s.close()


async def _seed(store: SqliteStore, node_id: str, mass: float) -> None:
    await store.save_documents(
        [{"id": node_id, "content": f"c {node_id}", "metadata": None}]
    )
    await store.save_node_states(
        [NodeState(id=node_id, mass=mass, last_access=time.time())]
    )


async def test_reset_masses_sets_default_and_returns_count(store):
    await _seed(store, "a", mass=10.5)
    await _seed(store, "b", mass=42.0)
    await _seed(store, "c", mass=0.7)

    affected = await store.reset_masses()  # default value=1.0
    assert affected == 3

    states = await store.get_node_states(["a", "b", "c"])
    assert states["a"].mass == pytest.approx(1.0)
    assert states["b"].mass == pytest.approx(1.0)
    assert states["c"].mass == pytest.approx(1.0)


async def test_reset_masses_honors_explicit_value(store):
    await _seed(store, "x", mass=5.0)
    await _seed(store, "y", mass=12.0)

    affected = await store.reset_masses(value=2.5)
    assert affected == 2

    states = await store.get_node_states(["x", "y"])
    assert states["x"].mass == pytest.approx(2.5)
    assert states["y"].mass == pytest.approx(2.5)


async def test_reset_masses_on_empty_db_returns_zero(store):
    affected = await store.reset_masses()
    assert affected == 0


async def test_reset_masses_leaves_other_columns_intact(store):
    # Set non-trivial values on every non-mass column so we can confirm
    # the UPDATE statement targets only ``mass``.
    state = NodeState(
        id="n1",
        mass=33.0,
        temperature=7.7,
        last_access=1700000000.0,
        return_count=4.0,
        emotion_weight=0.4,
        certainty=0.8,
    )
    await store.save_documents([{"id": "n1", "content": "c", "metadata": None}])
    await store.save_node_states([state])

    affected = await store.reset_masses()
    assert affected == 1

    loaded = (await store.get_node_states(["n1"]))["n1"]
    assert loaded.mass == pytest.approx(1.0)
    assert loaded.temperature == pytest.approx(7.7)
    assert loaded.last_access == pytest.approx(1700000000.0)
    assert loaded.return_count == pytest.approx(4.0)
    assert loaded.emotion_weight == pytest.approx(0.4)
    assert loaded.certainty == pytest.approx(0.8)
