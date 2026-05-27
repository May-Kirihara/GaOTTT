"""Hardening Stage 3 第一弾 — M3 / M4 / M6 の teeth-having 回帰テスト.

各 fix が **修正前なら落ちる** test を持つことが Stage 1/2 で確立した
規律 (`Plans-Hardening-Concurrency-Persistence.md`)。本ファイルはその規律に
従って M3 (transaction), M4 (dtype guard), M6 (friction clamp) に teeth を
入れる。
"""

from __future__ import annotations

import sqlite3

import numpy as np
import pytest

from gaottt.config import GaOTTTConfig
from gaottt.core.gravity import update_velocity
from gaottt.store.sqlite_store import SqliteStore


# ----- M3 — multi-statement destructive op rolls back on partial failure -----


@pytest.mark.asyncio
async def test_m3_reset_dynamic_state_rolls_back_on_mid_sequence_failure(tmp_path):
    """If the DELETE FROM edges statement raises, the prior UPDATE on nodes
    (mass=1.0 reset) must roll back too — without the M3 try/rollback this
    test would observe partial application (mass reset but edges intact).
    """
    store = SqliteStore(db_path=str(tmp_path / "test.db"))
    await store.initialize()
    # Seed a node with non-default mass and an edge.
    await store._conn.execute(
        "INSERT INTO nodes (id, mass) VALUES (?, ?)", ("n0", 3.14)
    )
    await store._conn.execute(
        "INSERT INTO nodes (id, mass) VALUES (?, ?)", ("n1", 2.72)
    )
    await store._conn.execute(
        "INSERT INTO edges (src, dst, weight) VALUES (?, ?, ?)",
        ("n0", "n1", 5.0),
    )
    await store._conn.commit()

    # Wrap execute so that the 2nd destructive statement (DELETE FROM edges)
    # raises after the 1st (UPDATE nodes ... mass = 1.0) succeeds.
    original_execute = store._conn.execute

    async def faulty_execute(sql, *args, **kwargs):
        s = sql.strip().upper()
        if s.startswith("DELETE FROM EDGES"):
            raise sqlite3.OperationalError("simulated mid-sequence failure")
        return await original_execute(sql, *args, **kwargs)

    store._conn.execute = faulty_execute  # type: ignore[assignment]
    try:
        with pytest.raises(sqlite3.OperationalError, match="simulated"):
            await store.reset_dynamic_state()
    finally:
        store._conn.execute = original_execute  # type: ignore[assignment]

    # Teeth: the UPDATE on nodes mass=1.0 must have been rolled back.
    cursor = await store._conn.execute(
        "SELECT id, mass FROM nodes ORDER BY id"
    )
    rows = await cursor.fetchall()
    assert rows == [("n0", 3.14), ("n1", 2.72)], (
        f"M3 rollback failed: expected original mass, got {rows}"
    )


@pytest.mark.asyncio
async def test_m3_hard_delete_nodes_rolls_back_on_mid_sequence_failure(tmp_path):
    """If DELETE FROM nodes raises after DELETE FROM edges succeeded,
    the edge deletion must roll back too — otherwise we'd have dangling
    state where edges are gone but their endpoints survived.
    """
    store = SqliteStore(db_path=str(tmp_path / "test.db"))
    await store.initialize()
    await store._conn.execute("INSERT INTO nodes (id, mass) VALUES (?, ?)", ("a", 1.0))
    await store._conn.execute("INSERT INTO nodes (id, mass) VALUES (?, ?)", ("b", 1.0))
    await store._conn.execute(
        "INSERT INTO edges (src, dst, weight) VALUES (?, ?, ?)", ("a", "b", 7.0)
    )
    await store._conn.commit()

    original_execute = store._conn.execute

    async def faulty_execute(sql, *args, **kwargs):
        s = sql.strip().upper()
        if s.startswith("DELETE FROM NODES"):
            raise sqlite3.OperationalError("simulated mid-sequence failure")
        return await original_execute(sql, *args, **kwargs)

    store._conn.execute = faulty_execute  # type: ignore[assignment]
    try:
        with pytest.raises(sqlite3.OperationalError, match="simulated"):
            await store.hard_delete_nodes(["a"])
    finally:
        store._conn.execute = original_execute  # type: ignore[assignment]

    # Teeth: the prior DELETE FROM edges should have been rolled back, so
    # the edge between a and b is still present.
    cursor = await store._conn.execute("SELECT COUNT(*) FROM edges")
    row = await cursor.fetchone()
    assert row[0] == 1, f"M3 rollback failed: edge was not restored, got {row[0]}"


# ----- M4 — dtype guard on save_displacements / save_velocities -------------


