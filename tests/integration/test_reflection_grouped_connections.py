"""Observation Apparatus Refinement Stage 4 — invariant: grouping does
not change co-occurrence counts or edge weights.

End-to-end check that ``reflect(aspect="connections")`` after Stage 4
returns the same total edges and the same per-edge weights as the
pre-Stage 4 path. Bucket labels are added; nothing else moves.
"""

from __future__ import annotations

import pytest

from gaottt.services import memory as memory_service
from gaottt.services.reflection import connections as connections_service
from tests.integration.test_engine_ambient_recall import _make_engine


@pytest.mark.asyncio
async def test_grouping_is_lossless_bit_exact_weights(tmp_path):
    """Edge weights survive bucket labelling unchanged."""
    engine = _make_engine(tmp_path)
    await engine.startup()
    try:
        for i in range(4):
            await memory_service.remember(
                engine, content=f"agent note seed {i}", source="agent",
            )
        # Make a few recalls so cooccurrence edges populate.
        for q in ("agent note seed", "note seed agent", "seed"):
            await memory_service.recall(engine, query=q, top_k=4)
        resp = await connections_service(engine, limit=20)
        # Every item now has a bucket label (Stage 4 invariant).
        for e in resp.items:
            assert e.bucket in {"persona", "agent_user", "ingest"}
        # And the underlying edge weights match what the cache stores.
        cache_edges = {
            (min(e.src, e.dst), max(e.src, e.dst)): e.weight
            for e in engine.cache.get_all_edges()
        }
        for item in resp.items:
            key = (min(item.src, item.dst), max(item.src, item.dst))
            assert key in cache_edges
            assert cache_edges[key] == item.weight
    finally:
        await engine.shutdown()


@pytest.mark.asyncio
async def test_persona_pair_classified_persona(tmp_path):
    """A value↔intention edge lands in the persona bucket."""
    engine = _make_engine(tmp_path)
    await engine.startup()
    try:
        v = await memory_service.remember(
            engine, content="value: literal design", source="value",
        )
        i = await memory_service.remember(
            engine, content="intention: ship Observation Refinement",
            source="intention",
        )
        # Force a cooccurrence edge between them.
        engine.cache.set_edge(v.id, i.id, weight=1.0)
        resp = await connections_service(engine, limit=20)
        match = [
            e for e in resp.items
            if {e.src, e.dst} == {v.id, i.id}
        ]
        assert match, "expected the value↔intention edge to surface"
        assert match[0].bucket == "persona"
    finally:
        await engine.shutdown()


@pytest.mark.asyncio
async def test_flag_off_returns_unbucketed_items(tmp_path):
    """Fix #5 — connections_grouped_by_source=False is a real rollback knob.

    With the flag False, ``connections()`` returns items with bucket=None,
    and ``format_reflect_connections`` falls back to the legacy flat layout.
    """
    from gaottt.services import formatters
    engine = _make_engine(tmp_path, connections_grouped_by_source=False)
    await engine.startup()
    try:
        a = await memory_service.remember(
            engine, content="value statement A", source="value",
        )
        b = await memory_service.remember(
            engine, content="intention statement B", source="intention",
        )
        engine.cache.set_edge(a.id, b.id, weight=1.0)
        resp = await connections_service(engine, limit=5)
        # Every item has bucket=None when the flag is off.
        for e in resp.items:
            assert e.bucket is None
        rendered = formatters.format_reflect_connections(resp)
        # Legacy flat header is the only heading — no '▼ persona' etc.
        assert "Strongest connections" in rendered
        assert "▼ persona" not in rendered
        assert "▼ agent" not in rendered
        assert "▼ file" not in rendered
    finally:
        await engine.shutdown()


@pytest.mark.asyncio
async def test_file_pair_classified_ingest(tmp_path):
    """A file↔file edge lands in the ingest bucket."""
    engine = _make_engine(tmp_path)
    await engine.startup()
    try:
        a = await memory_service.remember(
            engine, content="chunk A of a file", source="file",
        )
        b = await memory_service.remember(
            engine, content="chunk B of the same file", source="file",
        )
        engine.cache.set_edge(a.id, b.id, weight=8.0)
        resp = await connections_service(engine, limit=20)
        match = [
            e for e in resp.items
            if {e.src, e.dst} == {a.id, b.id}
        ]
        assert match
        assert match[0].bucket == "ingest"
    finally:
        await engine.shutdown()
