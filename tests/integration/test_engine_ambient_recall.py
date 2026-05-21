"""Ambient Recall Enrichment — ambient_recall() service (integration).

``services.memory.ambient_recall`` composes a structured multi-slot block out
of ONE passive recall: ① direct hits + ② gravitational-lensing pick +
③ provenance metadata, ④ derived_from/supersedes reasoning, ⑤ contradicts
tension, ⑥ persona grounding. Verified end to end through a real engine
(deterministic StubEmbedder).
"""
from __future__ import annotations

import pytest

from gaottt.config import GaOTTTConfig
from gaottt.core.engine import GaOTTTEngine
from gaottt.index.bm25_index import BM25Index
from gaottt.index.faiss_index import FaissIndex
from gaottt.services import memory as memory_service
from gaottt.store.cache import CacheLayer
from gaottt.store.sqlite_store import SqliteStore
from tests.integration.test_engine_query_kick import StubEmbedder


def _make_engine(tmp_path, *, bm25: bool = False):
    """Build a Stub-backed engine. ``bm25=True`` wires the word-BM25 ambient
    gate index and lowers ``ambient_bm25_min_score`` so the gate is
    exercisable on a tiny corpus (the 32.0 default is calibrated for a
    ~32k-doc corpus). The gate index here uses the default trigram tokenizer
    — the test drives the gate *wiring*, not the Sudachi tokenizer. With
    ``bm25=False`` there is no gate index, so ``ambient_recall`` falls back to
    the virtual_score gate — that path is what the other tests drive."""
    config = GaOTTTConfig(
        embedding_dim=64,
        data_dir=str(tmp_path),
        db_path=str(tmp_path / "test.db"),
        faiss_index_path=str(tmp_path / "test.faiss"),
        genesis_kick_enabled=False,
        dream_enabled=False,
        faiss_save_interval_seconds=0.0,
        flush_interval_seconds=0.05,
        ambient_bm25_min_score=0.01,
    )
    embedder = StubEmbedder(dim=config.embedding_dim)
    return GaOTTTEngine(
        config=config,
        embedder=embedder,
        faiss_index=FaissIndex(dimension=config.embedding_dim),
        cache=CacheLayer(
            flush_interval=config.flush_interval_seconds,
            flush_threshold=config.flush_threshold,
        ),
        store=SqliteStore(db_path=config.db_path),
        ambient_gate_index=BM25Index() if bm25 else None,
    )


@pytest.mark.asyncio
async def test_ambient_recall_returns_structured_block_with_provenance(tmp_path):
    """① direct hits + ③ provenance metadata (source / certainty / age)."""
    engine = _make_engine(tmp_path)
    await engine.startup()
    try:
        for i in range(5):
            await memory_service.remember(
                engine, content=f"ambient probe doc {i}", source="agent",
            )
        resp = await memory_service.ambient_recall(
            engine, "ambient probe", direct_k=2,
        )
        assert resp.count >= 1
        assert 1 <= len(resp.direct) <= 2
        m = resp.direct[0]
        assert m.source == "agent"
        assert m.certainty is not None          # ③ from NodeState
        assert m.age_days is not None and m.age_days >= 0.0
        assert m.virtual_score > 0.0
        assert m.content                        # excerpt non-empty
    finally:
        await engine.shutdown()


@pytest.mark.asyncio
async def test_ambient_recall_virtual_score_gate_fallback(tmp_path):
    """Fallback gate — with no BM25 index, ambient_recall gates on
    virtual_score; min_score above any achievable score → empty."""
    engine = _make_engine(tmp_path)  # bm25=False → virtual_score fallback
    await engine.startup()
    try:
        for i in range(3):
            await memory_service.remember(
                engine, content=f"gate doc {i}", source="agent",
            )
        resp = await memory_service.ambient_recall(
            engine, "gate doc", direct_k=2, min_score=0.999,
        )
        assert resp.count == 0
        assert resp.direct == []
        assert resp.lensing is None
    finally:
        await engine.shutdown()


