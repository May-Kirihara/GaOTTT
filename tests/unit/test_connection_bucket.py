"""Observation Apparatus Refinement Stage 4 — bucket classifier.

Pin the source → bucket mapping. The classifier is force-blind and
mass-blind by construction; it only routes display rows. These tests
also document the rule for future readers.

Bucket filter behaviour (connections() ``bucket`` parameter) is covered
in the second half of this module — the filter runs BEFORE the
weight-sorted top-N cut so a high-weight ingest cohort cannot crowd out
low-weight persona / agent_user pairs.
"""

from __future__ import annotations

import pytest

from gaottt.services import memory as memory_service
from gaottt.services.reflection import _connection_bucket, connections
from tests.integration.test_engine_ambient_recall import _make_engine


def test_two_personas_become_persona_bucket() -> None:
    assert _connection_bucket("value", "intention") == "persona"
    assert _connection_bucket("commitment", "value") == "persona"


def test_file_endpoint_routes_to_ingest_bucket() -> None:
    assert _connection_bucket("file", "agent") == "ingest"
    assert _connection_bucket("agent", "file") == "ingest"
    assert _connection_bucket("file", "file") == "ingest"


def test_tweet_or_csv_endpoint_also_ingest() -> None:
    assert _connection_bucket("tweet", "agent") == "ingest"
    assert _connection_bucket("csv", "user") == "ingest"
    assert _connection_bucket("claude-code", "agent") == "ingest"


def test_chat_export_endpoints_route_to_ingest() -> None:
    """Fix #2 — ChatGPT and Claude.ai web export sources (loader.py L109/L119)
    must land in the ingest bucket so same-conversation chunk co-occurrence
    does not crowd out cross-domain pairs in the dialogue bucket."""
    assert _connection_bucket("openai", "openai") == "ingest"
    assert _connection_bucket("openai", "agent") == "ingest"
    assert _connection_bucket("claude-web", "claude-web") == "ingest"
    assert _connection_bucket("claude-web", "agent") == "ingest"
    assert _connection_bucket("chat-export", "agent") == "ingest"


def test_agent_user_is_default_for_dialogue() -> None:
    assert _connection_bucket("agent", "agent") == "agent_user"
    assert _connection_bucket("user", "agent") == "agent_user"
    assert _connection_bucket("hypothesis", "note") == "agent_user"


def test_persona_plus_dialogue_is_agent_user() -> None:
    """A persona endpoint paired with a dialogue endpoint does NOT count as
    persona — the bucket is reserved for value↔value/intention pairs."""
    assert _connection_bucket("value", "agent") == "agent_user"
    assert _connection_bucket("intention", "note") == "agent_user"


def test_none_endpoint_falls_through_to_dialogue() -> None:
    """An unknown source is treated as dialogue, not as ingest."""
    assert _connection_bucket(None, None) == "agent_user"
    assert _connection_bucket("agent", None) == "agent_user"


# ----- Bucket filter on connections() -----
# These exercise the ``bucket`` parameter of ``connections()``: the filter
# is applied BEFORE the weight-sorted top-N selection, so a low-weight
# persona edge surfaces even when high-weight ingest edges exist.


@pytest.mark.asyncio
async def test_bucket_persona_returns_only_persona_edges(tmp_path):
    """bucket="persona" surfaces persona edges even when ingest edges
    carry a higher weight (the core filter-before-top-N guarantee)."""
    engine = _make_engine(tmp_path)
    await engine.startup()
    try:
        v = await memory_service.remember(
            engine, content="value: ship the filter", source="value",
        )
        i = await memory_service.remember(
            engine, content="intention: filter before top-N", source="intention",
        )
        fa = await memory_service.remember(
            engine, content="file chunk A", source="file",
        )
        fb = await memory_service.remember(
            engine, content="file chunk B", source="file",
        )
        # Ingest edge has the HIGHER weight — without the filter it would
        # dominate the top-N and the persona edge would never show.
        engine.cache.set_edge(fa.id, fb.id, weight=100.0)
        engine.cache.set_edge(v.id, i.id, weight=1.0)
        resp = await connections(engine, limit=10, bucket="persona")
        assert resp.filter_bucket == "persona"
        assert resp.filtered_total == 1
        # Every returned edge must be the persona pair (v ↔ i).
        for item in resp.items:
            assert {item.src, item.dst} == {v.id, i.id}
        # The high-weight ingest edge must NOT appear.
        for item in resp.items:
            assert fa.id not in {item.src, item.dst}
            assert fb.id not in {item.src, item.dst}
    finally:
        await engine.shutdown()


@pytest.mark.asyncio
async def test_bucket_ingest_returns_only_ingest_edges(tmp_path):
    engine = _make_engine(tmp_path)
    await engine.startup()
    try:
        fa = await memory_service.remember(
            engine, content="file chunk A", source="file",
        )
        fb = await memory_service.remember(
            engine, content="file chunk B", source="file",
        )
        a = await memory_service.remember(
            engine, content="agent note", source="agent",
        )
        b = await memory_service.remember(
            engine, content="user note", source="user",
        )
        engine.cache.set_edge(fa.id, fb.id, weight=1.0)
        engine.cache.set_edge(a.id, b.id, weight=100.0)
        resp = await connections(engine, limit=10, bucket="ingest")
        assert resp.filter_bucket == "ingest"
        for item in resp.items:
            assert item.bucket == "ingest"
    finally:
        await engine.shutdown()


