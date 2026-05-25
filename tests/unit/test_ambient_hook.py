"""Stage 4 — ambient hook transcript-parsing helpers.

The hook is a stand-alone script (not part of the ``gaottt`` package), so we
import its helpers via ``importlib`` from ``scripts/hooks/ambient_recall.py``.
These tests cover the multi-turn context extraction (Refinement Stage 4):

- ``_extract_user_text`` tolerates the Claude Code transcript shapes seen in
  practice (string content / structured content list / ``type`` vs ``role``).
- ``_recent_user_prompts`` returns ``[]`` on missing file / parse errors —
  the hook always falls back to current-prompt-only behavior.
- ``_compose_query`` dedupes a trailing exact-match (the transcript may
  already log the current prompt as its last entry).
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

_HOOK = Path(__file__).resolve().parents[2] / "scripts" / "hooks" / "ambient_recall.py"


def _load_hook_module():
    spec = importlib.util.spec_from_file_location("ambient_recall_hook", _HOOK)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


hook = _load_hook_module()


def test_extract_user_text_handles_string_content():
    rec = {"type": "user", "message": {"content": "  hello world  "}}
    assert hook._extract_user_text(rec) == "hello world"


def test_extract_user_text_handles_structured_content_list():
    rec = {
        "type": "user",
        "message": {
            "content": [
                {"type": "text", "text": "first chunk"},
                {"type": "text", "text": "second chunk"},
            ],
        },
    }
    assert hook._extract_user_text(rec) == "first chunk second chunk"


def test_extract_user_text_handles_role_shape():
    rec = {"role": "user", "content": "role-shaped"}
    assert hook._extract_user_text(rec) == "role-shaped"


def test_extract_user_text_returns_empty_on_unknown_shape():
    assert hook._extract_user_text({"foo": "bar"}) == ""


def test_recent_user_prompts_returns_last_n(tmp_path):
    f = tmp_path / "transcript.jsonl"
    lines = [
        {"type": "user", "message": {"content": "turn 1"}},
        {"type": "assistant", "message": {"content": "asst 1"}},
        {"type": "user", "message": {"content": "turn 2"}},
        {"type": "assistant", "message": {"content": "asst 2"}},
        {"type": "user", "message": {"content": "turn 3"}},
    ]
    f.write_text(
        "\n".join(json.dumps(line) for line in lines), encoding="utf-8",
    )
    assert hook._recent_user_prompts(str(f), 2) == ["turn 2", "turn 3"]
    assert hook._recent_user_prompts(str(f), 5) == ["turn 1", "turn 2", "turn 3"]


def test_recent_user_prompts_failsafe_on_missing_file(tmp_path):
    missing = tmp_path / "does-not-exist.jsonl"
    assert hook._recent_user_prompts(str(missing), 3) == []


def test_recent_user_prompts_skips_bad_json_lines(tmp_path):
    f = tmp_path / "transcript.jsonl"
    f.write_text(
        "not valid json\n"
        + json.dumps({"type": "user", "message": {"content": "good"}}) + "\n"
        + "another garbage line\n",
        encoding="utf-8",
    )
    assert hook._recent_user_prompts(str(f), 5) == ["good"]


def test_recent_user_prompts_returns_empty_for_zero_n(tmp_path):
    f = tmp_path / "t.jsonl"
    f.write_text(
        json.dumps({"type": "user", "message": {"content": "one"}}),
        encoding="utf-8",
    )
    assert hook._recent_user_prompts(str(f), 0) == []


def test_compose_query_dedupes_trailing_current_prompt():
    # Transcript already logged the current prompt as the last user turn.
    history = ["earlier turn", "  current  "]
    query = hook._compose_query("current", history)
    assert query == "earlier turn\ncurrent"


def test_compose_query_no_history_returns_current():
    assert hook._compose_query("only this", []) == "only this"


def test_compose_query_concatenates_history_and_current():
    history = ["first earlier", "second earlier"]
    query = hook._compose_query("now", history)
    assert query == "first earlier\nsecond earlier\nnow"


# --- Lateral Association Stage 1 — manifest parsing + novelty map -------------


def test_ids_from_manifest_extracts_all_slot_ids():
    block = (
        "<gaottt-ambient-recall>\n"
        " ... (slots) ...\n"
        "<!-- ambient-ids direct=abc123,def456 lensing=789xyz persona=p_id -->\n"
        "</gaottt-ambient-recall>\n"
    )
    ids = hook._ids_from_manifest(block)
    assert ids == ["abc123", "def456", "789xyz", "p_id"]


def test_ids_from_manifest_handles_missing_slots():
    # persona-only — common when the relevance gate killed direct + lensing
    block = "<!-- ambient-ids persona=only_persona -->"
    assert hook._ids_from_manifest(block) == ["only_persona"]


def test_ids_from_manifest_returns_empty_when_absent():
    block = "<gaottt-ambient-recall>\n no manifest\n</gaottt-ambient-recall>"
    assert hook._ids_from_manifest(block) == []


def _ambient_attachment(content: str) -> dict:
    """Shape of a Claude Code transcript record carrying a UserPromptSubmit
    hook's stdout (the ambient block this hook itself emits)."""
    return {
        "type": "system",
        "attachment": {
            "type": "hook_success",
            "hookName": "UserPromptSubmit",
            "content": content,
            "stdout": content,
        },
    }


