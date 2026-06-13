"""Observation Apparatus Refinement Stage 4 — invariant: grouping does
not change co-occurrence counts or edge weights.

End-to-end check that ``reflect(aspect="connections")`` after Stage 4
returns the same total edges and the same per-edge weights as the
pre-Stage 4 path. Bucket labels are added; nothing else moves.
"""

from __future__ import annotations

import pytest

from gaottt.services import formatters
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


# ----- Bucket filter + grouping flag interaction -----

@pytest.mark.asyncio
async def test_grouping_off_bucket_ignored(tmp_path):
    """connections_grouped_by_source=False + bucket="persona": the filter
    is structurally meaningless without classification, so it must NOT be
    applied. filter_bucket stays None and the result is the legacy
    all-buckets top-N."""
    engine = _make_engine(tmp_path, connections_grouped_by_source=False)
    await engine.startup()
    try:
        v = await memory_service.remember(
            engine, content="value statement", source="value",
        )
        i = await memory_service.remember(
            engine, content="intention statement", source="intention",
        )
        fa = await memory_service.remember(
            engine, content="file chunk A", source="file",
        )
        fb = await memory_service.remember(
            engine, content="file chunk B", source="file",
        )
        engine.cache.set_edge(v.id, i.id, weight=1.0)
        engine.cache.set_edge(fa.id, fb.id, weight=100.0)
        resp = await connections_service(engine, limit=10, bucket="persona")
        # Filter was NOT applied — observability fields stay None.
        assert resp.filter_bucket is None
        assert resp.filtered_total is None
        # bucket labels are also None (grouping off).
        for e in resp.items:
            assert e.bucket is None
        # And the high-weight ingest edge DOES appear (no filter).
        top_pair_ids = set()
        for item in resp.items:
            top_pair_ids.add(item.src)
            top_pair_ids.add(item.dst)
        assert fa.id in top_pair_ids
        assert fb.id in top_pair_ids
    finally:
        await engine.shutdown()


@pytest.mark.asyncio
async def test_formatter_shows_filter_header_when_bucket_set(tmp_path):
    """format_reflect_connections prepends '[filtered: ... bucket, N total]'
    to the header when filter_bucket is set, while keeping the
    'Strongest connections' prefix intact."""
    from gaottt.services import formatters
    engine = _make_engine(tmp_path)
    await engine.startup()
    try:
        v = await memory_service.remember(
            engine, content="value statement", source="value",
        )
        i = await memory_service.remember(
            engine, content="intention statement", source="intention",
        )
        engine.cache.set_edge(v.id, i.id, weight=1.0)
        resp = await connections_service(engine, limit=10, bucket="persona")
        rendered = formatters.format_reflect_connections(resp)
        assert "Strongest connections" in rendered
        assert "[filtered: persona bucket" in rendered
    finally:
        await engine.shutdown()


@pytest.mark.asyncio
async def test_formatter_no_filter_header_when_bucket_none(tmp_path):
    """format_reflect_connections does NOT emit '[filtered:' when
    filter_bucket is None (default / grouping-off path)."""
    from gaottt.services import formatters
    engine = _make_engine(tmp_path)
    await engine.startup()
    try:
        a = await memory_service.remember(
            engine, content="agent note", source="agent",
        )
        b = await memory_service.remember(
            engine, content="user note", source="user",
        )
        engine.cache.set_edge(a.id, b.id, weight=1.0)
        resp = await connections_service(engine, limit=10)
        rendered = formatters.format_reflect_connections(resp)
        assert "Strongest connections" in rendered
        assert "[filtered:" not in rendered
    finally:
        await engine.shutdown()


# ---------------------------------------------------------------------------
# Bucket filter parameter — reflect(aspect="connections", bucket=...)
#
# The core filter behaviour (persona / ingest / agent_user / None / invalid /
# filter-before-top-N / observability fields / empty result) is covered in
# ``tests/unit/test_connection_bucket.py``. The tests below cover the aspects
# that need the grouped-connections config flag or the formatter: grouping-off
# suppression, and the ``[filtered: ...]`` header annotation.
# ---------------------------------------------------------------------------

async def _seed_three_buckets(engine):
    """Seed one edge per bucket (persona / agent_user / ingest).

    Returns a dict with the created node ids so tests can assert presence
    or absence after filtering. Weights are chosen so the ingest edge is
    the heaviest — this mirrors the production pathology the filter fixes.
    """
    v = await memory_service.remember(engine, content="value: design lens", source="value")
    i = await memory_service.remember(engine, content="intention: ship filter", source="intention")
    engine.cache.set_edge(v.id, i.id, weight=1.0)  # persona, low weight

    a = await memory_service.remember(engine, content="agent note", source="agent")
    u = await memory_service.remember(engine, content="user note", source="user")
    engine.cache.set_edge(a.id, u.id, weight=3.0)  # agent_user, mid weight

    f1 = await memory_service.remember(engine, content="file chunk A", source="file")
    f2 = await memory_service.remember(engine, content="file chunk B", source="file")
    engine.cache.set_edge(f1.id, f2.id, weight=10.0)  # ingest, high weight

    return {
        "persona": (v.id, i.id),
        "agent_user": (a.id, u.id),
        "ingest": (f1.id, f2.id),
    }


@pytest.mark.asyncio
async def test_formatter_no_filter_header_when_grouping_off(tmp_path):
    """grouping_on=False also suppresses the filter annotation."""
    engine = _make_engine(tmp_path, connections_grouped_by_source=False)
    await engine.startup()
    try:
        await _seed_three_buckets(engine)
        resp = await connections_service(engine, limit=10, bucket="persona")
        rendered = formatters.format_reflect_connections(resp)
        assert "[filtered:" not in rendered
    finally:
        await engine.shutdown()


@pytest.mark.asyncio
async def test_formatter_empty_result_filter_header(tmp_path):
    """QA #1 — bucket='persona' with zero persona edges: the formatter renders
    the empty-result header with the filter annotation intact."""
    engine = _make_engine(tmp_path)
    await engine.startup()
    try:
        f1 = await memory_service.remember(engine, content="file A", source="file")
        f2 = await memory_service.remember(engine, content="file B", source="file")
        engine.cache.set_edge(f1.id, f2.id, weight=5.0)

        resp = await connections_service(engine, limit=10, bucket="persona")
        assert resp.items == []
        assert resp.filter_bucket == "persona"
        assert resp.filtered_total == 0

        rendered = formatters.format_reflect_connections(resp)
        assert "Strongest connections (0 shown)" in rendered
        assert "[filtered: persona bucket, 0 total]" in rendered
    finally:
        await engine.shutdown()
