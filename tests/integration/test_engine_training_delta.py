"""Phase O Stage 2 — integration tests for TrainingDelta via engine + services.

Verifies:
- recall service attaches training_delta with mass/displacement changes
- consecutive recalls accumulate Δmass for the same node
- training_delta_enabled=False yields training_delta=None
- topk_only=False expands coverage to all reached nodes
- cache hits set cache_hit=True and emit empty dicts
"""
from __future__ import annotations

import hashlib

import numpy as np
import pytest

from gaottt.config import GaOTTTConfig
from gaottt.core.engine import GaOTTTEngine
from gaottt.index.faiss_index import FaissIndex
from gaottt.services import memory as memory_service
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
    base = dict(
        embedding_dim=32,
        data_dir=str(tmp_path),
        db_path=str(tmp_path / "ger.db"),
        faiss_index_path=str(tmp_path / "ger.faiss"),
        flush_interval_seconds=999.0,
        wave_initial_k=3,
        wave_max_depth=1,
    )
    base.update(overrides)
    cfg = GaOTTTConfig(**base)
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


async def test_recall_response_carries_training_delta(engine):
    await engine.index_documents([
        {"content": "alpha gamma kappa", "metadata": {"source": "user"}},
        {"content": "kappa lambda mu", "metadata": {"source": "user"}},
    ])
    resp = await memory_service.recall(engine, query="alpha gamma", top_k=3)
    assert resp.training_delta is not None
    td = resp.training_delta
    assert td.cache_hit is False
    assert td.wave_reached_count >= 1
    assert td.wave_max_depth == engine.config.wave_max_depth
    # delta dicts should cover at least the returned nodes
    assert set(td.displacement_changes.keys()) >= {r.id for r in resp.items}
    assert set(td.mass_changes.keys()) >= {r.id for r in resp.items}


async def test_consecutive_recalls_accumulate_mass_for_same_node(engine):
    """Repeatedly recalling the same query → mass keeps increasing for the same node."""
    ids = await engine.index_documents([
        {"content": "alpha gamma", "metadata": {"source": "user"}},
    ])
    target = ids[0]

    deltas = []
    for _ in range(3):
        resp = await memory_service.recall(engine, query="alpha gamma", top_k=3, force_refresh=True)
        td = resp.training_delta
        assert td is not None
        if target in td.mass_changes:
            deltas.append(td.mass_changes[target])

    # at least two consecutive runs should have produced positive Δmass
    positives = [d for d in deltas if d > 0]
    assert len(positives) >= 2, f"expected ≥2 positive Δmass entries, got {deltas}"


async def test_training_delta_disabled_yields_none(tmp_path):
    eng = await _make_engine(tmp_path, training_delta_enabled=False)
    try:
        await eng.index_documents([
            {"content": "alpha gamma", "metadata": {"source": "user"}},
        ])
        resp = await memory_service.recall(eng, query="alpha gamma", top_k=3)
        assert resp.training_delta is None
    finally:
        await eng.shutdown()


async def test_training_delta_topk_only_limits_coverage(tmp_path):
    """topk_only=True → delta dicts only cover returned (top-K) nodes."""
    eng = await _make_engine(tmp_path, wave_initial_k=10, wave_max_depth=2)
    try:
        await eng.index_documents([
            {"content": f"doc {i} alpha gamma", "metadata": {"source": "user"}}
            for i in range(8)
        ])
        # top_k=2 but wave should reach many more
        resp = await memory_service.recall(eng, query="alpha gamma", top_k=2)
        td = resp.training_delta
        assert td is not None
        assert td.topk_only is True
        assert len(td.displacement_changes) <= 2
        # reached count should be larger than the captured delta dict
        assert td.wave_reached_count >= len(td.displacement_changes)
    finally:
        await eng.shutdown()


async def test_training_delta_topk_only_false_covers_all_reached(tmp_path):
    eng = await _make_engine(
        tmp_path, wave_initial_k=10, wave_max_depth=2,
        training_delta_topk_only=False,
    )
    try:
        await eng.index_documents([
            {"content": f"doc {i} alpha gamma", "metadata": {"source": "user"}}
            for i in range(8)
        ])
        resp = await memory_service.recall(eng, query="alpha gamma", top_k=2)
        td = resp.training_delta
        assert td is not None
        assert td.topk_only is False
        # full reached coverage — delta dict size should match wave_reached_count
        # (modulo nodes that disappeared mid-step; expect equality in this small fixture)
        assert len(td.displacement_changes) == td.wave_reached_count
    finally:
        await eng.shutdown()


async def test_cache_hit_emits_explicit_cache_hit_flag(engine):
    """When prefetch cache serves the result, delta.cache_hit=True with empty dicts."""
    await engine.index_documents([
        {"content": "alpha gamma kappa", "metadata": {"source": "user"}},
    ])
    # First call: primes the cache (use the prefetch path explicitly via engine.query
    # so it serves as cache; recall service force-refreshes by default would skip cache)
    await engine.query(text="alpha gamma", top_k=3, use_cache=True)

    # Second call hits the cache. Use a direct engine.query with out_training_delta=
    delta_dict: dict = {}
    await engine.query(
        text="alpha gamma", top_k=3, use_cache=True,
        out_training_delta=delta_dict,
    )
    assert delta_dict.get("cache_hit") is True
    # cache hit path doesn't populate the delta dicts
    assert "displacement_changes" not in delta_dict or delta_dict["displacement_changes"] == {}


async def test_explore_carries_training_delta(engine):
    await engine.index_documents([
        {"content": "alpha gamma kappa", "metadata": {"source": "user"}},
        {"content": "delta epsilon", "metadata": {"source": "user"}},
    ])
    resp = await memory_service.explore(engine, query="alpha", diversity=0.5, top_k=3)
    assert resp.training_delta is not None
    assert resp.training_delta.wave_reached_count >= 1
