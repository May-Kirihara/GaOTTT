"""Phase O Stage 3 — integration tests for recall/explore auto-routing.

Verifies:
- recall with a matching surface form attaches RoutingHint + reflect_summary
- free-form recall query yields routing_hint.pattern_matched=False
- auto_route=False suppresses the reflect run entirely
- auto_route_enabled=False (config) suppresses globally
- explore parity
- the formatted MCP output carries the trailer when routed, not otherwise
"""
from __future__ import annotations

import hashlib

import numpy as np
import pytest

from gaottt.config import GaOTTTConfig
from gaottt.core.engine import GaOTTTEngine
from gaottt.index.faiss_index import FaissIndex
from gaottt.services import formatters
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


async def _seed_commitment(engine: GaOTTTEngine, content: str) -> str:
    """Plant a `source=commitment` memory so reflect(aspect='commitments') finds it."""
    ids = await engine.index_documents([
        {
            "content": content,
            "metadata": {
                "source": "commitment",
                "tags": ["phase-o-stage-3-test"],
            },
        }
    ])
    return ids[0]


async def test_recall_matched_query_attaches_routing_hint(engine):
    await _seed_commitment(engine, "Phase O Stage 3 を完了する")
    r = await memory_service.recall(
        engine, query="現在 active な commitment は何?", top_k=3,
    )
    h = r.routing_hint
    assert h is not None, "expected routing_hint to be attached when router is on"
    assert h.pattern_matched is True
    assert h.aspect == "commitments"
    assert h.auto_routed is True
    assert h.reflect_summary is not None
    # The reflect output for commitments lists items — the seeded content
    # must show up by substring.
    assert "Phase O Stage 3" in h.reflect_summary


async def test_recall_free_form_query_no_route(engine):
    await _seed_commitment(engine, "free-form check")
    r = await memory_service.recall(
        engine, query="Articulation as Carrier の物理実装", top_k=3,
    )
    h = r.routing_hint
    assert h is not None
    assert h.pattern_matched is False
    assert h.aspect is None
    assert h.auto_routed is False
    assert h.reflect_summary is None


async def test_recall_auto_route_false_suppresses(engine):
    await _seed_commitment(engine, "suppression check")
    r = await memory_service.recall(
        engine, query="現在 active な commitment", top_k=3, auto_route=False,
    )
    # With BOTH per-call auto_route=False and config still True, _build_routing_hint
    # returns a hint object with auto_routed=False (config covers the "still informative").
    # The point: reflect_summary must be None — no work was done.
    h = r.routing_hint
    if h is not None:
        assert h.reflect_summary is None
        assert h.auto_routed is False


async def test_recall_config_disabled_suppresses(tmp_path):
    eng = await _make_engine(tmp_path, auto_route_enabled=False)
    try:
        await eng.index_documents([
            {"content": "config off check", "metadata": {"source": "commitment"}},
        ])
        r = await memory_service.recall(
            eng, query="現在 active な commitment", top_k=3,
        )
        h = r.routing_hint
        if h is not None:
            assert h.auto_routed is False
            assert h.reflect_summary is None
    finally:
        await eng.shutdown()


async def test_explore_parity(engine):
    await _seed_commitment(engine, "explore parity check")
    r = await memory_service.explore(
        engine, query="現在 active な commitment", top_k=3,
    )
    h = r.routing_hint
    assert h is not None
    assert h.aspect == "commitments"
    assert h.auto_routed is True
    assert h.reflect_summary is not None


async def test_recall_formatter_appends_routing_trailer(engine):
    await _seed_commitment(engine, "format trailer check")
    r = await memory_service.recall(
        engine, query="持っている value", top_k=3,
    )
    out = formatters.format_recall(r)
    # When values is auto-routed even with no value declared, the reflect
    # call still runs and returns the "No values declared" hint. The trailer
    # marker must be present in either case.
    assert "auto-routed" in out
    assert "aspect" in out


async def test_recall_formatter_no_trailer_for_free_form(engine):
    await _seed_commitment(engine, "no trailer check")
    r = await memory_service.recall(
        engine, query="Articulation as Carrier", top_k=3,
    )
    out = formatters.format_recall(r)
    assert "auto-routed" not in out
