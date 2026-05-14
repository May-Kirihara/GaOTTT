"""Phase O Stage 1 — integration tests for engine.query producing ScoreBreakdown.

Verifies:
- score_breakdown attached to every QueryResultItem when expose_score_breakdown=True
- breakdown.expected_sum reproduces final_score (within FP tolerance)
- expose_score_breakdown=False yields score_breakdown=None
- forced_inclusion=True for tag-injected nodes
- determinism: two recalls of same query yield identical breakdown
"""
from __future__ import annotations

import hashlib
import math

import numpy as np
import pytest

from gaottt.config import GaOTTTConfig
from gaottt.core.engine import GaOTTTEngine
from gaottt.index.faiss_index import FaissIndex
from gaottt.store.cache import CacheLayer
from gaottt.store.sqlite_store import SqliteStore


class StubEmbedder:
    def __init__(self, dimension: int = 32):
        self._dim = dimension
        self._cache: dict[str, np.ndarray] = {}

    @property
    def dimension(self) -> int:
        return self._dim

    def _vec(self, tok: str) -> np.ndarray:
        v = self._cache.get(tok)
        if v is not None:
            return v
        seed = int.from_bytes(hashlib.md5(tok.encode()).digest()[:8], "big")
        rng = np.random.default_rng(seed)
        x = rng.standard_normal(self._dim).astype(np.float32)
        x /= np.linalg.norm(x) + 1e-9
        self._cache[tok] = x
        return x

    def _embed(self, text: str) -> np.ndarray:
        toks = [t.lower() for t in text.split() if t.strip()]
        if not toks:
            return np.zeros(self._dim, dtype=np.float32)
        v = sum(self._vec(t) for t in toks)
        n = np.linalg.norm(v)
        return (v / n).astype(np.float32) if n > 0 else v.astype(np.float32)

    def encode_documents(self, texts):
        return np.stack([self._embed(t) for t in texts])

    def encode_query(self, text):
        return self._embed(text).reshape(1, -1)


async def _make_engine(tmp_path, **overrides):
    cfg = GaOTTTConfig(
        embedding_dim=32,
        data_dir=str(tmp_path),
        db_path=str(tmp_path / "ger.db"),
        faiss_index_path=str(tmp_path / "ger.faiss"),
        flush_interval_seconds=999.0,
        wave_initial_k=3,
        wave_max_depth=1,
        **overrides,
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


@pytest.fixture
async def engine(tmp_path):
    eng = await _make_engine(tmp_path)
    try:
        yield eng
    finally:
        await eng.shutdown()


async def test_breakdown_attached_to_every_result(engine):
    await engine.index_documents([
        {"content": "alpha note about uv tooling", "metadata": {"source": "user"}},
        {"content": "beta note about uv migration", "metadata": {"source": "user"}},
    ])
    results = await engine.query(text="uv tooling", top_k=5)
    assert len(results) > 0
    for r in results:
        assert r.score_breakdown is not None
        assert r.score_breakdown.saturation > 0.0


async def test_breakdown_expected_sum_matches_final_score(engine):
    """The whole point of Phase O Stage 1: the additive decomposition is honest."""
    await engine.index_documents([
        {"content": "alpha gamma kappa zeta", "metadata": {"source": "user"}},
        {"content": "alpha beta delta epsilon", "metadata": {"source": "user"}},
        {"content": "kappa lambda mu nu", "metadata": {"source": "user"}},
    ])
    results = await engine.query(text="alpha gamma", top_k=5)
    for r in results:
        b = r.score_breakdown
        assert b is not None
        # FP tolerance — gravity_sim and wave_boost are accumulated separately
        assert math.isclose(
            b.expected_sum, r.final_score, rel_tol=1e-4, abs_tol=1e-6
        ), f"breakdown {b.expected_sum} != final_score {r.final_score} for {r.id}"


async def test_breakdown_disabled_yields_none(tmp_path):
    eng = await _make_engine(tmp_path, expose_score_breakdown=False)
    try:
        await eng.index_documents([
            {"content": "alpha note about uv", "metadata": {"source": "user"}},
        ])
        results = await eng.query(text="uv", top_k=5)
        assert len(results) > 0
        for r in results:
            assert r.score_breakdown is None
    finally:
        await eng.shutdown()


async def test_breakdown_forced_inclusion_marks_tag_injected(engine):
    """tag_filter injection sets forced_inclusion=True on injected nodes."""
    ids = await engine.index_documents([
        {
            "content": "alpha note",
            "metadata": {"source": "user", "tags": ["needle"]},
        },
        {
            "content": "beta note",
            "metadata": {"source": "user", "tags": []},
        },
    ])
    results = await engine.query(
        text="completely unrelated query xyz", top_k=5,
        tag_filter=["needle"],
    )
    # the needle-tagged doc must be present and flagged forced_inclusion
    forced = [r for r in results if r.id == ids[0]]
    assert len(forced) == 1
    assert forced[0].score_breakdown is not None
    assert forced[0].score_breakdown.forced_inclusion is True
    # the other doc, if it appears at all, is not forced
    others = [r for r in results if r.id == ids[1]]
    for o in others:
        assert o.score_breakdown.forced_inclusion is False


async def test_breakdown_persona_proximity_zero_without_persona(engine):
    """No declared persona → persona_proximity stays 0.0 in breakdown."""
    await engine.index_documents([
        {"content": "alpha note", "metadata": {"source": "user"}},
    ])
    results = await engine.query(text="alpha", top_k=5)
    for r in results:
        assert r.score_breakdown is not None
        assert r.score_breakdown.persona_proximity == 0.0


async def test_breakdown_deterministic_across_recalls(engine):
    """Same query → same breakdown (modulo tiny drift from displacement updates)."""
    await engine.index_documents([
        {"content": "alpha gamma kappa", "metadata": {"source": "user"}},
        {"content": "kappa lambda mu", "metadata": {"source": "user"}},
    ])
    r1 = await engine.query(text="alpha gamma", top_k=5, use_cache=False)
    r2 = await engine.query(text="alpha gamma", top_k=5, use_cache=False)
    # IDs should be identical (deterministic stub embedder), order may shift
    # slightly only if Phase I Stage 2 displacement kicked. Check breakdown
    # structurally: same node should have very similar (or identical) raw_cosine.
    map1 = {r.id: r.score_breakdown for r in r1}
    map2 = {r.id: r.score_breakdown for r in r2}
    common = set(map1) & set(map2)
    assert common, "expected at least one shared id across two recalls"
    for nid in common:
        # raw_cosine is purely cosine(query, original_emb) — must be identical
        assert math.isclose(map1[nid].raw_cosine, map2[nid].raw_cosine, abs_tol=1e-6)
