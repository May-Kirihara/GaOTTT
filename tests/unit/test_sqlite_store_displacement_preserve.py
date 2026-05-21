"""Regression: save_node_states must NOT wipe displacement / velocity.

Guards the Hardening Stage 1 / C1 fix. `save_node_states` historically used
`INSERT OR REPLACE`, which on a PRIMARY KEY conflict is DELETE-then-INSERT and
therefore reset every column absent from `_NODE_COLS` (displacement / velocity,
persisted separately) back to NULL. A node flushed for a non-displacement
reason (mass / last_access touch) silently lost its accumulated orbital
position on the next load — destroying the Phase I/J/K query-attraction field.
"""
from __future__ import annotations

import time

import numpy as np
import pytest

from gaottt.core.types import NodeState
from gaottt.store.sqlite_store import SqliteStore


@pytest.fixture
async def store(tmp_path):
    s = SqliteStore(db_path=str(tmp_path / "ger.db"))
    await s.initialize()
    yield s
    await s.close()


async def test_node_state_flush_preserves_displacement_and_velocity(store):
    disp = np.arange(8, dtype=np.float32) * 0.1
    vel = np.arange(8, dtype=np.float32) * -0.2

    await store.save_documents([{"id": "n1", "content": "c", "metadata": None}])
    await store.save_node_states([NodeState(id="n1", mass=1.0, last_access=time.time())])
    await store.save_displacements({"n1": disp})
    await store.save_velocities({"n1": vel})

    # Node becomes dirty for a NON-displacement reason (mass changed by a
    # recall touch). The write-behind loop flushes save_node_states alone,
    # WITHOUT save_displacements/save_velocities (dirty sets are independent).
    await store.save_node_states([NodeState(id="n1", mass=5.0, last_access=time.time())])

    loaded_disp = await store.load_displacements(["n1"])
    loaded_vel = await store.load_velocities(["n1"])

    assert "n1" in loaded_disp, "displacement was wiped by save_node_states (C1 regression)"
    np.testing.assert_array_equal(loaded_disp["n1"], disp)
    assert "n1" in loaded_vel, "velocity was wiped by save_node_states (C1 regression)"
    np.testing.assert_array_equal(loaded_vel["n1"], vel)

    # The non-displacement column update must still have taken effect (the
    # upsert's DO UPDATE branch), proving we preserved AND updated correctly.
    states = await store.get_node_states(["n1"])
    assert states["n1"].mass == pytest.approx(5.0)


async def test_fresh_insert_has_null_displacement(store):
    """A brand-new node has no displacement yet — upsert INSERT path leaves it
    NULL (set later by save_displacements), unchanged from prior behaviour."""
    await store.save_documents([{"id": "fresh", "content": "c", "metadata": None}])
    await store.save_node_states([NodeState(id="fresh", mass=1.0, last_access=time.time())])

    assert await store.load_displacements(["fresh"]) == {}
    states = await store.get_node_states(["fresh"])
    assert states["fresh"].mass == pytest.approx(1.0)