def _ambient_block(direct_ids, lensing=None, persona=None) -> str:
    parts = []
    if direct_ids:
        parts.append("direct=" + ",".join(direct_ids))
    if lensing:
        parts.append(f"lensing={lensing}")
    if persona:
        parts.append(f"persona={persona}")
    return (
        "<gaottt-ambient-recall>\n"
        "stub block\n"
        f"<!-- ambient-ids {' '.join(parts)} -->\n"
        "</gaottt-ambient-recall>"
    )


def test_recently_surfaced_counts_across_recent_turns(tmp_path):
    f = tmp_path / "transcript.jsonl"
    # 3 ambient blocks: id_A appears in 2/3, id_B in 1, id_C in 1.
    blocks = [
        _ambient_block(["id_A", "id_B"], persona="id_P"),
        _ambient_block(["id_A"], lensing="id_C", persona="id_P"),
        _ambient_block(["id_D"], persona="id_P"),
    ]
    records = [_ambient_attachment(b) for b in blocks]
    f.write_text(
        "\n".join(json.dumps(r) for r in records), encoding="utf-8",
    )
    counts = hook._recently_surfaced(str(f), 5)
    assert counts["id_A"] == 2
    assert counts["id_B"] == 1
    assert counts["id_C"] == 1
    assert counts["id_D"] == 1
    assert counts["id_P"] == 3


def test_recently_surfaced_caps_at_n_most_recent(tmp_path):
    f = tmp_path / "transcript.jsonl"
    records = [
        _ambient_attachment(_ambient_block(["old"])),
        _ambient_attachment(_ambient_block(["mid"])),
        _ambient_attachment(_ambient_block(["new1", "new2"])),
    ]
    f.write_text(
        "\n".join(json.dumps(r) for r in records), encoding="utf-8",
    )
    # n=1 picks only the newest block.
    counts = hook._recently_surfaced(str(f), 1)
    assert counts == {"new1": 1, "new2": 1}


def test_recently_surfaced_failsafe_on_missing_file(tmp_path):
    missing = tmp_path / "nope.jsonl"
    assert hook._recently_surfaced(str(missing), 5) == {}


def test_recently_surfaced_returns_empty_for_zero_n(tmp_path):
    f = tmp_path / "t.jsonl"
    f.write_text(
        json.dumps(_ambient_attachment(_ambient_block(["any"]))),
        encoding="utf-8",
    )
    assert hook._recently_surfaced(str(f), 0) == {}


# --- Lateral Association Stage 4 — composed query visibility -----------------


