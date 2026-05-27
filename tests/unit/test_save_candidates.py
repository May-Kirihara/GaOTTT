"""Unit tests — ``format_save_candidates`` block formatter.

Pure-function tests for the ``<gaottt-save-candidates>`` block layout
defined in ``gaottt.services.formatters.format_save_candidates``. No
engine required — the formatter only reads the ``SaveCandidatesResponse``
shape.
"""
from __future__ import annotations

from gaottt.core.types import (
    AmbientPersona,
    AutoRememberCandidate,
    SaveCandidatesResponse,
)
from gaottt.services.formatters import format_save_candidates


def _candidate(content: str, score: float = 0.7, **kw) -> AutoRememberCandidate:
    return AutoRememberCandidate(
        content=content,
        score=score,
        suggested_source=kw.get("suggested_source", "agent"),
        suggested_tags=kw.get("suggested_tags", []),
        reasons=kw.get("reasons", ["decision-marker"]),
    )


def test_empty_response_returns_sentinel():
    """Mirrors ``format_ambient``'s count==0 contract — sentinel string, no
    block tag, hook stays silent."""
    result = SaveCandidatesResponse(candidates=[], count=0)
    out = format_save_candidates(result)
    assert out == "(保存候補なし)"
    assert "<gaottt-save-candidates>" not in out


def test_single_candidate_renders_block():
    result = SaveCandidatesResponse(
        candidates=[_candidate("Phase P 起草は 2026-05-26", score=0.82)],
        count=1,
    )
    out = format_save_candidates(result)
    assert out.startswith("<gaottt-save-candidates>")
    assert out.rstrip().endswith("</gaottt-save-candidates>")
    assert "▼ 候補" in out
    assert "Phase P 起草は 2026-05-26" in out
    assert "score=0.82" in out
    assert "source=agent" in out
    assert "<!-- save-candidates count=1 -->" in out


def test_block_carries_save_policy_filter_line():
    """The save-policy filter (durable user preference, memory id 93035d35)
    is articulated at every lens firing — visible at the exact moment the
    save decision happens. Skip / save guidance lives next to the candidate
    list so the reader does not have to recall a separate doc."""
    result = SaveCandidatesResponse(
        candidates=[_candidate("any candidate", score=0.5)], count=1,
    )
    out = format_save_candidates(result)
    assert "判断 filter:" in out
    assert "未来の判断を変える" in out
    assert "git log" in out or "diff" in out


def test_persona_slot_renders_when_present():
    persona = AmbientPersona(
        id="p1", kind="intention",
        content="GaOTTT を体系的な重力場として残す",
    )
    result = SaveCandidatesResponse(
        candidates=[_candidate("decision X")],
        persona=persona,
        count=1,
    )
    out = format_save_candidates(result)
    assert "▼ いま誰として" in out
    assert "intention:" in out
    assert "重力場" in out


def test_persona_slot_omitted_when_none():
    result = SaveCandidatesResponse(
        candidates=[_candidate("decision X")], persona=None, count=1,
    )
    out = format_save_candidates(result)
    assert "▼ いま誰として" not in out


def test_long_content_is_truncated_to_200_chars():
    """Token-budget guard — the block should stay compact."""
    long_text = "あ" * 500
    result = SaveCandidatesResponse(
        candidates=[_candidate(long_text)], count=1,
    )
    out = format_save_candidates(result)
    # 200 truncated chars + "..." ellipsis suffix
    assert "あ" * 200 + "..." in out
    assert "あ" * 250 not in out


def test_reasons_render_on_indented_line():
    result = SaveCandidatesResponse(
        candidates=[_candidate("x", reasons=["correction", "absolute"])],
        count=1,
    )
    out = format_save_candidates(result)
    assert "reason: correction, absolute" in out


def test_manifest_count_matches_candidate_count():
    """The trailing ``<!-- save-candidates count=N -->`` comment lets a hook
    parser know the candidate count without reparsing the body."""
    result = SaveCandidatesResponse(
        candidates=[_candidate("a"), _candidate("b"), _candidate("c")],
        count=3,
    )
    out = format_save_candidates(result)
    assert "<!-- save-candidates count=3 -->" in out


# --- Stop-hook transcript extractor (regression for the tool_result bug) ---

