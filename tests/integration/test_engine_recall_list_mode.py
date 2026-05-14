"""Phase O Stage 4 — integration tests for recall(mode='list').

Verifies:
- mode='list' truncates content for *all* returned items
- mode='detail' (default) is byte-identical to legacy recall
- same query → same id ordering across modes (rerank must not depend on mode)
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


_LONG = (
    "Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do "
    "eiusmod tempor incididunt ut labore et dolore magna aliqua. Ut enim "
    "ad minim veniam, quis nostrud exercitation ullamco laboris nisi ut "
    "aliquip ex ea commodo consequat."
)


async def test_list_mode_truncates_each_item(engine):
    await engine.index_documents([
        {"content": f"alpha gamma {_LONG}", "metadata": {"source": "user"}},
        {"content": f"alpha kappa {_LONG}", "metadata": {"source": "user"}},
    ])
    r = await memory_service.recall(
        engine, query="alpha gamma", top_k=5, mode="list",
    )
    assert r.count > 0
    for item in r.items:
        assert len(item.content) <= engine.config.list_mode_excerpt_chars
        assert "\n" not in item.content


async def test_detail_mode_preserves_full_content(engine):
    full = f"alpha gamma {_LONG}"
    await engine.index_documents([
        {"content": full, "metadata": {"source": "user"}},
    ])
    r = await memory_service.recall(engine, query="alpha gamma", top_k=5)
    assert r.items[0].content == full


async def test_list_and_detail_mode_same_id_ordering(engine):
    await engine.index_documents([
        {"content": f"alpha gamma {_LONG}", "metadata": {"source": "user"}},
        {"content": f"alpha kappa {_LONG}", "metadata": {"source": "user"}},
        {"content": f"alpha zeta {_LONG}", "metadata": {"source": "user"}},
    ])
    r_detail = await memory_service.recall(
        engine, query="alpha gamma", top_k=5, mode="detail",
    )
    r_list = await memory_service.recall(
        engine, query="alpha gamma", top_k=5, mode="list",
    )
    assert [i.id for i in r_detail.items] == [i.id for i in r_list.items], (
        "list mode must not reorder results — it only truncates"
    )


async def test_list_mode_excerpt_chars_config_overridable(tmp_path):
    eng = await _make_engine(tmp_path, list_mode_excerpt_chars=20)
    try:
        await eng.index_documents([
            {"content": f"alpha gamma {_LONG}", "metadata": {"source": "user"}},
        ])
        r = await memory_service.recall(
            eng, query="alpha", top_k=5, mode="list",
        )
        assert all(len(i.content) <= 20 for i in r.items)
    finally:
        await eng.shutdown()


async def test_list_mode_score_breakdown_still_present(engine):
    """Stage 1 breakdown survives list mode (the *score* fields aren't truncated)."""
    await engine.index_documents([
        {"content": f"alpha gamma {_LONG}", "metadata": {"source": "user"}},
    ])
    r = await memory_service.recall(
        engine, query="alpha gamma", top_k=5, mode="list",
    )
    for item in r.items:
        assert item.score_breakdown is not None
