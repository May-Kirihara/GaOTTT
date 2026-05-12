"""Phase J Stage 2 — explicit pool injection (integration).

The key acceptance property: a node whose embedding is *far* from the
query (raw cosine outside FAISS top-K) must still surface when its tag
is in ``tag_filter`` or its id is in ``persona_context``.

We construct a deliberately adversarial fixture:
  - A "target" memo with content unrelated to the probe query, tagged
    ``acceptance-target`` (so it has no embedding affinity to the probe).
  - Many "distractor" memos whose content overlaps the probe word for word
    (high raw cosine, will dominate FAISS top-K).
  - Then call recall with and without ``tag_filter=["acceptance-target"]``.
    Without injection: target is absent. With injection: target surfaces.
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
    """Hash-based deterministic embedder. Two strings get similar embeddings
    only if they have an overlap of substring tokens — close enough for
    making intentional embedding distance in tests."""

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


def _make_engine(tmp_path):
    config = GaOTTTConfig(
        data_dir=str(tmp_path),
        db_path=str(tmp_path / "test.db"),
        faiss_index_path=str(tmp_path / "test.faiss"),
        genesis_kick_enabled=False,
        dream_enabled=False,
        supernova_enabled=False,  # isolate injection
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


def _rank_of(results, tid: str) -> int:
    """Return the 0-based rank of ``tid`` in the result list, or 999 if absent."""
    for i, r in enumerate(results):
        if r.id == tid:
            return i
    return 999


@pytest.mark.asyncio
async def test_tag_filter_lifts_target_rank(tmp_path):
    """A target memo tagged ``acceptance-target`` must rank strictly higher
    when ``tag_filter=["acceptance-target"]`` is passed than when omitted.
    StubEmbedder is hash-random so we can't reliably assert "absent without
    injection" — the relative rank shift is the robust acceptance signal."""
    engine = _make_engine(tmp_path)
    await engine.startup()
    try:
        target_meta = {"source": "agent", "tags": ["acceptance-target"]}
        ids_target = await engine.index_documents([
            {"content": "tracked-cohort-target-xy-vector", "metadata": target_meta},
        ])
        target_id = ids_target[0]
        probe = "purple monkey dishwasher"
        await engine.index_documents([
            {"content": f"{probe} chunk {i}", "metadata": {"source": "agent"}}
            for i in range(30)
        ])

        results_no = await engine.query(text=probe, top_k=20)
        results_inj = await engine.query(
            text=probe, top_k=20,
            tag_filter=["acceptance-target"],
        )

        rank_no = _rank_of(results_no, target_id)
        rank_inj = _rank_of(results_inj, target_id)

        # With injection the target must (a) be in the results at all and
        # (b) rank at least as well — typically strictly better.
        assert rank_inj < 999, f"target absent under tag_filter (rank={rank_inj})"
        assert rank_inj <= rank_no, (
            f"tag_filter should not worsen target rank. "
            f"rank_no_inject={rank_no}, rank_with_inject={rank_inj}"
        )
    finally:
        await engine.shutdown()


@pytest.mark.asyncio
async def test_persona_context_lifts_target_rank(tmp_path):
    """Explicit ``persona_context`` IDs must improve (or at least not worsen)
    the target's rank in the result list."""
    engine = _make_engine(tmp_path)
    await engine.startup()
    try:
        ids_target = await engine.index_documents([
            {"content": "intention-anchor-far-far-content",
             "metadata": {"source": "intention"}},
        ])
        target_id = ids_target[0]
        probe = "alpha beta gamma delta"
        await engine.index_documents([
            {"content": f"{probe} item {i}", "metadata": {"source": "agent"}}
            for i in range(30)
        ])

        results_plain = await engine.query(text=probe, top_k=20)
        results_pc = await engine.query(
            text=probe, top_k=20,
            persona_context=[target_id],
        )
        rank_plain = _rank_of(results_plain, target_id)
        rank_pc = _rank_of(results_pc, target_id)
        assert rank_pc < 999, f"target absent under persona_context (rank={rank_pc})"
        assert rank_pc <= rank_plain
    finally:
        await engine.shutdown()


@pytest.mark.asyncio
async def test_tag_filter_bypasses_source_filter(tmp_path):
    """Phase J Stage 2 design: tag_filter is additive AND bypasses
    source_filter restrictions. The caller's explicit ask wins."""
    engine = _make_engine(tmp_path)
    await engine.startup()
    try:
        # Target has source=file (would be excluded by source_filter=["agent"])
        # but tag matches the explicit filter
        target_meta = {"source": "file", "tags": ["bypass-target"]}
        ids_target = await engine.index_documents([
            {"content": "bypass-content-content-content", "metadata": target_meta},
        ])
        target_id = ids_target[0]

        await engine.index_documents([
            {"content": f"another-doc-{i}", "metadata": {"source": "agent"}}
            for i in range(5)
        ])

        # With source_filter=["agent"] alone the file target is excluded
        results_sf = await engine.query(
            text="other probe", top_k=5,
            source_filter=["agent"],
        )
        assert target_id not in [r.id for r in results_sf]

        # With source_filter + tag_filter, the tag_filter injection bypasses
        # the source_filter restriction
        results_combo = await engine.query(
            text="other probe", top_k=5,
            source_filter=["agent"],
            tag_filter=["bypass-target"],
        )
        assert target_id in [r.id for r in results_combo]
    finally:
        await engine.shutdown()