def _ambient_text_block(direct_ids, persona=None) -> str:
    """Minimal valid ambient block for injection tests."""
    parts = ["direct=" + ",".join(direct_ids)] if direct_ids else []
    if persona:
        parts.append(f"persona={persona}")
    manifest = f"<!-- ambient-ids {' '.join(parts)} -->" if parts else ""
    return (
        "<gaottt-ambient-recall>\n"
        "stub body\n"
        + (manifest + "\n" if manifest else "")
        + "</gaottt-ambient-recall>"
    )


def test_inject_composed_query_debug_appends_comment_before_close_tag():
    block = _ambient_text_block(["a", "b"])
    out = hook._inject_composed_query_debug(
        block, prompt="follow-up", composed="prior turn\nfollow-up",
    )
    assert "<!-- ambient: composed query" in out
    comment_idx = out.find("<!-- ambient: composed query")
    close_idx = out.find("</gaottt-ambient-recall>")
    assert 0 < comment_idx < close_idx, (
        "comment must sit inside the block, before the close tag"
    )
    # Composed query content is preserved (newlines escaped to keep one line).
    assert "prior turn\\nfollow-up" in out


def test_inject_composed_query_debug_noop_when_composed_equals_prompt():
    """If history was empty / matched the prompt, composed==prompt and the
    debug line would just duplicate user input — skip it."""
    block = _ambient_text_block(["a"])
    out = hook._inject_composed_query_debug(
        block, prompt="same text", composed="same text",
    )
    assert out == block
    assert "<!-- ambient: composed query" not in out


def test_inject_composed_query_debug_noop_when_no_close_tag():
    """Defensive: if the response isn't our ambient block (no close tag),
    leave it alone — we don't want to mutate unrelated text."""
    not_a_block = "some other text without the tag"
    out = hook._inject_composed_query_debug(
        not_a_block, prompt="p", composed="composed",
    )
    assert out == not_a_block


def test_inject_composed_query_debug_escapes_embedded_newlines():
    """The comment must stay a single line so other parsers
    (transcript-line readers, our own ``_recently_surfaced``) don't trip."""
    block = _ambient_text_block(["a"])
    composed = "line1\nline2\nline3"
    out = hook._inject_composed_query_debug(
        block, prompt="line3", composed=composed,
    )
    # Find the injected line; it must not contain literal newlines.
    injected_line = next(
        (line for line in out.splitlines() if "ambient: composed query" in line),
        None,
    )
    assert injected_line is not None
    assert injected_line.count("\\n") == 2  # 3 lines → 2 escaped newlines
    assert "\n" not in injected_line  # the line itself is one line


# --- Frontend parity (Python payload accepts history + recently_surfaced) ---


def _make_stdin_payload(**kwargs) -> str:
    return json.dumps(kwargs)


def _run_hook_main(payload_json: str, monkeypatch, capsys, **mock_block_kwargs):
    """Drive the hook's ``main()`` end-to-end with a synthetic stdin payload,
    mocking out the MCP call and stdout write. Returns the call args the
    ``_ambient_recall`` mock received so the test can assert on the payload."""
    import io

    call_args: dict = {}

    async def _fake_recall(prompt, recently_surfaced=None):
        call_args["prompt"] = prompt
        call_args["recently_surfaced"] = recently_surfaced
        return mock_block_kwargs.get("returned_block")

    def _fake_emit(text: str) -> None:
        call_args["emitted"] = text

    monkeypatch.setattr(hook, "_ambient_recall", _fake_recall)
    monkeypatch.setattr(hook, "_emit", _fake_emit)
    monkeypatch.setattr(hook.sys, "stdin", io.StringIO(payload_json))
    rc = hook.main()
    call_args["rc"] = rc
    return call_args


def test_payload_history_bypasses_transcript_scan(monkeypatch, capsys):
    """When ``history`` is in the payload, the hook uses it directly and
    never calls the transcript-scanning helper."""
    sentinel = "TRANSCRIPT SCAN WAS CALLED"

    def _explode(*args, **kwargs):
        raise AssertionError(sentinel)

    monkeypatch.setattr(hook, "_recent_user_prompts", _explode)
    monkeypatch.setattr(hook, "_recently_surfaced", lambda *a, **k: {})
    payload = _make_stdin_payload(
        prompt="current prompt long enough",
        history=["earlier 1", "earlier 2"],
    )
    args = _run_hook_main(payload, monkeypatch, capsys, returned_block=None)
    assert args["rc"] == 0
    assert args["prompt"] == "earlier 1\nearlier 2\ncurrent prompt long enough"


