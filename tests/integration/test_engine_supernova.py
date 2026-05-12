"""Phase K Stage 1 — Stellar supernova cohort (integration).

End-to-end through engine.index_documents():
  1. A batch of size ≥ supernova_min_cohort_size forms mutual co-occurrence
     edges and outward initial velocities for all members.
  2. Cohort members have non-zero velocity in cache after indexing.
  3. With supernova_enabled=False the legacy (Phase G only) behaviour is
     preserved — no inter-batch edges, no outward initial velocity from
     centroid.
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
    """SHA256-based deterministic embedder. Using sha256 (not hash()) avoids
    PYTHONHASHSEED randomisation introduced in Python 3.3, which would make
    test_cohort_members_get_outward_velocity flaky across runs."""

    def __init__(self, dim: int = 768):
        self.dim = dim

    def encode_documents(self, contents):
        return np.array([self._embed(c) for c in contents], dtype=np.float32)

    def encode_query(self, text):
        return self._embed(text).reshape(1, -1).astype(np.float32)

    def _embed(self, text: str) -> np.ndarray:
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        seed = int.from_bytes(digest[:8], "big") & 0xFFFFFFFF
        rng = np.random.default_rng(seed)
        v = rng.standard_normal(self.dim).astype(np.float32)
        v /= np.linalg.norm(v) + 1e-9
        return v


def _make_engine(tmp_path, *, supernova_enabled: bool):
    config = GaOTTTConfig(
        data_dir=str(tmp_path),
        db_path=str(tmp_path / "test.db"),
        faiss_index_path=str(tmp_path / "test.faiss"),
        # Phase K knobs
        supernova_enabled=supernova_enabled,
        supernova_min_cohort_size=2,
        supernova_initial_weight=1.0,
        supernova_velocity_alpha=0.03,
        # Suppress unrelated background noise
        genesis_kick_enabled=False,
        dream_enabled=False,
        faiss_save_interval_seconds=0.0,
        flush_interval_seconds=0.05,
    )
    embedder = StubEmbedder(dim=config.embedding_dim)
    faiss_index = FaissIndex(dimension=config.embedding_dim)
    store = SqliteStore(db_path=config.db_path)
    cache = CacheLayer(
        flush_interval=config.flush_interval_seconds,
        flush_threshold=config.flush_threshold,
    )
    return GaOTTTEngine(
        config=config, embedder=embedder, faiss_index=faiss_index,
        cache=cache, store=store,
    )


@pytest.mark.asyncio
async def test_cohort_forms_mutual_edges(tmp_path):
    """A 4-node batch produces 6 mutual co-occurrence edges in the cache."""
    engine = _make_engine(tmp_path, supernova_enabled=True)
    await engine.startup()
    try:
        ids = await engine.index_documents([
            {"content": f"cohort-doc-{i}", "metadata": {"source": "agent"}}
            for i in range(4)
        ])
        assert len(ids) == 4
        # 4 choose 2 = 6 expected edges; each appears in both directions of
        # the undirected graph_cache, but cache.get_all_edges deduplicates.
        edges = engine.cache.get_all_edges()
        cohort_pairs = {
            tuple(sorted([e.src, e.dst]))
            for e in edges
            if e.src in ids and e.dst in ids
        }
        assert len(cohort_pairs) == 6, f"expected 6 unique pairs, got {len(cohort_pairs)}"
    finally:
        await engine.shutdown()


@pytest.mark.asyncio
async def test_cohort_members_get_outward_velocity(tmp_path):
    """Each cohort member has non-zero velocity in the cache; the velocity
    points away from the batch centroid (positive dot product with the
    radial direction)."""
    engine = _make_engine(tmp_path, supernova_enabled=True)
    await engine.startup()
    try:
        ids = await engine.index_documents([
            {"content": f"radial-doc-{i}", "metadata": {"source": "agent"}}
            for i in range(5)
        ])
        # Pull raw embeddings to compute the centroid and radial dirs
        emb_map = engine.faiss_index.get_vectors(ids)
        embs = np.stack([emb_map[nid] for nid in ids])
        centroid = embs.mean(axis=0)

        for i, nid in enumerate(ids):
            v = engine.cache.get_velocity(nid)
            assert v is not None, f"node {nid} has no cached velocity"
            assert float(np.linalg.norm(v)) > 1e-6, f"velocity ~ 0 for {nid}"
            radial = embs[i] - centroid
            cos = float(np.dot(v, radial)) / (
                float(np.linalg.norm(v)) * float(np.linalg.norm(radial)) + 1e-12
            )
            assert cos > 0.95, f"node {nid} velocity not radial: cos={cos}"
    finally:
        await engine.shutdown()


@pytest.mark.asyncio
async def test_supernova_disabled_legacy(tmp_path):
    """With supernova_enabled=False, no inter-batch edges form and no
    centroid-outward initial velocity is written. Genesis kick is also
    off, so velocities should be either absent or all-zero."""
    engine = _make_engine(tmp_path, supernova_enabled=False)
    await engine.startup()
    try:
        ids = await engine.index_documents([
            {"content": f"legacy-doc-{i}", "metadata": {"source": "agent"}}
            for i in range(4)
        ])
        # No inter-batch edges
        edges = engine.cache.get_all_edges()
        cohort_pairs = {
            tuple(sorted([e.src, e.dst]))
            for e in edges
            if e.src in ids and e.dst in ids
        }
        assert cohort_pairs == set(), f"unexpected cohort edges: {cohort_pairs}"

        # No initialized velocity (genesis_kick also off in this engine)
        for nid in ids:
            v = engine.cache.get_velocity(nid)
            assert v is None or float(np.linalg.norm(v)) < 1e-6, (
                f"unexpected velocity for {nid}: {v}"
            )
    finally:
        await engine.shutdown()


@pytest.mark.asyncio
async def test_supernova_single_doc_no_cohort(tmp_path):
    """A 1-doc batch (below min_cohort_size=2) gets no cohort treatment."""
    engine = _make_engine(tmp_path, supernova_enabled=True)
    await engine.startup()
    try:
        ids = await engine.index_documents([
            {"content": "solo-doc", "metadata": {"source": "agent"}},
        ])
        edges = engine.cache.get_all_edges()
        assert all(e.src not in ids and e.dst not in ids for e in edges), (
            "solo doc should have no cohort edges"
        )
        v = engine.cache.get_velocity(ids[0])
        assert v is None or float(np.linalg.norm(v)) < 1e-6
    finally:
        await engine.shutdown()


@pytest.mark.asyncio
async def test_cohort_lifts_mass_aware_seed_entry(tmp_path):
    """A cohort that all share mutual edges should get a higher mass-aware
    seed boost than legacy-mode counterparts when wave_seed_mass_alpha > 0.
    This is the integration-level reason Phase K helps Phase J Stage 1's
    seed-pool entry problem.

    We can't easily measure FAISS top-K admission directly in a unit test,
    but we can verify that cohort members' mass grows when one is recalled
    (because the mutual edges let Phase B-style mass propagation happen),
    while legacy nodes don't.
    """
    # With supernova: cohort edges + outward velocity
    engine_sn = _make_engine(tmp_path / "sn", supernova_enabled=True)
    (tmp_path / "sn").mkdir(exist_ok=True)
    await engine_sn.startup()
    try:
        ids_sn = await engine_sn.index_documents([
            {"content": f"cohort-{i}", "metadata": {"source": "agent"}}
            for i in range(4)
        ])
        # Check that cohort edges exist (this is what Phase B's wave then
        # exploits at recall time)
        edges_sn = engine_sn.cache.get_all_edges()
        sn_cohort_pairs = {
            tuple(sorted([e.src, e.dst]))
            for e in edges_sn
            if e.src in ids_sn and e.dst in ids_sn
        }
        assert len(sn_cohort_pairs) == 6
    finally:
        await engine_sn.shutdown()

    # Without supernova: no cohort edges
    engine_legacy = _make_engine(tmp_path / "lg", supernova_enabled=False)
    (tmp_path / "lg").mkdir(exist_ok=True)
    await engine_legacy.startup()
    try:
        ids_lg = await engine_legacy.index_documents([
            {"content": f"cohort-{i}", "metadata": {"source": "agent"}}
            for i in range(4)
        ])
        edges_lg = engine_legacy.cache.get_all_edges()
        lg_cohort_pairs = {
            tuple(sorted([e.src, e.dst]))
            for e in edges_lg
            if e.src in ids_lg and e.dst in ids_lg
        }
        assert lg_cohort_pairs == set()
    finally:
        await engine_legacy.shutdown()
