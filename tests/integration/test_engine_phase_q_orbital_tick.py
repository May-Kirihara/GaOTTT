"""Phase Q Stage 2 — continuous orbital tick (engine._orbital_tick).

The tick advances displacement + velocity of the *lively* nodes (|v| >
orbital_lively_v_min) without a recall, leaving cold nodes and the
mass/temperature/last_access state untouched. See
docs/wiki/Plans-Phase-Q-Orbital-Mechanics.md §3.3.
"""
from __future__ import annotations

import hashlib

import numpy as np
import pytest

from gaottt.config import GaOTTTConfig
from gaottt.core.engine import GaOTTTEngine
from gaottt.index.faiss_index import FaissIndex
from gaottt.store.cache import CacheLayer
from gaottt.store.sqlite_store import SqliteStore


class StubEmbedder:
    """Deterministic token-based embeddings — no GPU/network."""

    def __init__(self, dim: int = 32):
        self.dim = dim

    def encode_documents(self, contents):
        return np.array([self._embed(c) for c in contents], dtype=np.float32)

    def encode_query(self, text):
        return self._embed(text).reshape(1, -1).astype(np.float32)

    def _embed(self, text: str) -> np.ndarray:
        seed = int.from_bytes(hashlib.md5(text.encode()).digest()[:8], "big")
        rng = np.random.default_rng(seed)
        v = rng.standard_normal(self.dim).astype(np.float32)
        v /= np.linalg.norm(v) + 1e-9
        return v


def _make_engine(tmp_path, **overrides):
    cfg_kwargs = dict(
        embedding_dim=32,
        data_dir=str(tmp_path),
        db_path=str(tmp_path / "test.db"),
        faiss_index_path=str(tmp_path / "test.faiss"),
        flush_interval_seconds=999.0,
        faiss_save_interval_seconds=0.0,
        virtual_faiss_save_interval_seconds=0.0,
        dream_enabled=False,            # we drive _orbital_tick manually
        dream_interval_seconds=999.0,   # background loop never fires in-test
    )
    cfg_kwargs.update(overrides)
    cfg = GaOTTTConfig(**cfg_kwargs)
    return GaOTTTEngine(
        config=cfg,
        embedder=StubEmbedder(dim=32),
        faiss_index=FaissIndex(dimension=32),
        cache=CacheLayer(flush_interval=999.0),
        store=SqliteStore(db_path=cfg.db_path),
    )


async def _index(engine, n):
    return await engine.index_documents([
        {"content": f"orbital tick node number {i} alpha beta",
         "metadata": {"source": "user"}}
        for i in range(n)
    ])


def _set_velocity(engine, nid, mag):
    dim = engine.config.embedding_dim
    v = np.zeros(dim, dtype=np.float32)
    v[0] = mag
    v[1] = mag  # 2-D so the harmonic motion is a plane, not a degenerate line
    engine.cache.set_velocity(nid, v)


@pytest.mark.asyncio
async def test_tick_moves_lively_leaves_cold(tmp_path):
    engine = _make_engine(
        tmp_path,
        orbital_tick_enabled=True,
        orbital_tangential_alpha=0.8,
        orbital_integrator="verlet",
        orbital_friction=0.005,
        orbital_lively_v_min=0.001,
    )
    await engine.startup()
    try:
        ids = await _index(engine, 4)
        # zero every displacement so we measure tick-induced motion only
        for nid in ids:
            engine.cache.set_displacement(
                nid, np.zeros(engine.config.embedding_dim, dtype=np.float32)
            )
        # three lively, one cold (below v_min)
        _set_velocity(engine, ids[0], 0.02)
        _set_velocity(engine, ids[1], 0.02)
        _set_velocity(engine, ids[2], 0.02)
        engine.cache.set_velocity(
            ids[3], np.zeros(engine.config.embedding_dim, dtype=np.float32)
        )

        before = {nid: engine.cache.get_displacement(nid).copy() for nid in ids}
        engine._orbital_tick()
        after = {nid: engine.cache.get_displacement(nid) for nid in ids}

        # lively nodes moved (their velocity integrated into displacement)
        for nid in ids[:3]:
            assert not np.allclose(before[nid], after[nid]), f"{nid} did not move"
        # cold node untouched — it was never in the active set
        assert np.allclose(before[ids[3]], after[ids[3]])
    finally:
        await engine.shutdown()


@pytest.mark.asyncio
async def test_tick_disabled_is_noop(tmp_path):
    engine = _make_engine(
        tmp_path,
        orbital_tick_enabled=False,   # gate off
        orbital_tangential_alpha=0.8,
    )
    await engine.startup()
    try:
        ids = await _index(engine, 3)
        for nid in ids:
            engine.cache.set_displacement(
                nid, np.zeros(engine.config.embedding_dim, dtype=np.float32)
            )
            _set_velocity(engine, nid, 0.02)
        before = {nid: engine.cache.get_displacement(nid).copy() for nid in ids}
        engine._orbital_tick()
        for nid in ids:
            assert np.allclose(before[nid], engine.cache.get_displacement(nid))
    finally:
        await engine.shutdown()