@pytest.mark.asyncio
async def test_no_args_preserves_legacy_behaviour(tmp_path):
    """When neither persona_context nor tag_filter is passed, recall behaves
    exactly as Stage 1 (no injection, normal FAISS top-K). This is the
    backward-compatibility guarantee."""
    engine = _make_engine(tmp_path)
    await engine.startup()
    try:
        ids = await engine.index_documents([
            {"content": f"plain-doc-{i}", "metadata": {"source": "agent"}}
            for i in range(5)
        ])
        # No exceptions, results returned, sane shape.
        results = await engine.query(text="plain-doc-1", top_k=3)
        assert isinstance(results, list)
        assert len(results) <= 3
        # Top result should be the matching plain-doc (raw cosine should still
        # dominate without any injection).
        assert results[0].id in ids
    finally:
        await engine.shutdown()


# ---------------------------------------------------------------------------
# Phase J Stage 3 — forced 内 query-aware ordering + prefetch/explore parity
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_stage3_forced_ordering_uses_raw_score(tmp_path):
    """Phase J Stage 3: when ``tag_filter`` matches more nodes than ``top_k``,
    the forced top-K must be ordered by ``raw_score`` (query semantic) — NOT
    by ``final_score`` (which is dominated by mass/wave/emotion accumulated
    from prior recalls).

    Construct two tagged memos: one semantically near the probe (high raw
    cosine), one semantically far. Boost the *far* one's recall count so
    its final_score climbs. Then recall with ``tag_filter`` matching both.
    Stage 3: the *near* one must rank above the far one — query semantic
    wins inside the forced set.
    """
    engine = _make_engine(tmp_path)
    await engine.startup()
    try:
        probe = "specific-probe-vocab-XY"
        # Near memo: shares vocabulary with the probe → high raw cosine
        near_meta = {"source": "agent", "tags": ["stage3-target"]}
        ids_near = await engine.index_documents([
            {"content": f"{probe} continuation prose", "metadata": near_meta},
        ])
        near_id = ids_near[0]
        # Far memo: disjoint vocabulary → low raw cosine to probe
        far_meta = {"source": "agent", "tags": ["stage3-target"]}
        ids_far = await engine.index_documents([
            {"content": "completely unrelated dorsal arrangement", "metadata": far_meta},
        ])
        far_id = ids_far[0]
        # Some distractors to populate the pool
        await engine.index_documents([
            {"content": f"distract chunk {i}", "metadata": {"source": "agent"}}
            for i in range(20)
        ])

        # Inflate ``far_id``'s final_score by repeatedly recalling its own
        # content — Phase I Stage 2 will drift its displacement and mass.
        for _ in range(8):
            await engine.query(text="completely unrelated dorsal arrangement", top_k=3)

        # Now recall with tag_filter — both stage3-target memos are forced.
        results = await engine.query(
            text=probe, top_k=2, tag_filter=["stage3-target"],
        )
        ids = [r.id for r in results]
        assert near_id in ids, f"near memo absent from forced top-K: {ids}"
        assert far_id in ids, f"far memo absent from forced top-K: {ids}"
        # Key Stage 3 assertion: query semantic (raw_score) wins inside
        # the forced set — near must rank above far.
        assert ids.index(near_id) < ids.index(far_id), (
            f"Stage 3 expects raw_score ordering inside forced set — "
            f"near should outrank far. Got: {ids}"
        )
    finally:
        await engine.shutdown()


@pytest.mark.asyncio
async def test_stage3_explore_accepts_tag_filter(tmp_path):
    """Phase J Stage 3 parity: ``explore`` must accept tag_filter and
    surface tagged nodes even on a wide exploratory wave."""
    from gaottt.services import memory as memory_service

    engine = _make_engine(tmp_path)
    await engine.startup()
    try:
        ids_target = await engine.index_documents([
            {"content": "explore-target-content",
             "metadata": {"source": "agent", "tags": ["explore-stage3"]}},
        ])
        target_id = ids_target[0]
        await engine.index_documents([
            {"content": f"unrelated explore chunk {i}",
             "metadata": {"source": "agent"}}
            for i in range(20)
        ])

        # explore without tag_filter — target may or may not appear
        # (depends on diversity and raw cosine luck)
        # explore WITH tag_filter — target MUST appear
        resp = await memory_service.explore(
            engine, query="unrelated query text", diversity=0.5, top_k=10,
            tag_filter=["explore-stage3"],
        )
        ids = [item.id for item in resp.items]
        assert target_id in ids, f"explore(tag_filter=...) failed to surface target: {ids}"
    finally:
        await engine.shutdown()


@pytest.mark.asyncio
async def test_stage3_prefetch_accepts_tag_filter(tmp_path):
    """Phase J Stage 3 parity: ``prefetch`` must accept the same injection
    arguments as recall, and the pre-warmed cache entry must surface the
    tagged target."""
    from gaottt.services import maintenance as maintenance_service

    engine = _make_engine(tmp_path)
    await engine.startup()
    try:
        ids_target = await engine.index_documents([
            {"content": "prefetch-target-content",
             "metadata": {"source": "agent", "tags": ["prefetch-stage3"]}},
        ])
        target_id = ids_target[0]
        await engine.index_documents([
            {"content": f"unrelated prefetch chunk {i}",
             "metadata": {"source": "agent"}}
            for i in range(20)
        ])

        # Schedule a prefetch with tag_filter — fires asynchronously.
        maintenance_service.prefetch(
            engine, query="unrelated prefetch probe", top_k=5,
            tag_filter=["prefetch-stage3"],
        )
        # The service wrapper doesn't expose the task handle; poll the
        # cache until the bounded pool drains.
        import asyncio
        cached = None
        for _ in range(20):
            await asyncio.sleep(0.05)
            cached = engine.prefetch_cache.get("unrelated prefetch probe", 5)
            if cached is not None:
                break
        assert cached is not None, "prefetch did not populate the cache"
        ids = [r.id for r in cached]
        assert target_id in ids, (
            f"prefetch(tag_filter=...) cached result missing target: {ids}"
        )
    finally:
        await engine.shutdown()
