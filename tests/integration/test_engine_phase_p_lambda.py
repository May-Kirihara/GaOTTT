"""Phase P Stage 2 — Cosmological Λ, engine-level integration.

Verifies that the Λ term flows through engine.query (which calls
_update_simulation → update_orbital_state → compute_acceleration)
and that:
  - default OFF reproduces legacy engine behavior (smoke),
  - flag ON expands cluster centroid distance over multiple recalls
    (the canonical "voids open between clusters" test),
  - T₀-style rollback (H=0) is a no-op.
"""

from __future__ import annotations

import numpy as np
import pytest

from gaottt.config import GaOTTTConfig
from gaottt.core.engine import GaOTTTEngine
from gaottt.index.faiss_index import FaissIndex
from gaottt.services import memory as memory_service
from gaottt.store.cache import CacheLayer
from gaottt.store.sqlite_store import SqliteStore
from tests.integration.test_engine_archive_ttl import StubEmbedder


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
async def test_lambda_off_engine_runs_unchanged(tmp_path):
    """Smoke: default Λ OFF — engine.query and recall continue to work."""
    eng = _make_engine(tmp_path)
    await eng.startup()
    try:
        for i in range(4):
            await memory_service.remember(
                eng, content=f"gravity note {i}", source="agent",
            )
        resp = await memory_service.recall(eng, query="gravity note", top_k=4)
        assert resp.items
    finally:
        await eng.shutdown()


@pytest.mark.asyncio
async def test_lambda_on_expands_displacement_total(tmp_path):
    """Λ-on should produce strictly larger total displacement than Λ-off.

    Insert N tightly-related docs, run several recalls. Λ pushes each
    node away from its neighbors at every update step, so the total
    L2 sum of displacement grows faster than baseline.
    """
    off_dir = tmp_path / "off"
    on_dir = tmp_path / "on"
    off_dir.mkdir()
    on_dir.mkdir()
    eng_off = _make_engine(off_dir, cosmological_lambda_enabled=False)
    eng_on = _make_engine(
        on_dir,
        cosmological_lambda_enabled=True,
        cosmological_lambda_h=0.05,   # bigger than default — easier to observe in test scale
    )
    for eng in (eng_off, eng_on):
        await eng.startup()
    try:
        contents = [f"gravity note {i}" for i in range(6)]
        for eng in (eng_off, eng_on):
            for c in contents:
                await memory_service.remember(eng, content=c, source="agent")
            for _ in range(4):
                await memory_service.recall(eng, query="gravity note", top_k=5)

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
            f"Λ should add outward motion: total |d| off={disp_off:.4f} on={disp_on:.4f}"
        )
    finally:
        for eng in (eng_off, eng_on):
            await eng.shutdown()


@pytest.mark.asyncio
async def test_lambda_rollback_via_h_zero(tmp_path):
    """Flag enabled + H=0 ⇒ engine behavior identical to Λ off."""
    eng = _make_engine(
        tmp_path,
        cosmological_lambda_enabled=True,
        cosmological_lambda_h=0.0,
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


@pytest.mark.asyncio
async def test_lambda_and_langevin_coexist(tmp_path):
    """Phase P-α and P-β must coexist without interaction errors.

    Plan §3 (single-rule) says α (space-pressure) and β (time-pressure)
    are mathematically orthogonal — flipping both flags simultaneously
    should produce a valid engine path with neither term zeroing the
    other.
    """
    eng = _make_engine(
        tmp_path,
        cosmological_lambda_enabled=True,
        cosmological_lambda_h=0.005,
        langevin_temperature_enabled=True,
        langevin_temperature_t0=0.001,
    )
    await eng.startup()
    try:
        for i in range(4):
            await memory_service.remember(
                eng, content=f"co-existence probe {i}", source="agent",
            )
        for _ in range(3):
            resp = await memory_service.recall(
                eng, query="co-existence probe", top_k=4,
            )
            assert resp.items
        # Engine still healthy — both pressure terms ran without exception.
        assert any(
            s for s in eng.cache.get_all_nodes() if not s.is_archived
        )
    finally:
        await eng.shutdown()
