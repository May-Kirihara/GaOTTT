"""Phase M follow-up — warm displacement from velocity.

Covers both the engine method and the REST `/admin/warm_displacement`
endpoint. The migration step (M005) reuses the same engine method, so
exercising it here is sufficient for that path.
"""
from __future__ import annotations

import numpy as np
import pytest
from httpx import ASGITransport, AsyncClient

from gaottt.config import GaOTTTConfig
from gaottt.core.engine import GaOTTTEngine
from gaottt.index.faiss_index import FaissIndex
from gaottt.server.app import app
from gaottt.store.cache import CacheLayer
from gaottt.store.sqlite_store import SqliteStore
from tests.integration.test_engine_archive_ttl import StubEmbedder


async def _make_engine(tmp_path):
    cfg = GaOTTTConfig(
        embedding_dim=32,
        data_dir=str(tmp_path),
        db_path=str(tmp_path / "warm.db"),
        faiss_index_path=str(tmp_path / "warm.faiss"),
        flush_interval_seconds=999.0,
        faiss_save_interval_seconds=0.0,
        dream_enabled=False,
        genesis_kick_enabled=False,
        supernova_enabled=False,
    )
    eng = GaOTTTEngine(
        config=cfg,
        embedder=StubEmbedder(dimension=32),
        faiss_index=FaissIndex(dimension=32),
        cache=CacheLayer(flush_interval=999.0),
        store=SqliteStore(db_path=cfg.db_path),
    )
    await eng.startup()
    return eng


async def test_warm_seeds_velocity_only_nodes(tmp_path):
    eng = await _make_engine(tmp_path)
    try:
        ids = await eng.index_documents([
            {"content": f"node-{i}", "metadata": {"source": "agent"}}
            for i in range(5)
        ])
        # Simulate the M004 condition: velocity set, displacement absent.
        seed_v = np.full(32, 0.01, dtype=np.float32)
        for nid in ids:
            eng.cache.set_velocity(nid, seed_v.copy())
        # One node already has displacement — must be preserved by default.
        preserved_v = ids[0]
        preserved_disp = np.full(32, 0.5, dtype=np.float32)
        eng.cache.set_displacement(preserved_v, preserved_disp.copy())

        stats = await eng.warm_displacement(overwrite=False)
        assert stats["active_total"] == 5
        assert stats["seeded"] == 4
        assert stats["skipped_already_displaced"] == 1
        assert stats["skipped_no_velocity"] == 0

        for nid in ids[1:]:
            d = eng.cache.get_displacement(nid)
            assert d is not None
            assert np.allclose(d, seed_v)
        # Preserved untouched.
        assert np.allclose(eng.cache.get_displacement(preserved_v), preserved_disp)
    finally:
        await eng.shutdown()


async def test_warm_skips_when_velocity_absent(tmp_path):
    eng = await _make_engine(tmp_path)
    try:
        ids = await eng.index_documents([
            {"content": f"calm-{i}", "metadata": {"source": "agent"}}
            for i in range(3)
        ])
        # No velocity, no displacement → nothing to seed.
        stats = await eng.warm_displacement(overwrite=False)
        assert stats["seeded"] == 0
        assert stats["skipped_no_velocity"] == 3
        for nid in ids:
            assert eng.cache.get_displacement(nid) is None
    finally:
        await eng.shutdown()


async def test_warm_overwrite_replaces_existing_displacement(tmp_path):
    eng = await _make_engine(tmp_path)
    try:
        ids = await eng.index_documents([
            {"content": f"overwrite-{i}", "metadata": {"source": "agent"}}
            for i in range(2)
        ])
        seed_v = np.full(32, 0.02, dtype=np.float32)
        old_disp = np.full(32, 0.3, dtype=np.float32)
        for nid in ids:
            eng.cache.set_velocity(nid, seed_v.copy())
            eng.cache.set_displacement(nid, old_disp.copy())

        stats = await eng.warm_displacement(overwrite=True)
        assert stats["seeded"] == 2
        assert stats["skipped_already_displaced"] == 0
        for nid in ids:
            assert np.allclose(eng.cache.get_displacement(nid), seed_v)
    finally:
        await eng.shutdown()


async def test_warm_is_idempotent(tmp_path):
    eng = await _make_engine(tmp_path)
    try:
        ids = await eng.index_documents([
            {"content": f"idempotent-{i}", "metadata": {"source": "agent"}}
            for i in range(3)
        ])
        seed_v = np.full(32, 0.05, dtype=np.float32)
        for nid in ids:
            eng.cache.set_velocity(nid, seed_v.copy())

        first = await eng.warm_displacement(overwrite=False)
        second = await eng.warm_displacement(overwrite=False)
        assert first["seeded"] == 3
        # Already-displaced now — second call is a no-op write.
        assert second["seeded"] == 0
        assert second["skipped_already_displaced"] == 3
    finally:
        await eng.shutdown()


@pytest.fixture
async def rest_client_warm(tmp_path):
    eng = await _make_engine(tmp_path)
    app.state.engine = eng
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, eng
    await eng.shutdown()


async def test_rest_warm_displacement_round_trip(rest_client_warm):
    client, eng = rest_client_warm
    ids = await eng.index_documents([
        {"content": f"rest-warm-{i}", "metadata": {"source": "agent"}}
        for i in range(4)
    ])
    seed_v = np.full(32, 0.03, dtype=np.float32)
    for nid in ids:
        eng.cache.set_velocity(nid, seed_v.copy())

    resp = await client.post("/admin/warm_displacement", json={})
    assert resp.status_code == 200
    data = resp.json()
    assert data["seeded"] == 4
    assert data["active_total"] == 4
    assert data["skipped_no_velocity"] == 0
    assert data["skipped_already_displaced"] == 0


async def test_rest_warm_displacement_overwrite(rest_client_warm):
    client, eng = rest_client_warm
    ids = await eng.index_documents([
        {"content": f"rest-ow-{i}", "metadata": {"source": "agent"}}
        for i in range(2)
    ])
    seed_v = np.full(32, 0.04, dtype=np.float32)
    old_disp = np.full(32, 0.2, dtype=np.float32)
    for nid in ids:
        eng.cache.set_velocity(nid, seed_v.copy())
        eng.cache.set_displacement(nid, old_disp.copy())

    default = await client.post("/admin/warm_displacement", json={})
    assert default.json()["seeded"] == 0
    assert default.json()["skipped_already_displaced"] == 2

    forced = await client.post(
        "/admin/warm_displacement", json={"overwrite": True},
    )
    assert forced.json()["seeded"] == 2
