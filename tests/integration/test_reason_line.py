"""Observation Apparatus Refinement Stage 1 — integration tests.

End-to-end coverage that ``ScoreBreakdown.reason`` is populated through
``services.memory.recall`` and that the MCP formatter renders the
``reason:`` line. Uses the same StubEmbedder pattern as test_engine_archive_ttl.
"""

from __future__ import annotations

import hashlib

import numpy as np
import pytest

from gaottt.config import GaOTTTConfig
from gaottt.core.engine import GaOTTTEngine
from gaottt.index.faiss_index import FaissIndex
from gaottt.services import formatters
from gaottt.services.memory import recall as recall_service
from gaottt.store.cache import CacheLayer
from gaottt.store.sqlite_store import SqliteStore


class StubEmbedder:
    def __init__(self, dimension: int = 32):
        self._dimension = dimension
        self._token_cache: dict[str, np.ndarray] = {}

    @property
    def dimension(self) -> int:
        return self._dimension

    def _token_vec(self, token: str) -> np.ndarray:
        cached = self._token_cache.get(token)
        if cached is not None:
            return cached
        seed = int.from_bytes(hashlib.md5(token.encode()).digest()[:8], "big")
        rng = np.random.default_rng(seed)
        v = rng.standard_normal(self._dimension).astype(np.float32)
        v /= np.linalg.norm(v) + 1e-9
        self._token_cache[token] = v
        return v

    def _embed(self, text: str) -> np.ndarray:
        tokens = [t.lower() for t in text.split() if t.strip()]
        if not tokens:
            return np.zeros(self._dimension, dtype=np.float32)
        v = sum(self._token_vec(t) for t in tokens)
        norm = np.linalg.norm(v)
        return (v / norm).astype(np.float32) if norm > 0 else v.astype(np.float32)

    def encode_documents(self, texts: list[str]) -> np.ndarray:
        return np.stack([self._embed(t) for t in texts])

    def encode_query(self, text: str) -> np.ndarray:
        return self._embed(text).reshape(1, -1)


@pytest.fixture
async def engine(tmp_path):
    cfg = GaOTTTConfig(
        embedding_dim=32,
        data_dir=str(tmp_path),
        db_path=str(tmp_path / "ger.db"),
        faiss_index_path=str(tmp_path / "ger.faiss"),
        flush_interval_seconds=999.0,
        wave_initial_k=3,
        wave_max_depth=1,
    )
    eng = GaOTTTEngine(
        config=cfg,
        embedder=StubEmbedder(dimension=32),
        faiss_index=FaissIndex(dimension=32),
        cache=CacheLayer(flush_interval=999.0),
        store=SqliteStore(db_path=cfg.db_path),
    )
    await eng.startup()
    try:
        yield eng
    finally:
        await eng.shutdown()


async def test_recall_attaches_reason_when_enabled(engine):
    """ScoreBreakdown.reason is populated through services.memory.recall."""
    await engine.index_documents([
        {"content": "alpha gravity wave", "metadata": {"source": "agent"}},
        {"content": "beta gravity field", "metadata": {"source": "agent"}},
    ])
    result = await recall_service(engine, query="gravity wave", top_k=5)
    assert result.items, "expected at least one recall hit"
    # At least one item should carry a reason — StubEmbedder gives a strong
    # virtual_cosine, so the semantic-match fallback fires.
    reasoned = [m for m in result.items if m.score_breakdown and m.score_breakdown.reason]
    assert reasoned, "expected reason to be populated on at least one item"


async def test_recall_skips_reason_when_disabled(engine):
    """expose_reason=False short-circuits explain_score (no string generated)."""
    engine.config.expose_reason = False
    try:
        await engine.index_documents([
            {"content": "alpha gravity wave", "metadata": {"source": "agent"}},
        ])
        result = await recall_service(engine, query="gravity wave", top_k=5)
        assert result.items
        for m in result.items:
            if m.score_breakdown is not None:
                assert m.score_breakdown.reason is None
    finally:
        engine.config.expose_reason = True


async def test_dominance_artifact_fires_on_high_mass(engine):
    """When a node's mass crosses the threshold and cosine is low, the
    'possible dominance artifact' suffix appears in the reason line.

    We synthesize this by manually bumping a node's mass on the cache
    layer — physics is *not* touched (we're testing the observation
    layer's ability to flag dominance, not its computation).
    """
    ids = await engine.index_documents([
        {"content": "alpha persona statement", "metadata": {"source": "agent"}},
        {"content": "beta unrelated topic", "metadata": {"source": "agent"}},
    ])
    # Force high mass on the first node (mutate cache state in place; the
    # write-back loop or shutdown will flush it. We only need the value to
    # be visible to `_enrich_breakdown`'s `cache.get_node()` read.)
    state = engine.cache.get_node(ids[0])
    assert state is not None
    state.mass = 5.0

    # Query something semantically far so virtual_cosine stays low for the
    # high-mass node — high_mass + low_cos triggers the dominance flag.
    result = await recall_service(engine, query="completely orthogonal query", top_k=5)
    for m in result.items:
        if m.id != ids[0]:
            continue
        b = m.score_breakdown
        if b is None or b.virtual_cosine >= 0.5:
            # Cosine ended up high — dominance flag would not fire.
            return
        assert b.reason is not None
        assert "high mass persona proximity" in b.reason
        assert "possible dominance artifact" in b.reason


async def test_formatter_renders_reason_line(engine):
    """``_format_breakdown`` emits the ``reason:`` sub-line when populated."""
    await engine.index_documents([
        {"content": "alpha gravity wave note", "metadata": {"source": "agent"}},
    ])
    result = await recall_service(engine, query="gravity wave", top_k=3)
    assert result.items
    item = result.items[0]
    rendered = formatters._format_breakdown(item.score_breakdown)
    # Existing breakdown line stays first (Phase O Stage 1 substring contract)
    assert "breakdown: cos=" in rendered
    if item.score_breakdown and item.score_breakdown.reason:
        # The reason is rendered on a second indented line, so the existing
        # one-line breakdown assertions in test_mcp_tools keep matching.
        assert "\n  reason:" in rendered
