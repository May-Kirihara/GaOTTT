"""Phase O Stage 5 — integration tests for explore(mode='dormant').

Verifies:
- dormant mode returns nodes matching age + mass + source-class conditions
- source classes outside ``dormant_source_classes`` (e.g. tweet/file) are filtered
- recent (last_access > cutoff) nodes are filtered
- high-mass nodes are filtered (only counter-importance candidates)
- empty result returns ``ExploreResponse(items=[], count=0)`` (no exception)
- training_delta and routing_hint are None (no wave / no query intent)
"""
from __future__ import annotations

import hashlib
import time

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
        # These dormant tests predate Stage 7.2 and assert against the
        # legacy absolute ``dormant_mass_threshold`` semantic (e.g.
        # ``mass=10.0`` must NOT surface because it exceeds the absolute
        # 2.0 cut). The default has been promoted to ``10.0`` (percentile
        # mode) — pin to ``None`` here so the legacy assertions remain
        # the contract under test. Stage 7.2-specific behaviour is covered
        # by ``tests/perf/test_tier5_phase_o_dormant.py``.
        dormant_mass_percentile=None,
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


async def _index_aged(engine, content: str, source: str, age_days: float, mass: float = 1.0):
    """Plant a doc and rewind its ``last_access`` to ``age_days`` ago.

    Direct cache surgery — we cannot wait 30+ days in a test.
    """
    ids = await engine.index_documents([
        {"content": content, "metadata": {"source": source}},
    ])
    nid = ids[0]
    state = engine.cache.get_node(nid)
    if state is not None:
        state.last_access = time.time() - age_days * 86400.0
        state.mass = mass
    return nid


@pytest.fixture
async def engine(tmp_path):
    eng = await _make_engine(tmp_path)
    try:
        yield eng
    finally:
        await eng.shutdown()


async def test_dormant_surfaces_old_low_mass_self_authored(engine):
    aged_id = await _index_aged(
        engine, "I authored this and forgot", source="agent",
        age_days=60, mass=1.0,
    )
    r = await memory_service.explore(
        engine, query="ignored", mode="dormant", top_k=5,
    )
    assert r.count >= 1
    assert any(item.id == aged_id for item in r.items)


async def test_dormant_filters_recent_nodes(engine):
    recent_id = await _index_aged(
        engine, "recent agent note", source="agent",
        age_days=1, mass=1.0,
    )
    r = await memory_service.explore(
        engine, query="ignored", mode="dormant", top_k=5,
    )
    assert all(item.id != recent_id for item in r.items)


async def test_dormant_filters_high_mass(engine):
    mature_id = await _index_aged(
        engine, "much-recalled agent note", source="agent",
        age_days=60, mass=10.0,   # well above default threshold 2.0
    )
    r = await memory_service.explore(
        engine, query="ignored", mode="dormant", top_k=5,
    )
    assert all(item.id != mature_id for item in r.items)


async def test_dormant_filters_non_self_authored_sources(engine):
    """tweet / file / hypothesis must not surface — dormant is for *self*-authored memos."""
    tweet_id = await _index_aged(
        engine, "twitter content", source="tweet",
        age_days=60, mass=1.0,
    )
    file_id = await _index_aged(
        engine, "file content", source="file",
        age_days=60, mass=1.0,
    )
    r = await memory_service.explore(
        engine, query="ignored", mode="dormant", top_k=10,
    )
    ids = {item.id for item in r.items}
    assert tweet_id not in ids
    assert file_id not in ids


async def test_dormant_empty_result_safe(engine):
    """No exception when nothing matches — returns empty ExploreResponse."""
    # Plant only recent / high-mass / wrong-source memos
    await _index_aged(engine, "recent note", "agent", age_days=1, mass=1.0)
    await _index_aged(engine, "tweet", "tweet", age_days=60, mass=1.0)
    r = await memory_service.explore(
        engine, query="ignored", mode="dormant", top_k=5,
    )
    assert r.count == 0
    assert r.items == []


async def test_dormant_response_omits_training_delta_and_routing_hint(engine):
    """dormant skips the wave entirely → no TTT update / no aspect routing."""
    await _index_aged(engine, "dormant note", "agent", age_days=60, mass=1.0)
    r = await memory_service.explore(
        engine, query="ignored", mode="dormant", top_k=5,
    )
    assert r.training_delta is None
    assert r.routing_hint is None


async def test_dormant_includes_all_self_authored_classes(engine):
    """Each class in dormant_source_classes is eligible — agent/value/intention/commitment/note/reference."""
    seeded: dict[str, str] = {}
    for src in ("agent", "value", "intention", "commitment", "note", "reference"):
        seeded[src] = await _index_aged(
            engine, f"dormant {src}", source=src, age_days=60, mass=1.0,
        )
    r = await memory_service.explore(
        engine, query="ignored", mode="dormant", top_k=20,
    )
    surfaced_sources = {item.source for item in r.items}
    # All 6 should be surfacable; depending on random sample we may not hit all
    # in a single call, so we run multiple draws.
    for _ in range(5):
        r2 = await memory_service.explore(
            engine, query="ignored", mode="dormant", top_k=20,
        )
        surfaced_sources |= {item.source for item in r2.items}
    assert surfaced_sources >= {
        "agent", "value", "intention", "commitment", "note", "reference",
    }
