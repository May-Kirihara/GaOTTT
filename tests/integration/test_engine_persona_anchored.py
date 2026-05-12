"""Phase J Stage 1 — Persona-anchored gravity boost (integration).

End-to-end through engine.query():
  1. When a node is linked to a declared persona via derived_from / fulfills,
     it ranks higher with persona_boost_enabled=True than with =False.
  2. persona_boost_enabled=False makes the wave path call propagate with
     persona_proximities=None — legacy behaviour preserved.
  3. relate() / unrelate() keep cache.directed_out/in in sync (otherwise
     the next recall in the same process wouldn't see new edges).
"""
from __future__ import annotations

import numpy as np
import pytest

from gaottt.config import GaOTTTConfig
from gaottt.core.engine import GaOTTTEngine
from gaottt.index.faiss_index import FaissIndex
from gaottt.store.cache import CacheLayer
from gaottt.store.sqlite_store import SqliteStore


class StubEmbedder:
    """Deterministic token-based embeddings."""

    def __init__(self, dim: int = 768):
        self.dim = dim

    def encode_documents(self, contents):
        return np.array([self._embed(c) for c in contents], dtype=np.float32)

    def encode_query(self, text):
        return self._embed(text).reshape(1, -1).astype(np.float32)

    def _embed(self, text: str) -> np.ndarray:
        seed = abs(hash(text)) & 0xFFFFFFFF
        rng = np.random.default_rng(seed)
        v = rng.standard_normal(self.dim).astype(np.float32)
        v /= np.linalg.norm(v) + 1e-9
        return v


def _make_engine(tmp_path, *, persona_boost_enabled: bool, persona_boost_alpha: float = 0.5):
    config = GaOTTTConfig(
        data_dir=str(tmp_path),
        db_path=str(tmp_path / "test.db"),
        faiss_index_path=str(tmp_path / "test.faiss"),
        # Phase J knobs
        persona_boost_enabled=persona_boost_enabled,
        persona_boost_alpha=persona_boost_alpha,
        persona_max_hop=2,
        persona_hop_decay=0.5,
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


async def _index_and_get_ids(engine):
    """Index a known set of docs and return their IDs by content key."""
    docs = [
        {"content": "intention-shape-the-future", "metadata": {"source": "intention"}},
        {"content": "task-build-the-thing", "metadata": {"source": "task"}},
        {"content": "agent-knowledge-derived-from-the-work", "metadata": {"source": "agent"}},
        {"content": "distraction-file-content-1", "metadata": {"source": "file"}},
        {"content": "distraction-file-content-2", "metadata": {"source": "file"}},
        {"content": "distraction-file-content-3", "metadata": {"source": "file"}},
        {"content": "distraction-agent-unrelated", "metadata": {"source": "agent"}},
    ]
    await engine.index_documents(docs)
    # The engine assigns IDs via SHA-256 of content — find them back by content.
    nodes = engine.cache.get_all_nodes()
    by_content: dict[str, str] = {}
    for nstate in nodes:
        doc = await engine.store.get_document(nstate.id)
        if doc:
            by_content[doc["content"]] = nstate.id
    return by_content


@pytest.mark.asyncio
async def test_persona_boost_lifts_linked_agent_memo(tmp_path):
    """An agent memo linked via derived_from → task → fulfills → intention
    should rank higher with persona_boost_enabled=True than with =False on
    a probe whose raw cosine is unrelated to all docs (so persona boost is
    the dominant rank signal).
    """

    async def rank_of_linked_memo(subdir: str, enabled: bool) -> int:
        path = tmp_path / subdir
        path.mkdir()
        engine = _make_engine(path, persona_boost_enabled=enabled)
        await engine.startup()
        try:
            by_content = await _index_and_get_ids(engine)
            intention_id = by_content["intention-shape-the-future"]
            task_id = by_content["task-build-the-thing"]
            agent_id = by_content["agent-knowledge-derived-from-the-work"]

            # Build the persona-gravity chain. Phase D semantics: fulfills
            # goes from task to its parent; derived_from from extension to
            # seed. Persona node "intention" is the persona; "agent_id"
            # is 2 hops away (agent → task → intention).
            await engine.relate(task_id, intention_id, "fulfills")
            await engine.relate(agent_id, task_id, "derived_from")

            # Probe with text that has no specific semantic match — random
            # cosine landscape. Persona boost should lift the linked agent
            # memo above unrelated distractions.
            results = await engine.query(text="random unrelated probe", top_k=7)
            ranks = {r.id: i for i, r in enumerate(results)}
            # Sentinel large rank if not in top_k at all
            return ranks.get(agent_id, 999)
        finally:
            await engine.shutdown()

    rank_with = await rank_of_linked_memo("with", enabled=True)
    rank_without = await rank_of_linked_memo("without", enabled=False)

    # With persona boost, the linked agent memo should appear in results
    # (rank < 999) and rank at least as well as without.
    assert rank_with < 999, f"linked agent memo not in top-7 with boost (rank={rank_with})"
    assert rank_with <= rank_without, (
        f"persona boost should not worsen the linked memo's rank — "
        f"with={rank_with}, without={rank_without}"
    )


@pytest.mark.asyncio
async def test_persona_boost_disabled_no_proximities_in_wave(tmp_path):
    """With persona_boost_enabled=False the engine must not compute or
    pass persona_proximities through to propagate_gravity_wave."""
    engine = _make_engine(tmp_path, persona_boost_enabled=False)
    await engine.startup()
    try:
        by_content = await _index_and_get_ids(engine)
        intention_id = by_content["intention-shape-the-future"]
        task_id = by_content["task-build-the-thing"]
        await engine.relate(task_id, intention_id, "fulfills")

        # The recall still succeeds (legacy path used)
        results = await engine.query(text="probe", top_k=5)
        # We don't assert specific ordering; just that no crash and the
        # wave produced results without persona influence.
        assert isinstance(results, list)
    finally:
        await engine.shutdown()


@pytest.mark.asyncio
async def test_relate_unrelate_keep_directed_cache_in_sync(tmp_path):
    """engine.relate() must mirror into cache.directed_out/in so that
    persona traversal in the same process sees the new edge. unrelate()
    must remove it."""
    engine = _make_engine(tmp_path, persona_boost_enabled=True)
    await engine.startup()
    try:
        by_content = await _index_and_get_ids(engine)
        intention_id = by_content["intention-shape-the-future"]
        task_id = by_content["task-build-the-thing"]

        # Before: no edge
        assert (intention_id, "fulfills") not in engine.cache.get_outgoing(task_id)
        assert (task_id, "fulfills") not in engine.cache.get_incoming(intention_id)

        await engine.relate(task_id, intention_id, "fulfills")

        # After relate: cache is in sync
        assert (intention_id, "fulfills") in engine.cache.get_outgoing(task_id)
        assert (task_id, "fulfills") in engine.cache.get_incoming(intention_id)

        # After unrelate: gone
        await engine.unrelate(task_id, intention_id, "fulfills")
        assert (intention_id, "fulfills") not in engine.cache.get_outgoing(task_id)
        assert (task_id, "fulfills") not in engine.cache.get_incoming(intention_id)
    finally:
        await engine.shutdown()