def _load_hook_extract():
    """Import ``_extract_text`` from the Stop hook script without making the
    test suite depend on the script being on the Python path. The script
    has no side effects at import time."""
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location(
        "save_candidates_hook",
        Path(__file__).resolve().parents[2]
        / "scripts" / "hooks" / "save_candidates.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod._extract_text


def test_hook_extract_text_skips_tool_result_blocks():
    """Live-acceptance regression — Claude Code transcript ``user`` records
    carry tool_result blocks (bash output, find listings, etc.) interleaved
    with the actual human messages. Earlier the extractor returned
    ``c.get("text") or c.get("content")``, which pulled the long bash output
    out of ``tool_result`` and flooded the heuristic with garbage, sentinel-ing
    the Stop hook silent. The fix: only ``type == "text"`` blocks count."""
    extract = _load_hook_extract()
    rec = {
        "type": "user",
        "message": {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "x",
                    "content": "/path/to/garbage.jsonl\n" * 50,
                },
                {"type": "text", "text": "重要な決定: foo を bar に置き換える"},
            ],
        },
    }
    text = extract(rec)
    assert "重要な決定" in text
    assert "garbage.jsonl" not in text


def test_hook_extract_text_skips_assistant_thinking():
    """Assistant records can contain ``thinking`` blocks (internal reasoning).
    Those are not what the human said in a conversation and should not feed
    the heuristic — only ``type == "text"`` (model output) counts."""
    extract = _load_hook_extract()
    rec = {
        "type": "assistant",
        "message": {
            "role": "assistant",
            "content": [
                {"type": "thinking", "thinking": "let me think about X..."},
                {"type": "tool_use", "name": "Bash", "input": {"command": "ls"}},
                {"type": "text", "text": "結論: X を採用する"},
            ],
        },
    }
    text = extract(rec)
    assert text == "結論: X を採用する"


def test_hook_extract_text_returns_empty_for_tool_only_record():
    """A user record that is *purely* a tool_result (no human text alongside)
    should yield empty string so the caller's filter drops it from the turn
    count — otherwise tool_result-only records would consume the N budget
    without contributing any save-worthy signal."""
    extract = _load_hook_extract()
    rec = {
        "type": "user",
        "message": {
            "content": [
                {"type": "tool_result", "tool_use_id": "x", "content": "ok"},
            ],
        },
    }
    assert extract(rec) == ""


def test_hook_extract_text_accepts_plain_string_content():
    """Older transcript shapes (or programmatic callers) sometimes store
    ``content`` as a bare string — the extractor must still handle that path
    so the regression doesn't break the opencode/manual-payload route."""
    extract = _load_hook_extract()
    rec = {"type": "user", "message": {"content": "失敗: parse error"}}
    assert extract(rec) == "失敗: parse error"


# --- Stop-hook emit-mode dispatch (regression for the opencode plugin path) ---

