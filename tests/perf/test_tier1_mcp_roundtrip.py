"""Tier 1 smoke — every MCP tool is callable and returns a non-empty string.

Two checks:
  1. The MCP server exposes exactly 26 tools (matches the documented surface).
  2. Each tool runs end-to-end with sane args and returns a non-empty
     string. IDs from earlier calls thread into later calls so we exercise
     the realistic shape of a session.

Patches ``gaottt.server.mcp_server._engine`` with a Stub-embedder engine
so the tools call the real service layer + formatters but never touch a
production DB.
"""
from __future__ import annotations

import inspect
import re
import tempfile
from pathlib import Path

import pytest

from gaottt.server import mcp_server as srv
from tests.perf._helpers import make_engine


# Expected tool surface. Update this list intentionally if a tool is added
# or removed — the count is a contract.
EXPECTED_TOOLS = {
    "remember", "revalidate", "forget", "restore", "recall", "ambient_recall",
    "explore", "reflect", "prefetch", "prefetch_status", "relate", "unrelate",
    "get_relations", "commit", "start", "complete", "abandon", "depend",
    "declare_value", "declare_intention", "declare_commitment",
    "inherit_persona", "merge", "compact", "auto_remember", "ingest",
}


@pytest.fixture
async def engine_singleton(tmp_path, monkeypatch):
    eng = make_engine(tmp_path)
    await eng.startup()
    monkeypatch.setattr(srv, "_engine", eng)
    try:
        yield eng
    finally:
        monkeypatch.setattr(srv, "_engine", None)
        await eng.shutdown()


def test_mcp_surface_count_matches_expected():
    """The 26-tool surface is a contract — additions/removals are intentional."""
    source = Path(srv.__file__).read_text(encoding="utf-8")
    decorator_count = len(re.findall(r"^@mcp\.tool\(\)\s*$", source, re.MULTILINE))
    assert decorator_count == 26, (
        f"Found {decorator_count} @mcp.tool() decorators; expected 26"
    )

    discovered = set()
    for name, obj in inspect.getmembers(srv):
        if inspect.iscoroutinefunction(obj) and name in EXPECTED_TOOLS:
            discovered.add(name)
    missing = EXPECTED_TOOLS - discovered
    assert not missing, f"Tools declared but not importable: {missing}"


