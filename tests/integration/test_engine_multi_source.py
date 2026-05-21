"""Multi-Source Query — query as a mass distribution (integration).

A compound prompt whose *pooled* embedding lands on one cluster: the legacy
single-source path (one pooled centroid) misses the other cluster entirely;
multi-source recall segments the prompt and seeds from the superposed
per-segment pools, so the drowned cluster is surfaced.

Flag-off assertions are paired with flag-on positive controls so a silently
broken segmentation path cannot let the test pass vacuously. See
docs/wiki/Plans-Query-Mass-Distribution.md.
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

_DIM = 16
# Compound prompt: clause 1 → A cluster, clause 2 → B cluster. Each clause is
# ≥ multi_source_min_segment_chars (12) so neither merges away.
_SEG_A = "アルファ集団に関する長めのクエリ"
_SEG_B = "ベータ集団に関する長めのクエリ"
_COMPOUND = f"{_SEG_A}。{_SEG_B}"


def _axis(i: int) -> np.ndarray:
    v = np.zeros(_DIM, dtype=np.float32)
    v[i] = 1.0
    return v


def _perturbed(base: np.ndarray, tag: str) -> np.ndarray:
    """A point close to ``base`` — distinct per tag, ~0.99 mutual cosine."""
    seed = int.from_bytes(hashlib.sha256(tag.encode()).digest()[:8], "big")
    rng = np.random.default_rng(seed)
    p = rng.standard_normal(_DIM).astype(np.float32)
    p /= np.linalg.norm(p) + 1e-9
    v = base + 0.06 * p
    return (v / (np.linalg.norm(v) + 1e-9)).astype(np.float32)


class KeyedEmbedder:
    """Deterministic embedder with hand-placed geometry.

    A-cluster docs sit near axis 0, the B-cluster doc near axis 1. The
    compound prompt's *pooled* embedding is mapped onto axis 0 — it simulates
    centroid drag: the whole-prompt vector lands on the dominant cluster and
    cannot see cluster B. The *segments* embed onto their own axes, so
    multi-source seeding reaches both.
    """

    def __init__(self):
        self.dim = _DIM
        self._a = _axis(0)
        self._b = _axis(1)

    def _embed(self, text: str) -> np.ndarray:
        if text.startswith("a-doc"):
            return _perturbed(self._a, text)
        if text.startswith("b-doc"):
            return _perturbed(self._b, text)
        if text == _COMPOUND or text == _SEG_A:
            return self._a.copy()        # pooled centroid → A cluster (drag)
        if text == _SEG_B:
            return self._b.copy()
        return _perturbed(self._a, "fallback:" + text)

    def encode_documents(self, texts):
        return np.array([self._embed(t) for t in texts], dtype=np.float32)

    def encode_queries(self, texts):
        return np.array([self._embed(t) for t in texts], dtype=np.float32)

    def encode_query(self, text):
        return self.encode_queries([text])


def _make_engine(tmp_path, **cfg_kw):
    base = dict(
        embedding_dim=_DIM,
        data_dir=str(tmp_path),
        db_path=str(tmp_path / "t.db"),
        faiss_index_path=str(tmp_path / "t.faiss"),
        genesis_kick_enabled=False,
        dream_enabled=False,
        supernova_enabled=False,
        hybrid_bm25_enabled=False,
        faiss_save_interval_seconds=0.0,
        flush_interval_seconds=0.05,
    )
    base.update(cfg_kw)
    config = GaOTTTConfig(**base)
    return GaOTTTEngine(
        config=config,
        embedder=KeyedEmbedder(),
        faiss_index=FaissIndex(dimension=_DIM),
        cache=CacheLayer(
            flush_interval=config.flush_interval_seconds,
            flush_threshold=config.flush_threshold,
        ),
        store=SqliteStore(db_path=config.db_path),
    )


async def _index_clusters(engine):
    await engine.index_documents(
        [{"content": f"a-doc-{i}", "metadata": {"source": "agent"}} for i in range(4)]
        + [{"content": "b-doc-0", "metadata": {"source": "agent"}}]
    )


@pytest.mark.asyncio
async def test_single_source_misses_the_other_cluster(tmp_path):
    """Baseline / rollback proof — with multi_source_enabled=False the
    compound prompt's pooled centroid lands on the A cluster and the B
    cluster is never surfaced."""
    engine = _make_engine(tmp_path, multi_source_enabled=False)
    await engine.startup()
    try:
        await _index_clusters(engine)
        results = await engine.query(text=_COMPOUND, top_k=10)
        contents = [r.content for r in results]
        assert any("a-doc" in c for c in contents), "A cluster must be found"
        assert not any("b-doc" in c for c in contents), (
            "single-source unexpectedly reached the B cluster"
        )
    finally:
        await engine.shutdown()


@pytest.mark.asyncio
async def test_multi_source_surfaces_the_drowned_cluster(tmp_path):
    """Teeth — multi_source_enabled=True segments the compound prompt and
    seeds from both clusters, surfacing the B cluster the centroid missed."""
    engine = _make_engine(tmp_path, multi_source_enabled=True)
    await engine.startup()
    try:
        await _index_clusters(engine)
        delta: dict = {}
        results = await engine.query(
            text=_COMPOUND, top_k=10, out_training_delta=delta,
        )
        contents = [r.content for r in results]
        assert any("b-doc" in c for c in contents), (
            "multi-source did not surface the B cluster"
        )
        assert delta.get("intent_centers") == 2, (
            "compound prompt should report 2 intent centers"
        )
    finally:
        await engine.shutdown()


@pytest.mark.asyncio
async def test_simple_prompt_reports_one_intent_center(tmp_path):
    """A non-compound prompt does not split — intent_centers stays 1 even
    with the flag on (segmentation is a no-op, legacy single-source path)."""
    engine = _make_engine(tmp_path, multi_source_enabled=True)
    await engine.startup()
    try:
        await _index_clusters(engine)
        delta: dict = {}
        await engine.query(
            text="アルファ集団についてのみ知りたいです", top_k=5,
            out_training_delta=delta,
        )
        assert delta.get("intent_centers") == 1
    finally:
        await engine.shutdown()


@pytest.mark.asyncio
async def test_flag_off_keeps_compound_prompt_single_source(tmp_path):
    """With the flag off, even a compound prompt is single-source —
    intent_centers == 1 (the segmentation path is never entered)."""
    engine = _make_engine(tmp_path, multi_source_enabled=False)
    await engine.startup()
    try:
        await _index_clusters(engine)
        delta: dict = {}
        await engine.query(text=_COMPOUND, top_k=5, out_training_delta=delta)
        assert delta.get("intent_centers") == 1
    finally:
        await engine.shutdown()


@pytest.mark.asyncio
async def test_passive_multi_source_reports_centers_but_perturbs_nothing(tmp_path):
    """A passive multi-source recall still segments (intent_centers==2) but
    leaves the field untouched; an active multi-source recall is the
    positive control proving the field *can* move."""
    engine = _make_engine(tmp_path, multi_source_enabled=True)
    await engine.startup()
    try:
        await _index_clusters(engine)
        seed = await engine.query(text=_COMPOUND, top_k=10)
        ids = [r.id for r in seed]
        assert ids, "setup recall must return results"
        masses_before = {
            nid: float(engine.cache.get_node(nid).mass) for nid in ids
        }

        delta: dict = {}
        for _ in range(5):
            await engine.query(
                text=_COMPOUND, top_k=10, passive=True, out_training_delta=delta,
            )
        assert delta.get("intent_centers") == 2
        masses_passive = {
            nid: float(engine.cache.get_node(nid).mass) for nid in ids
        }
        assert masses_passive == masses_before, (
            "passive multi-source recall changed mass"
        )

        # Positive control — an active multi-source recall MUST move mass.
        await engine.query(text=_COMPOUND, top_k=10)
        masses_active = {
            nid: float(engine.cache.get_node(nid).mass) for nid in ids
        }
        assert masses_active != masses_before, (
            "active recall did not move mass — passive assertion is vacuous"
        )
    finally:
        await engine.shutdown()