def test_payload_recently_surfaced_bypasses_transcript_scan(monkeypatch, capsys):
    """When ``recently_surfaced`` is in the payload, the hook forwards it
    verbatim and never calls the transcript-scanning helper."""
    def _explode(*args, **kwargs):
        raise AssertionError("transcript scan called")

    monkeypatch.setattr(hook, "_recently_surfaced", _explode)
    monkeypatch.setattr(hook, "_recent_user_prompts", lambda *a, **k: [])
    payload = _make_stdin_payload(
        prompt="current prompt long enough",
        recently_surfaced={"id_alpha": 2, "id_beta": 1},
    )
    args = _run_hook_main(payload, monkeypatch, capsys, returned_block=None)
    assert args["recently_surfaced"] == {"id_alpha": 2, "id_beta": 1}


def test_payload_transcript_path_fallback_when_history_absent(monkeypatch, capsys):
    """Claude Code path: only ``transcript_path`` in payload, no
    ``history``/``recently_surfaced`` → hook scans the transcript."""
    scan_calls: dict = {}

    def _scan_history(path, n):
        scan_calls["history"] = (path, n)
        return ["scanned 1"]

    def _scan_recently(path, n):
        scan_calls["recently"] = (path, n)
        return {"scanned_id": 1}

    monkeypatch.setattr(hook, "_recent_user_prompts", _scan_history)
    monkeypatch.setattr(hook, "_recently_surfaced", _scan_recently)
    # ensure both scan envs are >0 for the test (defaults are 2 and 5).
    monkeypatch.setattr(hook, "_HISTORY_TURNS", 2)
    monkeypatch.setattr(hook, "_NOVELTY_TURNS", 5)
    payload = _make_stdin_payload(
        prompt="current prompt long enough",
        transcript_path="/tmp/fake-transcript.jsonl",
    )
    args = _run_hook_main(payload, monkeypatch, capsys, returned_block=None)
    assert scan_calls["history"] == ("/tmp/fake-transcript.jsonl", 2)
    assert scan_calls["recently"] == ("/tmp/fake-transcript.jsonl", 5)
    assert args["recently_surfaced"] == {"scanned_id": 1}


def test_payload_invalid_recently_surfaced_falls_back(monkeypatch, capsys):
    """A malformed ``recently_surfaced`` (e.g. list instead of dict) should
    silently fall back to transcript scanning rather than crash."""
    monkeypatch.setattr(hook, "_recent_user_prompts", lambda *a, **k: [])
    monkeypatch.setattr(hook, "_recently_surfaced", lambda *a, **k: {"fallback": 1})
    payload = _make_stdin_payload(
        prompt="current prompt long enough",
        recently_surfaced=["not", "a", "dict"],  # malformed
    )
    args = _run_hook_main(payload, monkeypatch, capsys, returned_block=None)
    # Falls back to scan output (the {"fallback": 1} our stub returned).
    assert args["recently_surfaced"] == {"fallback": 1}


def test_recently_surfaced_ignores_non_ambient_hook_records(tmp_path):
    f = tmp_path / "t.jsonl"
    records = [
        # Wrong hook → ignored.
        {
            "type": "system",
            "attachment": {
                "type": "hook_success",
                "hookName": "SomeOtherHook",
                "content": _ambient_block(["wrong_hook"]),
            },
        },
        # Right hook, manifest present → counted.
        _ambient_attachment(_ambient_block(["good"])),
        # Right hook but no block → ignored (no manifest).
        {
            "type": "system",
            "attachment": {
                "type": "hook_success",
                "hookName": "UserPromptSubmit",
                "content": "just some text without the tag",
            },
        },
    ]
    f.write_text(
        "\n".join(json.dumps(r) for r in records), encoding="utf-8",
    )
    counts = hook._recently_surfaced(str(f), 5)
    assert counts == {"good": 1}