def _extract_id(text: str) -> str:
    """Pull the canonical id pattern (uuid-shaped) from a formatter output."""
    match = re.search(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", text)
    assert match is not None, f"No uuid found in: {text!r}"
    return match.group(0)


async def test_all_26_tools_round_trip(engine_singleton):
    """Drive every tool through a single coherent workflow.

    The order is chosen so each tool gets realistic inputs from prior tool
    outputs: values → intentions → commitments → tasks → memories →
    relations → maintenance. Each call must return a non-empty string and
    must not raise.
    """
    # Persona layer ------------------------------------------------------
    value_out = await srv.declare_value(content="Smoke-test value: tier 1 always green")
    value_id = _extract_id(value_out)

    intention_out = await srv.declare_intention(
        content="Smoke-test intention: keep the MCP surface honest",
        parent_value_id=value_id,
    )
    intention_id = _extract_id(intention_out)

    commit_decl_out = await srv.declare_commitment(
        content="Smoke-test commitment: tier-1 smoke runs in CI",
        parent_intention_id=intention_id,
    )
    commit_decl_id = _extract_id(commit_decl_out)

    persona_out = await srv.inherit_persona()
    assert "Persona" in persona_out or "Value" in persona_out

    # Task layer ---------------------------------------------------------
    commit_out = await srv.commit(
        content="Smoke-test task: tier-1 ran today",
        parent_id=commit_decl_id,
    )
    task_id = _extract_id(commit_out)

    other_task_out = await srv.commit(content="Smoke-test task: tier-1 sibling")
    other_task_id = _extract_id(other_task_out)

    depend_out = await srv.depend(task_id=task_id, depends_on_id=other_task_id)
    assert "-->" in depend_out

    start_out = await srv.start(task_id=task_id)
    assert "Started" in start_out

    complete_out = await srv.complete(
        task_id=task_id, outcome="Tier-1 smoke completed cleanly", emotion=0.6,
    )
    assert "Completed" in complete_out

    abandon_out = await srv.abandon(
        task_id=other_task_id, reason="Sibling task no longer needed",
    )
    assert "Abandoned" in abandon_out

    # Memory layer -------------------------------------------------------
    remember_out = await srv.remember(
        content="Tier-1 smoke: a note with no surprises",
        source="agent", tags=["tier-1-smoke"],
    )
    mem_id = _extract_id(remember_out)

    second_out = await srv.remember(
        content="Tier-1 smoke: a second note that overlaps lexically with first",
        source="agent", tags=["tier-1-smoke"],
    )
    mem2_id = _extract_id(second_out)

    revalidate_out = await srv.revalidate(node_id=mem_id, certainty=0.9)
    assert "Revalidated" in revalidate_out or "refreshed" in revalidate_out.lower()

    recall_out = await srv.recall(query="Tier-1 smoke", top_k=3)
    assert "smoke" in recall_out.lower() or "tier" in recall_out.lower()

    explore_out = await srv.explore(query="Tier-1 smoke", top_k=3)
    assert isinstance(explore_out, str) and len(explore_out) > 0

    ambient_out = await srv.ambient_recall(query="Tier-1 smoke")
    assert isinstance(ambient_out, str) and len(ambient_out) > 0

    # Auto-remember does not save — just extract candidates from a transcript
    auto_out = await srv.auto_remember(
        transcript="ユーザー: pip禁止。uvを使ってください\nアシスタント: 了解\n",
        max_candidates=3,
    )
    assert "Extracted" in auto_out or "candidate" in auto_out.lower()

    # Relations ----------------------------------------------------------
    relate_out = await srv.relate(
        src_id=mem2_id, dst_id=mem_id, edge_type="supersedes",
        metadata={"reason": "smoke-test"},
    )
    assert "supersedes" in relate_out or "-->" in relate_out

    rel_out = await srv.get_relations(node_id=mem2_id, direction="out")
    assert "supersedes" in rel_out

    unrel_out = await srv.unrelate(src_id=mem2_id, dst_id=mem_id, edge_type="supersedes")
    assert "Unrelated" in unrel_out or "removed" in unrel_out.lower()

    # Reflection ---------------------------------------------------------
    reflect_out = await srv.reflect(aspect="summary")
    assert isinstance(reflect_out, str) and len(reflect_out) > 0

    # Prefetch -----------------------------------------------------------
    pf_out = await srv.prefetch(query="Tier-1 smoke", top_k=3)
    assert "Prefetch" in pf_out or "scheduled" in pf_out.lower() or "queued" in pf_out.lower()
    pf_status = await srv.prefetch_status()
    assert isinstance(pf_status, str) and len(pf_status) > 0

    # Ingest -------------------------------------------------------------
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "smoke.md"
        p.write_text(
            "# Smoke ingest\nA small file used to exercise the ingest tool.",
            encoding="utf-8",
        )
        ingest_out = await srv.ingest(path=str(p), source="file")
        assert "Ingested" in ingest_out or "indexed" in ingest_out.lower()

    # Maintenance --------------------------------------------------------
    # Add a near-duplicate then merge it with mem_id.
    dup_out = await srv.remember(
        content="Tier-1 smoke: a near-duplicate note to be merged",
        source="agent", tags=["tier-1-smoke"],
    )
    dup_id = _extract_id(dup_out)
    merge_out = await srv.merge(node_ids=[mem_id, dup_id])
    assert "merge" in merge_out.lower() or "->" in merge_out or "→" in merge_out

    compact_out = await srv.compact()
    assert "Compact" in compact_out or "expired" in compact_out.lower()

    # Forget / restore ---------------------------------------------------
    forget_out = await srv.forget(node_ids=[mem2_id])
    assert "Archived" in forget_out or "1" in forget_out
    restore_out = await srv.restore(node_ids=[mem2_id])
    assert "Restored" in restore_out
