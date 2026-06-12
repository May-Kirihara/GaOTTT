#!/usr/bin/env python3
"""GaOTTT Save Candidates — Stop / turn-end hook.

Reads the Claude Code ``Stop`` event payload from stdin, scans the
transcript for the last few exchanges, calls the GaOTTT MCP backend's
``save_candidates`` tool, and writes the resulting
``<gaottt-save-candidates>`` block to a per-session state file. A
companion ``UserPromptSubmit`` hook (``save_candidates_inject.py``)
reads + clears that file at the start of the *next* turn and emits the
block into the model's context — option A from
``docs/wiki/Plans-Save-Candidates-Hook.md``.

Block injection is split across two hooks because Claude Code's Stop
hook ``stdout`` is shown to the user (as a ``hook_success`` record) but
does NOT automatically inject into the next system prompt. The state
file bridges the gap while keeping each hook a small, fail-safe unit.

Architecture mirrors ``scripts/hooks/ambient_recall.py``:
  - same MCP backend (proxy mode on port 7878), no separate engine
  - same passive / fail-safe contract: any error → exit 0, no output
  - same payload-shape parity: Claude Code's ``transcript_path`` is
    scanned here; opencode plugins (future v2) will pre-extract
    ``transcript`` and pass it directly.

Codex CLI: registered as a ``Stop`` command hook in ~/.codex/hooks.json.
The Stop side needs no output-format change (it writes the per-session
state file in ``state`` mode regardless of frontend); the only Codex
adaptation is that ``_build_transcript_from_path`` also understands Codex's
rollout JSONL (``event_msg`` / ``user_message`` + ``agent_message``). The
paired ``save_candidates_inject.py`` UserPromptSubmit hook is what carries
the ``--codex`` JSON-envelope output the next turn.

stdin payload (JSON, Claude Code Stop hook shape):
  session_id        (str)  Claude Code's session UUID, used for the
                           state-file name (per-session bridge).
  transcript_path   (str)  path to the session transcript JSONL.
  transcript        (str)  (opencode v2) pre-extracted transcript text;
                           bypasses transcript_path scanning when set.

Tunables (environment variables):
  GAOTTT_SAVE_CANDIDATES_ENABLED      "0"/"false"/"off" disables (default on)
  GAOTTT_SAVE_CANDIDATES_URL          MCP backend URL
                                      (default http://127.0.0.1:7878/mcp)
  GAOTTT_SAVE_CANDIDATES_TIMEOUT      hard timeout in seconds (default 3.0).
                                      ``save_candidates`` is heuristic only
                                      (no embedder), steady-state ~10-50ms;
                                      3s budget covers cold-start MCP setup.
  GAOTTT_SAVE_CANDIDATES_MAX          max candidates to surface (default 3).
  GAOTTT_SAVE_CANDIDATES_TURNS        number of preceding exchanges (user +
                                      assistant pairs) to feed the heuristic
                                      (default 2).
  GAOTTT_SAVE_CANDIDATES_STATE_DIR    per-session state-file directory
                                      (default ~/.gaottt/save_candidates).
  GAOTTT_SAVE_CANDIDATES_INCLUDE_PERSONA  "0" omits the persona slot
                                      (default on).
  GAOTTT_SAVE_CANDIDATES_EMIT         output mode (default ``state``):
                                      ``state``  → write to per-session
                                                   state file (Claude Code,
                                                   needs paired inject hook)
                                      ``stdout`` → print block to stdout
                                                   (opencode plugin et al.,
                                                   one-shot inject path)
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import tempfile
from pathlib import Path

_URL = os.environ.get(
    "GAOTTT_SAVE_CANDIDATES_URL", "http://127.0.0.1:7878/mcp",
)
_TIMEOUT = float(os.environ.get("GAOTTT_SAVE_CANDIDATES_TIMEOUT", "3.0"))
try:
    _MAX_CANDIDATES = max(1, int(
        os.environ.get("GAOTTT_SAVE_CANDIDATES_MAX", "3"),
    ))
except (TypeError, ValueError):
    _MAX_CANDIDATES = 3
try:
    _HISTORY_TURNS = max(1, int(
        os.environ.get("GAOTTT_SAVE_CANDIDATES_TURNS", "2"),
    ))
except (TypeError, ValueError):
    _HISTORY_TURNS = 2
_STATE_DIR = Path(
    os.environ.get(
        "GAOTTT_SAVE_CANDIDATES_STATE_DIR",
        str(Path.home() / ".gaottt" / "save_candidates"),
    )
).expanduser()
_INCLUDE_PERSONA = os.environ.get(
    "GAOTTT_SAVE_CANDIDATES_INCLUDE_PERSONA", "1",
).strip().lower() not in ("0", "false", "no", "off", "")
_EMIT_MODE = os.environ.get(
    "GAOTTT_SAVE_CANDIDATES_EMIT", "state",
).strip().lower()

_BLOCK_TAG = "<gaottt-save-candidates>"

_INJECTED_BLOCK_TAGS = [
    "gaottt-ambient-recall",
    "gaottt-save-candidates",
    "system-reminder",
    "command-name",
    "command-message",
    "command-args",
    "local-command-stdout",
    "local-command-caveat",
]
_INJECTED_BLOCK_PATTERN = re.compile(
    "|".join(
        rf"<{tag}>.*?</{tag}>" for tag in _INJECTED_BLOCK_TAGS
    ),
    re.DOTALL,
)


def _strip_injected_surfaces(text: str) -> str:
    """Remove instruction-surface artifacts from transcript text.

    Strips injected blocks that are neither user nor agent speech:
    gaottt lens blocks, system-reminder, and Claude Code local-command
    injection tags.  If the text starts with ``Base directory for this
    skill:`` the entire text is cleared (it is a Skill-tool content dump).

    Plans-Observation-Apparatus-Round-2 Stage C.
    """
    if text.startswith("Base directory for this skill:"):
        return ""
    return _INJECTED_BLOCK_PATTERN.sub("", text).strip()


def _disabled() -> bool:
    return os.environ.get(
        "GAOTTT_SAVE_CANDIDATES_ENABLED", "1",
    ).strip().lower() in ("0", "false", "no", "off", "")


def _extract_text(rec: dict) -> str:
    """Extract only the human-authored text from a Claude Code transcript
    record. Skips ``tool_use`` / ``tool_result`` / ``thinking`` blocks — the
    heuristic should see what the human said, not the bash output the agent
    produced. Returns empty string when the record carries no real text
    (the caller filters those out so they don't count toward the turn budget).
    """
    msg = rec.get("message") if isinstance(rec.get("message"), dict) else rec
    content = msg.get("content") if isinstance(msg, dict) else None
    if content is None:
        content = rec.get("content")
    if isinstance(content, str):
        return _strip_injected_surfaces(content.strip())
    if isinstance(content, list):
        parts: list[str] = []
        for c in content:
            if not isinstance(c, dict):
                continue
            # Claude Code JSONL puts conversation text in ``type=text`` blocks.
            # ``tool_use`` / ``tool_result`` / ``thinking`` blocks live in the
            # same record and would otherwise flood the heuristic with bash
            # output, internal reasoning, or tool name strings — all garbage
            # for "what looks save-worthy in the conversation".
            if c.get("type") != "text":
                continue
            t = c.get("text")
            if isinstance(t, str):
                parts.append(t)
        return _strip_injected_surfaces(" ".join(parts).strip())
    return ""


def _build_transcript_from_path(path: str, turns: int) -> str:
    """Last ``turns`` user+assistant exchange pairs from the JSONL transcript,
    formatted as a single string for the auto_remember heuristic.

    Returns ``""`` on missing file / parse failure — fail-safe to no
    candidate (hook exits 0).
    """
    if not path or turns <= 0:
        return ""
    try:
        exchanges: list[tuple[str, str]] = []  # (role, text) oldest→newest
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                # Codex rollout JSONL: the clean per-turn user / assistant
                # text lives in ``event_msg`` (``user_message`` /
                # ``agent_message``). The parallel ``response_item`` messages
                # also carry synthetic env/permission/tool blocks, so we read
                # only the event_msg stream — same reasoning as the ambient
                # hook. A Claude transcript has no ``event_msg`` records, so
                # this branch is inert there.
                if rec.get("type") == "event_msg":
                    p = rec.get("payload")
                    if isinstance(p, dict):
                        pt = p.get("type")
                        t = p.get("message")
                        if isinstance(t, str) and t.strip():
                            t_clean = _strip_injected_surfaces(t.strip())
                            if t_clean:
                                if pt == "user_message":
                                    exchanges.append(("user", t_clean))
                                elif pt == "agent_message":
                                    exchanges.append(("assistant", t_clean))
                    continue
                role = rec.get("type") or rec.get("role")
                if role not in ("user", "assistant"):
                    continue
                text = _extract_text(rec)
                if text:
                    exchanges.append((role, text))
        if not exchanges:
            return ""
        # A turn = 1 user + 1 assistant message. Take the last ``turns * 2``
        # entries as a generous slice (handles trailing-user or
        # trailing-assistant transcripts uniformly).
        slice_n = min(len(exchanges), turns * 2)
        recent = exchanges[-slice_n:]
        return "\n\n".join(f"[{r}] {t}" for r, t in recent)
    except Exception:
        return ""


async def _call_save_candidates(transcript: str) -> str | None:
    """Call the GaOTTT MCP backend's ``save_candidates`` tool."""
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    args: dict = {
        "transcript": transcript,
        "max_candidates": _MAX_CANDIDATES,
        "include_reasons": True,
        "include_persona": _INCLUDE_PERSONA,
    }
    async with streamablehttp_client(_URL) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool("save_candidates", args)
    if getattr(result, "isError", False):
        return None
    parts = [
        t for t in (getattr(b, "text", None) for b in result.content) if t
    ]
    return "\n".join(parts).strip() or None


def _state_path(session_id: str) -> Path:
    # Sanitize session_id to filesystem-safe characters (Claude Code uses
    # UUIDs which are already safe, but defensive against opencode session
    # ids that may include hyphens / dots).
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in session_id)
    return _STATE_DIR / f"{safe}.txt"