@pytest.mark.asyncio
async def test_m4_save_displacements_coerces_float64_to_float32(tmp_path):
    """Pre-M4: caller passes float64 displacement → ``disp.tobytes()`` writes
    2× the byte width, and ``load_displacements`` reads back as float32
    interpreting consecutive 4-byte chunks as separate floats → garbage.

    Post-M4: ``np.ascontiguousarray(disp, dtype=np.float32)`` coerces
    before serialization, so round-trip is value-preserving.
    """
    store = SqliteStore(db_path=str(tmp_path / "test.db"))
    await store.initialize()
    await store._conn.execute("INSERT INTO nodes (id, mass) VALUES (?, ?)", ("n0", 1.0))
    await store._conn.commit()

    # Caller mistake: float64 (numpy default for arithmetic outside the
    # ``.astype(np.float32)`` discipline).
    disp_f64 = np.linspace(0.0, 1.0, num=8, dtype=np.float64)
    await store.save_displacements({"n0": disp_f64})

    # Round-trip via load_displacements (uses dtype=np.float32 frombuffer).
    loaded = await store.load_displacements(["n0"])
    assert "n0" in loaded
    expected = disp_f64.astype(np.float32)
    np.testing.assert_allclose(loaded["n0"], expected, atol=1e-7), (
        "M4 dtype guard failed: float64 → float32 round-trip produced wrong values"
    )


@pytest.mark.asyncio
async def test_m4_save_velocities_coerces_float64_to_float32(tmp_path):
    """Same guard mirrored on save_velocities."""
    store = SqliteStore(db_path=str(tmp_path / "test.db"))
    await store.initialize()
    await store._conn.execute("INSERT INTO nodes (id, mass) VALUES (?, ?)", ("n0", 1.0))
    await store._conn.commit()

    vel_f64 = np.linspace(-1.0, 1.0, num=8, dtype=np.float64)
    await store.save_velocities({"n0": vel_f64})

    loaded = await store.load_velocities(["n0"])
    assert "n0" in loaded
    expected = vel_f64.astype(np.float32)
    np.testing.assert_allclose(loaded["n0"], expected, atol=1e-7)


@pytest.mark.asyncio
async def test_m4_save_displacements_accepts_non_contiguous_view(tmp_path):
    """A slice / transpose produces a non-contiguous view; tobytes() on it
    would still serialize element-by-element, but contiguity-check guards
    against future code that uses a method assuming contiguous buffers.
    """
    store = SqliteStore(db_path=str(tmp_path / "test.db"))
    await store.initialize()
    await store._conn.execute("INSERT INTO nodes (id, mass) VALUES (?, ?)", ("n0", 1.0))
    await store._conn.commit()

    base = np.arange(16, dtype=np.float32).reshape(2, 8)
    non_contig = base[::2, :].flatten()  # not necessarily contiguous
    await store.save_displacements({"n0": non_contig})
    loaded = await store.load_displacements(["n0"])
    np.testing.assert_allclose(loaded["n0"], non_contig.astype(np.float32))


# ----- M6 — friction clamp prevents velocity inversion ----------------------


def _cfg_with_friction(friction: float) -> GaOTTTConfig:
    return GaOTTTConfig(
        embedding_dim=4,
        orbital_friction=friction,
        orbital_friction_age_factor=0.0,
        displacement_age_delta=0.0,
        orbital_max_velocity=100.0,  # disable clamp so we observe the raw factor
    )


def test_m6_friction_above_one_does_not_invert_velocity():
    """Pre-M6: ``orbital_friction=1.5`` → ``v *= (1 - 1.5) = -0.5`` flips sign.
    Post-M6: the keep factor is clamped to ``max(0, 1-friction) = 0`` so
    velocity decays to zero instead of inverting.
    """
    cfg = _cfg_with_friction(friction=1.5)
    v0 = np.array([1.0, 1.0, 1.0, 1.0], dtype=np.float32)
    a = np.zeros(4, dtype=np.float32)
    v1 = update_velocity(v0, a, last_access=0.0, now=0.0, config=cfg)
    # Each component must NOT have flipped sign — pre-M6 it would be -0.5.
    assert all(v1[i] >= 0.0 for i in range(4)), (
        f"M6 clamp failed: velocity inverted to {v1.tolist()}"
    )
    # And under the M6 clamp (friction=1.5 → keep=0) it should be exactly 0.
    np.testing.assert_allclose(v1, np.zeros(4, dtype=np.float32), atol=1e-7)


def test_m6_friction_negative_does_not_amplify():
    """Negative friction would amplify (``v *= 1 - (-0.5) = 1.5``) — a
    self-destructive runaway. M6 clamp keeps it at ``min(1, 1-friction)=1.0``
    so velocity is preserved but never amplified.
    """
    cfg = _cfg_with_friction(friction=-0.5)
    v0 = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)
    a = np.zeros(4, dtype=np.float32)
    v1 = update_velocity(v0, a, last_access=0.0, now=0.0, config=cfg)
    # Without the upper clamp, |v1| would be 1.5. With M6, it stays at 1.0.
    assert float(np.linalg.norm(v1)) <= 1.0 + 1e-6, (
        f"M6 upper clamp failed: |v|={float(np.linalg.norm(v1))} exceeds 1.0"
    )


def test_m6_friction_in_range_unchanged():
    """Sanity: in-range friction (e.g., default 0.05) produces the same
    multiplication as before the clamp was added — no regression on the
    happy path.
    """
    cfg = _cfg_with_friction(friction=0.05)
    v0 = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)
    a = np.zeros(4, dtype=np.float32)
    v1 = update_velocity(v0, a, last_access=0.0, now=0.0, config=cfg)
    np.testing.assert_allclose(v1, np.array([0.95, 0, 0, 0], dtype=np.float32), atol=1e-6)