@pytest.mark.asyncio
async def test_ambient_recall_bm25_lexical_gate(tmp_path):
    """BM25 lexical gate — a prompt sharing terms with the corpus passes; a
    prompt with no lexical overlap (disjoint vocabulary → BM25 0) is
    suppressed even though dense recall would still return its 3 nearest."""
    engine = _make_engine(tmp_path, bm25=True)
    await engine.startup()
    try:
        for i in range(4):
            await memory_service.remember(
                engine,
                content=f"gravitational wave propagation seed pool {i}",
                source="agent",
            )
        on = await memory_service.ambient_recall(
            engine, "gravitational wave propagation", direct_k=2,
        )
        assert on.count >= 1, "lexically-overlapping prompt should inject"
        off = await memory_service.ambient_recall(
            engine, "りんごジュースの値段はいくらですか", direct_k=2,
        )
        assert off.count == 0, "disjoint-vocabulary prompt should be gated out"
    finally:
        await engine.shutdown()


@pytest.mark.asyncio
async def test_ambient_recall_reasoning_chain(tmp_path):
    """Stage 2 ④ — a derived_from edge surfaces as `because` on the child."""
    engine = _make_engine(tmp_path)
    await engine.startup()
    try:
        ids = []
        for i in range(4):
            r = await memory_service.remember(
                engine, content=f"reasoning node {i}", source="agent",
            )
            ids.append(r.id)
        await engine.relate(
            src_id=ids[0], dst_id=ids[1], edge_type="derived_from",
        )
        resp = await memory_service.ambient_recall(
            engine, "reasoning node", direct_k=4,
        )
        because = next(
            (m.because for m in resp.direct if m.id == ids[0]), None,
        )
        assert because is not None, "derived_from parent should populate `because`"
        assert "reasoning node 1" in because
    finally:
        await engine.shutdown()


@pytest.mark.asyncio
async def test_ambient_recall_tension_flag(tmp_path):
    """Stage 2 ⑤ — a contradicts edge surfaces as a tension caution."""
    engine = _make_engine(tmp_path)
    await engine.startup()
    try:
        ids = []
        for i in range(4):
            r = await memory_service.remember(
                engine, content=f"tension node {i}", source="agent",
            )
            ids.append(r.id)
        await engine.relate(
            src_id=ids[0], dst_id=ids[1], edge_type="contradicts",
        )
        resp = await memory_service.ambient_recall(
            engine, "tension node", direct_k=4,
        )
        assert resp.tensions, "contradicts edge should surface a tension"
        pair = {resp.tensions[0].memory_id, resp.tensions[0].contradicts_id}
        assert pair == {ids[0], ids[1]}
        # contradicts is bidirectional but the pair is de-duplicated
        assert len(resp.tensions) == 1
    finally:
        await engine.shutdown()


@pytest.mark.asyncio
async def test_ambient_recall_persona_slot(tmp_path):
    """Stage 3 ⑥ — a declared value surfaces in the persona slot."""
    engine = _make_engine(tmp_path)
    await engine.startup()
    try:
        await memory_service.remember(
            engine, content="最も literal な解を選ぶ", source="value",
        )
        for i in range(3):
            await memory_service.remember(
                engine, content=f"persona probe {i}", source="agent",
            )
        resp = await memory_service.ambient_recall(
            engine, "persona probe", direct_k=2,
        )
        assert resp.persona is not None
        assert resp.persona.kind == "value"
        assert "literal" in resp.persona.content
    finally:
        await engine.shutdown()


@pytest.mark.asyncio
async def test_ambient_recall_passive_does_not_perturb_field(tmp_path):
    """ambient_recall is passive end to end — mass is not moved (it reuses the
    passive recall path)."""
    engine = _make_engine(tmp_path)
    await engine.startup()
    try:
        for i in range(5):
            await memory_service.remember(
                engine, content=f"passive ambient {i}", source="agent",
            )
        ids = [
            r.id for r in (await engine.query(text="passive ambient", top_k=5))
        ]
        mass_before = {
            nid: float(engine.cache.get_node(nid).mass) for nid in ids
        }
        for _ in range(5):
            await memory_service.ambient_recall(engine, "passive ambient")
        mass_after = {
            nid: float(engine.cache.get_node(nid).mass) for nid in ids
        }
        assert mass_after == mass_before, "ambient_recall must not perturb mass"
    finally:
        await engine.shutdown()
