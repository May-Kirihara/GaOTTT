"""Tier 3 — Phase O Stage 1 ``forced`` flag visibility under tag_filter.

When ``recall(tag_filter=[...])`` injects nodes that wouldn't naturally
surface (Phase J Stage 2), the per-item score breakdown carries a
``[forced]`` flag so the caller can tell *I asked for this* from *the
wave found this*. GLM's 2026-05-15 playthrough specifically called out
that this flag is what makes sparse-class visibility honest — without
it, force-injection looks indistinguishable from a strong semantic hit.

Contract: a deliberately orthogonal query (semantically far from the
filtered tag) + ``tag_filter=[that_tag]`` → at least one result shows
``forced`` in its breakdown flags. Catches a regression that drops the
``forced_inclusion`` propagation from engine.query into ScoreBreakdown.

The mirror contract (no tag_filter → no ``forced`` flag) is tested in
parallel so the flag isn't accidentally always-on.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from gaottt.server import mcp_server as srv
from tests.perf._helpers import make_engine


GOLDEN_DIR = Path(__file__).parent / "golden_corpus"
CHUNKS_PATH = GOLDEN_DIR / "synthetic_chunks.jsonl"

# Orthogonal pair: the query talks about cooking, the tag filter asks for
# the eleventy (static-site) cluster. Without the filter, eleventy chunks
# would not surface for this query.
ORTHOGONAL_QUERY = "carbonara guanciale eggs pasta"
ORTHOGONAL_TAG = "eleventy"


def _load_chunks() -> list[dict]:
    with CHUNKS_PATH.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


@pytest.fixture
async def engine_with_corpus(tmp_path, monkeypatch):
    eng = make_engine(tmp_path)
    await eng.startup()
    chunks = _load_chunks()
    documents = [
        {
            "content": c["content"],
            "metadata": {
                "source": c.get("source", "synthetic"),
                "tags": c.get("tags", []),
                "golden_fixture_id": c["id"],
            },
        }
        for c in chunks
    ]
    await eng.index_documents(documents)
    monkeypatch.setattr(srv, "_engine", eng)
    try:
        yield eng
    finally:
        monkeypatch.setattr(srv, "_engine", None)
        await eng.shutdown()


async def test_tag_filter_surfaces_forced_flag(engine_with_corpus):
    """tag_filter on an orthogonal query → ``forced`` appears in breakdown flags."""
    out = await srv.recall(
        query=ORTHOGONAL_QUERY, top_k=5, tag_filter=[ORTHOGONAL_TAG],
    )
    assert "breakdown: cos=" in out, (
        "Score breakdown missing — Phase O Stage 1 trailer broke. "
        f"Got: {out[:500]!r}"
    )
    assert "forced" in out, (
        f"tag_filter=[{ORTHOGONAL_TAG!r}] + orthogonal query "
        f"{ORTHOGONAL_QUERY!r} should force-inject at least one node, "
        f"flagged ``forced`` in the breakdown. "
        f"Got: {out[:800]!r}"
    )


async def test_plain_recall_has_no_forced_flag(engine_with_corpus):
    """Mirror contract — without tag_filter, the ``forced`` flag stays off.

    Guards against a regression where ``forced_inclusion=True`` leaks for
    every result (which would defeat the purpose of the signal).
    """
    out = await srv.recall(
        query="static-site eleventy pipeline",  # natural semantic match
        top_k=5,
    )
    assert "breakdown: cos=" in out, "Stage 1 trailer missing"
    # The breakdown line is the only place ``forced`` appears in recall output.
    # If the flag fires here, our orthogonal-query test isn't meaningful.
    breakdown_lines = [
        line for line in out.splitlines() if "breakdown: cos=" in line
    ]
    forced_lines = [line for line in breakdown_lines if "forced" in line]
    assert not forced_lines, (
        "Plain recall (no tag_filter) leaked ``forced`` flag — Stage 1 "
        f"signal is meaningless. Offending lines: {forced_lines}"
    )