def _load_hook_module(monkeypatch, **env: str):
    """Re-import ``scripts/hooks/save_candidates.py`` with a fresh env so the
    module-level ``_EMIT_MODE`` / ``_STATE_DIR`` constants reflect the test
    config. ``importlib.util`` is used (not ``importlib.reload``) so each call
    yields a clean module — no leaked state from earlier tests."""
    import importlib.util
    import sys as _sys
    from pathlib import Path
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    # Strip prior test load so the new env takes effect on import.
    _sys.modules.pop("save_candidates_hook_emit", None)
    spec = importlib.util.spec_from_file_location(
        "save_candidates_hook_emit",
        Path(__file__).resolve().parents[2]
        / "scripts" / "hooks" / "save_candidates.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_emit_mode_defaults_to_state(monkeypatch, tmp_path):
    """Default behavior is preserved — Claude Code's existing hook chain
    relies on the state-file path. Touching ``_EMIT_MODE`` parsing must not
    silently flip the default."""
    monkeypatch.delenv("GAOTTT_SAVE_CANDIDATES_EMIT", raising=False)
    monkeypatch.setenv(
        "GAOTTT_SAVE_CANDIDATES_STATE_DIR", str(tmp_path / "state"),
    )
    mod = _load_hook_module(monkeypatch)
    assert mod._EMIT_MODE == "state"


def test_emit_mode_stdout_writes_to_stdout_not_state_file(
    monkeypatch, tmp_path, capfd,
):
    """opencode plugin path — ``EMIT=stdout`` must (a) print the block to
    stdout and (b) NOT create a state file. The two output modes are
    mutually exclusive at runtime so the opencode plugin can rely on
    capturing stdout synchronously."""
    state_dir = tmp_path / "state"
    monkeypatch.setenv("GAOTTT_SAVE_CANDIDATES_EMIT", "stdout")
    monkeypatch.setenv("GAOTTT_SAVE_CANDIDATES_STATE_DIR", str(state_dir))
    mod = _load_hook_module(monkeypatch)

    sentinel_block = (
        "<gaottt-save-candidates>\n"
        "test sentinel block\n"
        "</gaottt-save-candidates>"
    )

    async def _fake_call(_transcript: str) -> str:
        return sentinel_block

    monkeypatch.setattr(mod, "_call_save_candidates", _fake_call)
    monkeypatch.setattr(
        "sys.stdin",
        __import__("io").StringIO(
            '{"session_id": "test-session", '
            '"transcript": "[user] foo\\n\\n[assistant] bar"}',
        ),
    )

    rc = mod.main()
    captured = capfd.readouterr()
    assert rc == 0
    assert "test sentinel block" in captured.out
    assert captured.out.startswith("<gaottt-save-candidates>")
    # No state file should be created in stdout mode — the opencode plugin
    # reads stdout synchronously, the state-file bridge is Claude-Code-only.
    assert not state_dir.exists() or not list(state_dir.iterdir())


def test_emit_mode_state_writes_state_file_not_stdout(
    monkeypatch, tmp_path, capfd,
):
    """Mirror test for the default Claude Code path — the state file is
    written and stdout stays empty (Claude Code's Stop hook stdout is shown
    to the user as a `hook_success` record, not auto-injected, so the
    state-file bridge is what actually carries the block forward)."""
    state_dir = tmp_path / "state"
    monkeypatch.setenv("GAOTTT_SAVE_CANDIDATES_EMIT", "state")
    monkeypatch.setenv("GAOTTT_SAVE_CANDIDATES_STATE_DIR", str(state_dir))
    mod = _load_hook_module(monkeypatch)

    sentinel_block = (
        "<gaottt-save-candidates>\n"
        "claude-code path sentinel\n"
        "</gaottt-save-candidates>"
    )

    async def _fake_call(_transcript: str) -> str:
        return sentinel_block

    monkeypatch.setattr(mod, "_call_save_candidates", _fake_call)
    monkeypatch.setattr(
        "sys.stdin",
        __import__("io").StringIO(
            '{"session_id": "claude-sess-1", '
            '"transcript": "[user] foo\\n\\n[assistant] bar"}',
        ),
    )

    rc = mod.main()
    captured = capfd.readouterr()
    assert rc == 0
    assert captured.out.strip() == ""
    state_file = state_dir / "claude-sess-1.txt"
    assert state_file.exists()
    assert "claude-code path sentinel" in state_file.read_text(encoding="utf-8")


# --- Plans-Lens-Hygiene Stage 1: meta-extraction loop regression ---

def _make_recursive_transcript() -> str:
    """A transcript that contains a previously-injected <gaottt-save-candidates>
    block — exactly the shape that arrives at the next turn's Stop event after
    UserPromptSubmit injection. The block is the one observed live in the
    2026-05-27 verification (PR #28 review), reduced to the parts that trigger
    the regression."""
    return (
        "[user] こんにちは、今日も作業を進めていこう。\n"
        "\n"
        "<gaottt-save-candidates>\n"
        "GaOTTT が直前ターンから抽出した save 候補です（観察層: lens で見せ"
        "ています、save するかは agent の判断）。\n"
        "判断 filter: 未来の判断を変える insight/pattern なら save。"
        "bug fix の途中経過・fact 単体・code snippet は git log・diff・"
        "code に任せる。\n"
        "\n"
        "▼ 候補 (score 順)\n"
        " 1. [score=2.20, source=agent, tags=['design-decision']] "
        "[assistant] Next.js を採用することを決定した。\n"
        "    reason: 決定/結論キーワード, 適度な長さ\n"
        " 2. [score=1.90, source=agent, tags=['letter-to-future-self']] "
        "次に ToDo.md §8 に follow-up を追記。\n"
        "    reason: 教訓/次回への申し送り\n"
        "\n"
        "▼ いま誰として\n"
        " · intention: harakiriworks-art-website のプロジェクトノウハウを "
        "GaOTTT に体系的な重力場として残す。\n"
        "<!-- save-candidates count=2 -->\n"
        "</gaottt-save-candidates>\n"
        "\n"
        "[assistant] わかりました、それで進めましょう。実際の作業は別の "
        "API を採用することにします。"
    )


def test_strip_gaottt_blocks_removes_save_candidates_block():
    """Pure-function test for the regex helper. The strip must remove the
    entire <gaottt-save-candidates>…</gaottt-save-candidates> block (multi-line,
    DOTALL) and leave the surrounding user/assistant text intact."""
    from gaottt.services.memory import _strip_gaottt_blocks
    transcript = _make_recursive_transcript()
    stripped = _strip_gaottt_blocks(transcript)
    # Surrounding human turns remain
    assert "今日も作業を進めていこう" in stripped
    assert "別の API を採用することにします" in stripped
    # Block content gone
    assert "<gaottt-save-candidates>" not in stripped
    assert "</gaottt-save-candidates>" not in stripped
    assert "Next.js を採用することを決定した" not in stripped
    assert "次に ToDo.md §8" not in stripped
    assert "save-candidates count=2" not in stripped
    assert "判断 filter:" not in stripped


def test_strip_gaottt_blocks_removes_ambient_recall_block():
    """Same strip must work for ambient_recall blocks too — they follow the
    same naming convention (<gaottt-…>…</gaottt-…>) so a single regex covers
    every current and future lens block."""
    from gaottt.services.memory import _strip_gaottt_blocks
    transcript = (
        "[user] 進捗どう?\n"
        "\n"
        "<gaottt-ambient-recall>\n"
        "GaOTTT 長期記憶から自動取得した関連知識です。\n"
        "▼ 直接ヒット\n"
        " 1. [agent · certainty 0.90 · 0d] 失敗事例 — KUW-102\n"
        "</gaottt-ambient-recall>\n"
        "\n"
        "[assistant] 順調です。"
    )
    stripped = _strip_gaottt_blocks(transcript)
    assert "[user] 進捗どう?" in stripped
    assert "[assistant] 順調です。" in stripped
    assert "<gaottt-ambient-recall>" not in stripped
    assert "KUW-102" not in stripped


def test_strip_gaottt_blocks_handles_multiple_blocks_in_one_text():
    """Defensive — when both ambient_recall AND save_candidates are injected
    into the same user turn (the typical Claude Code + opencode setup), the
    strip must remove every block, not just the first."""
    from gaottt.services.memory import _strip_gaottt_blocks
    transcript = (
        "[user] テスト\n"
        "<gaottt-ambient-recall>\n A \n</gaottt-ambient-recall>\n"
        "<gaottt-save-candidates>\n B \n</gaottt-save-candidates>\n"
        "[assistant] OK"
    )
    stripped = _strip_gaottt_blocks(transcript)
    assert "<gaottt-" not in stripped
    assert "[user] テスト" in stripped
    assert "[assistant] OK" in stripped


def test_strip_gaottt_blocks_leaves_unrelated_text_intact():
    """A user message that literally mentions gaottt tag names in prose
    (without the angle-bracketed open/close pair) must survive — the regex
    only matches well-formed open+close tag pairs."""
    from gaottt.services.memory import _strip_gaottt_blocks
    text = "[user] gaottt-save-candidates の仕様について議論したい。"
    assert _strip_gaottt_blocks(text) == text


def test_auto_remember_does_not_leak_prior_block_content():
    """End-to-end heuristic regression — the live failure mode observed in
    PR #28 acceptance: feeding a transcript that includes a prior block to
    extract_candidates leaked 4 candidates derived from the block itself
    (prior candidates, "judgment filter" line scoring as troubleshooting via
    the literal "bug fix" keyword, "reason:" lines, "<!-- save-candidates -->"
    manifest). After the strip, none of these may surface."""
    from gaottt.services.memory import _strip_gaottt_blocks
    from gaottt.core.extractor import extract_candidates

    transcript = _make_recursive_transcript()
    cleaned = _strip_gaottt_blocks(transcript)
    candidates = extract_candidates(cleaned, max_candidates=10, min_score=0.5)

    contents = " | ".join(c.content for c in candidates)
    # The 4 documented leaks from the verification fixture
    assert "Next.js を採用することを決定した" not in contents, \
        "prior-block candidate #1 leaked"
    assert "次に ToDo.md §8" not in contents, "prior-block candidate #2 leaked"
    assert "判断 filter:" not in contents, "policy filter line leaked"
    assert "save-candidates count=" not in contents, "block manifest leaked"
    # And the user/assistant turns survive — the strip must NOT eat the
    # actual content the heuristic should still see (it just must not see
    # the lens artifact).
    survives_real_text = any(
        "別の API を採用することにします" in c.content for c in candidates
    )
    assert survives_real_text, (
        "the actual assistant decision should still be extracted after strip; "
        f"got {[c.content[:50] for c in candidates]}"
    )