@pytest.mark.asyncio
async def test_tick_does_not_touch_mass_or_last_access(tmp_path):
    """The tick is free evolution, not a recall — mass / temperature /
    last_access must be left exactly as they were."""
    engine = _make_engine(
        tmp_path,
        orbital_tick_enabled=True,
        orbital_tangential_alpha=0.8,
        orbital_integrator="verlet",
    )
    await engine.startup()
    try:
        ids = await _index(engine, 3)
        for nid in ids:
            _set_velocity(engine, nid, 0.02)
        snap = {
            nid: (
                engine.cache.get_node(nid).mass,
                engine.cache.get_node(nid).last_access,
                engine.cache.get_node(nid).temperature,
            )
            for nid in ids
        }
        engine._orbital_tick()
        for nid in ids:
            st = engine.cache.get_node(nid)
            assert st.mass == snap[nid][0]
            assert st.last_access == snap[nid][1]
            assert st.temperature == snap[nid][2]
    finally:
        await engine.shutdown()


@pytest.mark.asyncio
async def test_tick_respects_max_nodes_cap(tmp_path, caplog):
    """More lively nodes than the cap → the tick logs the truncation
    (no silent coverage cap) and still completes."""
    import logging

    engine = _make_engine(
        tmp_path,
        orbital_tick_enabled=True,
        orbital_tangential_alpha=0.8,
        orbital_tick_max_nodes=3,
        orbital_lively_v_min=0.001,
    )
    await engine.startup()
    try:
        ids = await _index(engine, 6)
        for nid in ids:
            _set_velocity(engine, nid, 0.02)   # all 6 lively > cap 3
        with caplog.at_level(logging.INFO):
            engine._orbital_tick()
        assert any("orbital_tick" in r.message and "cap" in r.message
                   for r in caplog.records)
    finally:
        await engine.shutdown()


@pytest.mark.asyncio
async def test_tick_neighbor_gravity_off_by_default(tmp_path):
    """Rollout fix (2026-05-30): by default the continuous tick runs a PURE
    self-anchor orbit — it does NOT couple the lively set via mutual neighbor
    gravity. On the real field that mutual gravity sums coherently and slams
    displacement to the clamp, so the default tick zeroes gravity_G internally;
    ``orbital_tick_neighbor_gravity_enabled=True`` restores the coupled path.

    Two close, heavy, lively nodes (same content → same deterministic anchor in
    both engines) are stepped once with the flag OFF vs ON. The flag-ON result
    must differ (neighbor gravity is wired and active), while the flag-OFF
    result stays finite and clamp-bounded (pure self-anchor)."""

    async def _step_once(flag: bool, sub: str):
        d = tmp_path / sub
        d.mkdir()
        engine = _make_engine(
            tmp_path,
            data_dir=str(d),
            db_path=str(d / "t.db"),
            faiss_index_path=str(d / "t.faiss"),
            genesis_kick_enabled=False,          # control the seed exactly
            orbital_tick_enabled=True,
            orbital_tick_neighbor_gravity_enabled=flag,
            orbital_integrator="verlet",
            orbital_anchor_strength=0.02,
            orbital_max_velocity=0.05,
            max_displacement_norm=2.0,
            orbital_lively_v_min=0.001,
        )
        await engine.startup()
        try:
            ids = await _index(engine, 2)        # content #0, #1 → same in both
            dim = engine.config.embedding_dim
            for nid in ids:
                disp = np.zeros(dim, dtype=np.float32)
                disp[0] = 0.3                     # off-anchor so neighbor gravity ≠ 0
                engine.cache.set_displacement(nid, disp)
                _set_velocity(engine, nid, 0.02)
                st = engine.cache.get_node(nid)
                st.mass = 5.0                     # amplify neighbor gravity
                engine.cache.set_node(st, dirty=True)
            engine._orbital_tick()
            return engine.cache.get_displacement(ids[0]).copy()
        finally:
            await engine.shutdown()

    d_off = await _step_once(False, "off")
    d_on = await _step_once(True, "on")

    # Flag is wired: enabling neighbor gravity changes node #0's one-tick result.
    assert not np.allclose(d_off, d_on), (
        "orbital_tick_neighbor_gravity_enabled had no effect — the tick is not "
        "honouring the flag (neighbor gravity not toggled)"
    )
    # Default (OFF) path stays finite and clamp-bounded (pure self-anchor).
    assert np.all(np.isfinite(d_off))
    assert float(np.linalg.norm(d_off)) <= 2.0 + 1e-6
