"""Integration tests — ``services.memory.save_candidates`` (engine round-trip).

Stop-hook companion to ambient_recall. Reuses ``auto_remember`` for
heuristic extraction and ``_pick_persona`` for the optional persona slot;
this test confirms the end-to-end shape via a real engine + StubEmbedder.
"""
from __future__ import annotations

import pytest

from gaottt.config import GaOTTTConfig
from gaottt.core.engine import GaOTTTEngine
from gaottt.index.faiss_index import FaissIndex
from gaottt.services import memory as memory_service
from gaottt.store.cache import CacheLayer
from gaottt.store.sqlite_store import SqliteStore
from tests.integration.test_engine_archive_ttl import StubEmbedder


@pytest.fixture
async def engine(tmp_path):
    cfg = GaOTTTConfig(
        embedding_dim=32,
        data_dir=str(tmp_path),
        db_path=str(tmp_path / "gaottt.db"),
        faiss_index_path=str(tmp_path / "gaottt.faiss"),
        flush_interval_seconds=999.0,
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


async def test_save_candidates_extracts_from_transcript(engine):
    """auto_remember heuristic surfaces typical save-worthy lines (user
    preferences, failures) — save_candidates is the same heuristic plus
    the block-formatting wrapper."""
    transcript = (
        "[user] pip 禁止。uv を使ってください\n"
        "[assistant] 了解、uv で進めます\n"
        "[user] 失敗: numpy に or 演算子で ValueError\n"
        "[assistant] 原因は bool 変換の曖昧さでした\n"
    )
    out = await memory_service.save_candidates(
        engine, transcript=transcript, max_candidates=5,
    )
    assert out.count >= 1
    contents = " ".join(c.content for c in out.candidates)
    # Either of the two distinctive lines should land in candidates.
    assert ("uv" in contents) or ("ValueError" in contents)


async def test_save_candidates_returns_empty_on_chatter(engine):
    """Greetings / acknowledgements should produce no candidates — the
    sentinel path the Stop hook keys on to stay silent."""
    transcript = "\n".join(["ok", "thanks", "了解", "👍"])
    out = await memory_service.save_candidates(engine, transcript=transcript)
    assert out.count == 0
    assert out.candidates == []


async def test_save_candidates_does_not_persist(engine):
    """Observation layer only — the service must NOT call remember as a
    side effect. The mass-entry stays volitional (Articulation as Carrier)."""
    transcript = "[user] 重要な決定: テストでは uv を使うこと\n"
    await memory_service.save_candidates(engine, transcript=transcript)
    states = await engine.store.get_all_node_states()
    assert states == []


async def test_save_candidates_persona_off_when_requested(engine):
    """``include_persona=False`` skips the persona pick entirely — used when
    ambient_recall already injects a persona slot and the Stop block would
    duplicate it."""
    transcript = "[user] 重要な決定: 観測層と物理層を分離する\n"
    out = await memory_service.save_candidates(
        engine, transcript=transcript, include_persona=False,
    )
    assert out.persona is None
