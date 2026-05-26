"""Phase P Stage 1 — Langevin Temperature, engine-level integration.

End-to-end coverage that the Langevin term flows through engine.query
(which calls _update_simulation → update_orbital_state) without breaking
anything, and that displacement variance is larger when the term is on
than when it is off — the canonical "wells get jiggled" test.
"""

from __future__ import annotations

import numpy as np
import pytest

from gaottt.services import memory as memory_service
from tests.integration.test_engine_archive_ttl import StubEmbedder
from gaottt.config import GaOTTTConfig
from gaottt.core.engine import GaOTTTEngine
from gaottt.index.faiss_index import FaissIndex
from gaottt.store.cache import CacheLayer
from gaottt.store.sqlite_store import SqliteStore


def _make_engine(tmp_path, **overrides):
    base = dict(
        embedding_dim=32,
        data_dir=str(tmp_path),
        db_path=str(tmp_path / "test.db"),
        faiss_index_path=str(tmp_path / "test.faiss"),
        flush_interval_seconds=999.0,
        wave_initial_k=3,
        wave_max_depth=1,
        genesis_kick_enabled=False,
        dream_enabled=False,
    )
    base.update(overrides)
    cfg = GaOTTTConfig(**base)
    return GaOTTTEngine(
        config=cfg,
        embedder=StubEmbedder(dimension=32),
        faiss_index=FaissIndex(dimension=32),
        cache=CacheLayer(flush_interval=999.0),
        store=SqliteStore(db_path=cfg.db_path),
    )


@pytest.mark.asyncio
async def test_langevin_off_engine_runs_unchanged(tmp_path):
    """Default (Langevin OFF) — engine.query and remember work normally.

    Smoke check: Stage 1 default OFF must not regress any existing engine path.
    """
    eng = _make_engine(tmp_path)
    await eng.startup()
    try:
        for i in range(4):
            await memory_service.remember(
                eng, content=f"gravity wave note {i}", source="agent",
            )
        resp = await memory_service.recall(eng, query="gravity wave", top_k=4)
        assert resp.items, "engine should still return hits with Langevin off"
    finally:
        await eng.shutdown()


@pytest.mark.asyncio
async def test_langevin_on_increases_displacement_variance(tmp_path):
    """With Langevin on (T₀=0.01) displacement spreads further than baseline.

    Insert N nodes, run a handful of recalls to trigger _update_simulation,
    then compare per-node displacement norms between the OFF and ON engines.
    The ON path should produce displacement of strictly larger total L2 sum
    (thermal noise is a source of additional motion).
    """
    # Baseline engine (Langevin OFF)
    off_dir = tmp_path / "off"
    on_dir = tmp_path / "on"
    off_dir.mkdir()
    on_dir.mkdir()
    eng_off = _make_engine(off_dir, langevin_temperature_enabled=False)
    eng_on = _make_engine(
        on_dir,
        langevin_temperature_enabled=True,
        langevin_temperature_t0=0.01,
    )
    for eng in (eng_off, eng_on):
        await eng.startup()
    try:
        contents = [f"gravity wave note {i}" for i in range(6)]
        for eng in (eng_off, eng_on):
            for c in contents:
                await memory_service.remember(eng, content=c, source="agent")
            # A few recalls to drive _update_simulation
            for _ in range(3):
                await memory_service.recall(eng, query="gravity wave", top_k=4)

        def total_disp(eng):
            total = 0.0
            for nid in [s.id for s in eng.cache.get_all_nodes()]:
                disp = eng.cache.get_displacement(nid)
                if disp is not None:
                    total += float(np.linalg.norm(disp))
            return total

        disp_off = total_disp(eng_off)
        disp_on = total_disp(eng_on)
        assert disp_on > disp_off, (
            f"Langevin should add motion: total |d| off={disp_off:.3f} on={disp_on:.3f}"
        )
    finally:
        for eng in (eng_off, eng_on):
            await eng.shutdown()


@pytest.mark.asyncio
async def test_langevin_rollback_via_t0_zero(tmp_path):
    """Setting T₀=0 with flag on must behave like flag off (no noise)."""
    eng = _make_engine(
        tmp_path,
        langevin_temperature_enabled=True,
        langevin_temperature_t0=0.0,
    )
    await eng.startup()
    try:
        for i in range(3):
            await memory_service.remember(
                eng, content=f"alpha beta gamma {i}", source="agent",
            )
        resp = await memory_service.recall(eng, query="alpha beta", top_k=3)
        assert resp.items
    finally:
        await eng.shutdown()