@pytest.mark.asyncio
async def test_bucket_agent_user_returns_only_agent_user_edges(tmp_path):
    engine = _make_engine(tmp_path)
    await engine.startup()
    try:
        a = await memory_service.remember(
            engine, content="agent note", source="agent",
        )
        b = await memory_service.remember(
            engine, content="user note", source="user",
        )
        fa = await memory_service.remember(
            engine, content="file chunk", source="file",
        )
        engine.cache.set_edge(a.id, b.id, weight=1.0)
        engine.cache.set_edge(a.id, fa.id, weight=100.0)
        resp = await connections(engine, limit=10, bucket="agent_user")
        assert resp.filter_bucket == "agent_user"
        for item in resp.items:
            assert item.bucket == "agent_user"
    finally:
        await engine.shutdown()


@pytest.mark.asyncio
async def test_bucket_none_returns_all_buckets(tmp_path):
    """bucket=None (default) is the legacy path: no filter applied."""
    engine = _make_engine(tmp_path)
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
        engine.cache.set_edge(fa.id, fb.id, weight=2.0)
        resp = await connections(engine, limit=10, bucket=None)
        assert resp.filter_bucket is None
        assert resp.filtered_total is None
        # Both persona and ingest edges appear.
        buckets_seen = {e.bucket for e in resp.items}
        assert "persona" in buckets_seen
        assert "ingest" in buckets_seen
    finally:
        await engine.shutdown()


@pytest.mark.asyncio
async def test_invalid_bucket_raises_value_error(tmp_path):
    """An unrecognised bucket value raises ValueError at the service layer
    (MCP callers bypass static typing, so the runtime guard is load-bearing)."""
    engine = _make_engine(tmp_path)
    await engine.startup()
    try:
        with pytest.raises(ValueError, match="Invalid bucket"):
            await connections(engine, limit=5, bucket="personna")
    finally:
        await engine.shutdown()


@pytest.mark.asyncio
async def test_filter_bucket_and_filtered_total_set_correctly(tmp_path):
    """Observability fields: filter_bucket + filtered_total reflect the
    filter that was actually applied."""
    engine = _make_engine(tmp_path)
    await engine.startup()
    try:
        v = await memory_service.remember(
            engine, content="value A", source="value",
        )
        i = await memory_service.remember(
            engine, content="intention A", source="intention",
        )
        v2 = await memory_service.remember(
            engine, content="value B", source="value",
        )
        i2 = await memory_service.remember(
            engine, content="intention B", source="intention",
        )
        fa = await memory_service.remember(
            engine, content="file chunk", source="file",
        )
        engine.cache.set_edge(v.id, i.id, weight=1.0)
        engine.cache.set_edge(v2.id, i2.id, weight=2.0)
        engine.cache.set_edge(v.id, fa.id, weight=3.0)  # NOT persona (file endpoint)
        resp = await connections(engine, limit=10, bucket="persona")
        assert resp.filter_bucket == "persona"
        # Two persona-persona edges exist in the pool.
        assert resp.filtered_total == 2
        # total counts ALL edges regardless of filter.
        assert resp.total >= 3
    finally:
        await engine.shutdown()


@pytest.mark.asyncio
async def test_filter_before_top_n_surfaces_low_weight_persona(tmp_path):
    """The defining test: with limit=1 and a high-weight ingest edge present,
    bucket="persona" must still surface the persona edge — proving the filter
    runs BEFORE the top-N cut, not after."""
    engine = _make_engine(tmp_path)
    await engine.startup()
    try:
        v = await memory_service.remember(
            engine, content="persona value", source="value",
        )
        i = await memory_service.remember(
            engine, content="persona intention", source="intention",
        )
        fa = await memory_service.remember(
            engine, content="file A", source="file",
        )
        fb = await memory_service.remember(
            engine, content="file B", source="file",
        )
        engine.cache.set_edge(fa.id, fb.id, weight=999.0)  # would win top-1
        engine.cache.set_edge(v.id, i.id, weight=0.5)
        resp = await connections(engine, limit=1, bucket="persona")
        assert len(resp.items) == 1
        pair = {resp.items[0].src, resp.items[0].dst}
        assert pair == {v.id, i.id}
    finally:
        await engine.shutdown()


@pytest.mark.asyncio
async def test_bucket_filter_with_empty_result(tmp_path):
    """Filtering to a bucket with zero matching edges returns an empty item
    list but still reports filter_bucket and filtered_total=0."""
    engine = _make_engine(tmp_path)
    await engine.startup()
    try:
        fa = await memory_service.remember(
            engine, content="only file chunk A", source="file",
        )
        fb = await memory_service.remember(
            engine, content="only file chunk B", source="file",
        )
        engine.cache.set_edge(fa.id, fb.id, weight=5.0)
        resp = await connections(engine, limit=10, bucket="persona")
        assert resp.filter_bucket == "persona"
        assert resp.filtered_total == 0
        assert resp.items == []
        # total still reflects the unfiltered pool.
        assert resp.total >= 1
    finally:
        await engine.shutdown()
