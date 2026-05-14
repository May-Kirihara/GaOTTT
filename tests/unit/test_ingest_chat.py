"""Unit tests for Claude Code transcript (.jsonl) ingestion.

Covers: turn pairing, CLI-injection skipping, ``isMeta`` / synthetic skip,
``tool_use`` summarisation, ``tool_result`` opt-in, sidechain tagging,
``original_id`` continuity, metadata propagation.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from gaottt.ingest.loader import ingest_path


def _write_jsonl(tmp_path: Path, rows: list[dict]) -> Path:
    p = tmp_path / "session.jsonl"
    with open(p, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return p


def _user_row(uuid: str, content, **extra) -> dict:
    base = {
        "type": "user",
        "uuid": uuid,
        "timestamp": "2026-05-14T00:00:00.000Z",
        "sessionId": "sess-1",
        "cwd": "/work",
        "message": {"role": "user", "content": content},
    }
    base.update(extra)
    return base


def _asst_row(uuid: str, content, model: str = "claude-opus-4-7", **extra) -> dict:
    base = {
        "type": "assistant",
        "uuid": uuid,
        "timestamp": "2026-05-14T00:00:01.000Z",
        "sessionId": "sess-1",
        "cwd": "/work",
        "message": {"role": "assistant", "model": model, "content": content},
    }
    base.update(extra)
    return base


def test_basic_user_assistant_pair(tmp_path: Path) -> None:
    p = _write_jsonl(tmp_path, [
        _user_row("u1", "Hello"),
        _asst_row("a1", [{"type": "text", "text": "Hi there"}]),
    ])
    docs = ingest_path(str(p), source="claude-code")

    assert len(docs) == 1
    d = docs[0]
    assert "## User\nHello" in d["content"]
    assert "## Assistant\nHi there" in d["content"]
    meta = d["metadata"]
    assert meta["source"] == "claude-code"
    assert meta["session_id"] == "sess-1"
    assert meta["turn_index"] == 0
    assert meta["original_id"] == "sess-1#0"
    assert meta["model"] == "claude-opus-4-7"
    assert meta["cwd"] == "/work"
    assert meta["file_path"] == str(p)


def test_skip_local_command_injections(tmp_path: Path) -> None:
    rows = [
        # CLI caveats / stdout — must be skipped entirely.
        _user_row("u1", "<local-command-caveat>foo</local-command-caveat>",
                  isMeta=True),
        _user_row("u2", "<command-name>/resume</command-name>\n"
                        "<command-message>resume</command-message>\n"
                        "<command-args></command-args>"),
        _user_row("u3", "<local-command-stdout>No conversations</local-command-stdout>"),
        # Real prompt
        _user_row("u4", "actual question"),
        _asst_row("a4", [{"type": "text", "text": "actual answer"}]),
    ]
    docs = ingest_path(str(_write_jsonl(tmp_path, rows)))
    assert len(docs) == 1
    assert "actual question" in docs[0]["content"]
    assert "actual answer" in docs[0]["content"]
    assert docs[0]["metadata"]["turn_index"] == 0


def test_skip_synthetic_assistant(tmp_path: Path) -> None:
    rows = [
        _user_row("u1", "ping"),
        _asst_row("a1", [{"type": "text", "text": "No response requested."}],
                  model="<synthetic>"),
    ]
    docs = ingest_path(str(_write_jsonl(tmp_path, rows)))
    # Synthetic assistant is dropped — the unanswered user prompt flushes alone.
    assert len(docs) == 1
    assert "## User\nping" in docs[0]["content"]
    assert "## Assistant" not in docs[0]["content"]


def test_skip_control_rows(tmp_path: Path) -> None:
    rows = [
        {"type": "permission-mode", "permissionMode": "default",
         "sessionId": "sess-1"},
        {"type": "file-history-snapshot", "messageId": "x",
         "snapshot": {}, "isSnapshotUpdate": False},
        {"type": "last-prompt", "leafUuid": "x", "sessionId": "sess-1"},
        _user_row("u1", "real prompt"),
        _asst_row("a1", [{"type": "text", "text": "reply"}]),
    ]
    docs = ingest_path(str(_write_jsonl(tmp_path, rows)))
    assert len(docs) == 1


def test_tool_use_summary(tmp_path: Path) -> None:
    rows = [
        _user_row("u1", "run something"),
        _asst_row("a1", [
            {"type": "text", "text": "Let me check."},
            {"type": "tool_use", "name": "Bash",
             "input": {"command": "ls -la", "description": "list files"}},
            {"type": "text", "text": "Done."},
        ]),
    ]
    docs = ingest_path(str(_write_jsonl(tmp_path, rows)))
    assert len(docs) == 1
    body = docs[0]["content"]
    assert "Let me check." in body
    assert "[tool:Bash]" in body
    assert "ls -la" in body
    assert "Done." in body


def test_tool_results_off_by_default(tmp_path: Path) -> None:
    """tool_result rows (user role) are dropped unless --include-tool-results."""
    rows = [
        _user_row("u1", "do it"),
        _asst_row("a1", [
            {"type": "text", "text": "running"},
            {"type": "tool_use", "name": "Bash",
             "input": {"command": "echo hi"}},
        ]),
        _user_row("u2", [
            {"type": "tool_result", "tool_use_id": "x",
             "content": "hi\nlots of stdout"},
        ]),
        _asst_row("a2", [{"type": "text", "text": "ok"}]),
    ]
    docs = ingest_path(str(_write_jsonl(tmp_path, rows)),
                       include_tool_results=False)
    body = "\n---\n".join(d["content"] for d in docs)
    assert "lots of stdout" not in body

    # With the flag, the tool_result is appended onto the previous turn.
    docs2 = ingest_path(str(_write_jsonl(tmp_path, rows)),
                        include_tool_results=True)
    body2 = "\n---\n".join(d["content"] for d in docs2)
    assert "lots of stdout" in body2


def test_sidechain_tag(tmp_path: Path) -> None:
    rows = [
        _user_row("u1", "spawn an agent", isSidechain=True),
        _asst_row("a1", [{"type": "text", "text": "agent reply"}],
                  isSidechain=True),
    ]
    docs = ingest_path(str(_write_jsonl(tmp_path, rows)))
    assert len(docs) == 1
    assert docs[0]["metadata"]["is_sidechain"] is True


def test_original_id_groups_chunks_of_same_turn(tmp_path: Path) -> None:
    long_text = "話 " * 1500  # ~3000 chars, exceeds 2000 chunk_size
    rows = [
        _user_row("u1", "short prompt"),
        _asst_row("a1", [{"type": "text", "text": long_text}]),
    ]
    docs = ingest_path(str(_write_jsonl(tmp_path, rows)), chunk_size=2000)
    assert len(docs) > 1
    # All chunks of the same turn must share original_id (Phase M self-force).
    ids = {d["metadata"]["original_id"] for d in docs}
    assert ids == {"sess-1#0"}
    # Each chunk gets its position metadata.
    for d in docs:
        assert d["metadata"]["chunk_index"] is not None
        assert d["metadata"]["total_chunks"] == len(docs)
    # Every chunk preserves both ## User and ## Assistant headers — chunks
    # past the first get a `## User (prev): ...` context line injected.
    for d in docs:
        assert "## User" in d["content"]
        assert "## Assistant" in d["content"]


def test_long_exchange_chunks_have_user_context(tmp_path: Path) -> None:
    """Chunks past the first must surface the user prompt as context.

    Regression for the post-compact acceptance test where tool-heavy
    continuations (top1 = mid-assistant tail) lost the user prompt and
    looked like naked tool-call fragments to the embedder.
    """
    user_prompt = "Refactor the FAISS write-behind to flush on shutdown please"
    huge_assistant = "Let me look. " + ("\n\n[tool:Edit] gaottt/store/cache.py" * 200)
    rows = [
        _user_row("u1", user_prompt),
        _asst_row("a1", [{"type": "text", "text": huge_assistant}]),
    ]
    docs = ingest_path(str(_write_jsonl(tmp_path, rows)), chunk_size=2000)
    assert len(docs) >= 2

    # First chunk: full ## User block with the original prompt.
    assert docs[0]["content"].startswith("## User\n")
    assert user_prompt in docs[0]["content"]

    # All later chunks: must contain the user prompt as a context line and
    # the (cont.) marker. The truncated prefix uses the first 100 chars of
    # the prompt's first line; the prompt above is short so it appears whole.
    for d in docs[1:]:
        c = d["content"]
        assert "## User (prev): " in c, f"chunk missing prev-user line: {c[:120]!r}"
        # The first 50 chars of the prompt should appear in the prefix.
        assert user_prompt[:50] in c
        # Either an `## Assistant` (first cont. chunk that starts with the
        # paragraph) or an `## Assistant (cont.)` marker for naked tails.
        assert "## Assistant" in c


def test_unanswered_trailing_user_is_kept(tmp_path: Path) -> None:
    rows = [
        _user_row("u1", "first"),
        _asst_row("a1", [{"type": "text", "text": "reply"}]),
        _user_row("u2", "trailing question with no reply"),
    ]
    docs = ingest_path(str(_write_jsonl(tmp_path, rows)))
    assert len(docs) == 2
    assert docs[1]["metadata"]["turn_index"] == 1
    assert "trailing question" in docs[1]["content"]
    assert "## Assistant" not in docs[1]["content"]


def test_empty_or_malformed_lines_skipped(tmp_path: Path) -> None:
    p = tmp_path / "session.jsonl"
    with open(p, "w", encoding="utf-8") as f:
        f.write("\n")
        f.write("not valid json\n")
        f.write(json.dumps(_user_row("u1", "real")) + "\n")
        f.write(json.dumps(_asst_row("a1", [{"type": "text", "text": "reply"}])) + "\n")
    docs = ingest_path(str(p))
    assert len(docs) == 1


def test_directory_walk(tmp_path: Path) -> None:
    sub = tmp_path / "proj"
    sub.mkdir()
    for sid in ("sess-A", "sess-B"):
        with open(sub / f"{sid}.jsonl", "w", encoding="utf-8") as f:
            f.write(json.dumps({**_user_row("u1", "q"), "sessionId": sid}) + "\n")
            f.write(json.dumps({**_asst_row(
                "a1", [{"type": "text", "text": "a"}]), "sessionId": sid}) + "\n")
    docs = ingest_path(str(sub), recursive=True, pattern="*.jsonl")
    assert len(docs) == 2
    session_ids = {d["metadata"]["session_id"] for d in docs}
    assert session_ids == {"sess-A", "sess-B"}


@pytest.mark.parametrize("sample_path", [
    Path(__file__).parent.parent.parent
    / "input" / "projects" / "-mnt-holyland-devs-maysweb"
    / "bd9ee013-59d6-4c0d-b091-ebacd47f3b1d.jsonl",
])
def test_real_sample_smoke(sample_path: Path) -> None:
    """The provided sample is mostly resume noise — should ingest 0 turns."""
    if not sample_path.exists():
        pytest.skip(f"sample not present at {sample_path}")
    docs = ingest_path(str(sample_path), source="claude-code")
    # Only synthetic assistant + CLI injections — no real exchange.
    assert docs == []