def main() -> int:
    if _disabled():
        return 0
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    session_id = str(payload.get("session_id") or "default")
    # opencode (v2) pre-extracted transcript wins; Claude Code falls back to
    # scanning transcript_path. Either path lands on the same downstream
    # call — same parity convention as ambient_recall.
    transcript = str(payload.get("transcript") or "").strip()
    if transcript:
        transcript = _strip_injected_surfaces(transcript)
    if not transcript:
        transcript_path = str(payload.get("transcript_path") or "")
        transcript = _build_transcript_from_path(
            transcript_path, _HISTORY_TURNS,
        )
    if not transcript:
        return 0
    try:
        block = asyncio.run(
            asyncio.wait_for(
                _call_save_candidates(transcript),
                timeout=_TIMEOUT,
            ),
        )
    except Exception:
        return 0
    if not block or not block.lstrip().startswith(_BLOCK_TAG):
        # Sentinel "(保存候補なし)" — stay silent, no state-file write.
        return 0
    if _EMIT_MODE == "stdout":
        # Direct os.write to dodge the block-buffering pitfall the ambient
        # recall hook documents (asyncio teardown can drop a buffered final
        # write). Used by the opencode plugin's chat.message path — no state
        # file bridge needed there, the block is injected synchronously.
        data = (block if block.endswith("\n") else block + "\n").encode(
            "utf-8", errors="replace",
        )
        fd = sys.stdout.fileno()
        while data:
            data = data[os.write(fd, data):]
        return 0
    try:
        _STATE_DIR.mkdir(parents=True, exist_ok=True)
        target = _state_path(session_id)
        fd, tmp_path = tempfile.mkstemp(
            dir=str(_STATE_DIR), prefix=".save-cand-", suffix=".tmp",
        )
        try:
            os.write(fd, block.encode("utf-8"))
            os.close(fd)
            fd = -1
            os.replace(tmp_path, str(target))
        except BaseException:
            if fd >= 0:
                os.close(fd)
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
