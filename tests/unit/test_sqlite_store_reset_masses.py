"""Phase M Stage 1 — ``SqliteStore.reset_masses`` + ``reset_orbital_state``
unit tests.

Verifies the SQL update changes only the targeted columns and reports the
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


async def test_reset_orbital_state_clears_displacement_and_velocity(store):
    import numpy as np

    await _seed(store, "n1", mass=1.0)
    await _seed(store, "n2", mass=1.0)

    # Populate displacement + velocity for both nodes.
    d1 = np.full(8, 0.1, dtype=np.float32)
    d2 = np.full(8, 0.2, dtype=np.float32)
    v1 = np.full(8, 0.01, dtype=np.float32)
    v2 = np.full(8, 0.02, dtype=np.float32)
    await store.save_displacements({"n1": d1, "n2": d2})
    await store.save_velocities({"n1": v1, "n2": v2})

    affected = await store.reset_orbital_state()
    assert affected == 2

    disps = await store.load_displacements()
    vels = await store.load_velocities()
    assert disps == {}, f"expected all displacements cleared, got keys {list(disps)}"
    assert vels == {}, f"expected all velocities cleared, got keys {list(vels)}"

    # Mass + metadata stay intact.
    states = await store.get_node_states(["n1", "n2"])
    assert states["n1"].mass == pytest.approx(1.0)
    assert states["n2"].mass == pytest.approx(1.0)


async def test_reset_orbital_state_idempotent_on_empty_columns(store):
    await _seed(store, "n1", mass=2.0)
    # No displacement/velocity ever written.
    affected = await store.reset_orbital_state()
    assert affected == 1

    # Mass not touched.
    states = await store.get_node_states(["n1"])
    assert states["n1"].mass == pytest.approx(2.0)


async def test_reset_orbital_state_does_not_affect_edges(store):
    import time

    from gaottt.core.types import CooccurrenceEdge

    await _seed(store, "n1", mass=1.0)
    await _seed(store, "n2", mass=1.0)
    await store.save_edges([
        CooccurrenceEdge(src="n1", dst="n2", weight=3.0, last_update=time.time()),
    ])

    await store.reset_orbital_state()

    edges = await store.get_all_edges()
    assert len(edges) == 1
    assert edges[0].weight == pytest.approx(3.0)


async def test_reset_velocities_clears_velocity_keeps_displacement(store):
    """Phase Q2 — ``reset_velocities`` zeroes velocity but PRESERVES
    displacement (unlike ``reset_orbital_state`` which wipes both)."""
    import numpy as np

    await _seed(store, "n1", mass=1.0)
    await _seed(store, "n2", mass=1.0)
    d1 = np.full(8, 0.1, dtype=np.float32)
    d2 = np.full(8, 0.2, dtype=np.float32)
    v1 = np.full(8, 0.01, dtype=np.float32)
    v2 = np.full(8, 0.02, dtype=np.float32)
    await store.save_displacements({"n1": d1, "n2": d2})
    await store.save_velocities({"n1": v1, "n2": v2})

    affected = await store.reset_velocities()
    assert affected == 2

    vels = await store.load_velocities()
    disps = await store.load_displacements()
    assert vels == {}, f"expected all velocities cleared, got keys {list(vels)}"
    # displacement is the learned positions — must survive the cooldown
    assert set(disps) == {"n1", "n2"}
    assert np.allclose(disps["n1"], d1)
    assert np.allclose(disps["n2"], d2)

    states = await store.get_node_states(["n1", "n2"])
    assert states["n1"].mass == pytest.approx(1.0)
    assert states["n2"].mass == pytest.approx(1.0)


async def test_reset_velocities_idempotent_on_empty_column(store):
    await _seed(store, "n1", mass=2.0)
    affected = await store.reset_velocities()
    assert affected == 1


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
