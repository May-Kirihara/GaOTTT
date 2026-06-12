#!/usr/bin/env python3
"""GaOTTT Save Candidates — UserPromptSubmit inject hook.

Reads the per-session state file written by ``save_candidates.py`` at the
previous turn's Stop event, emits the ``<gaottt-save-candidates>`` block
to stdout (which Claude Code injects into the next prompt's context),
and deletes the state file so the same block never injects twice.

This is the second half of the Stop → UserPromptSubmit bridge described
in ``docs/wiki/Plans-Save-Candidates-Hook.md``. Split into two scripts
because Claude Code's Stop hook stdout is not auto-injected into the
next prompt; the state file is the durable handoff.

stdin payload (JSON, Claude Code UserPromptSubmit shape):
  session_id  (str)  session UUID matching the Stop hook's write.

Codex CLI: registered alongside the ambient hook on ``UserPromptSubmit`` in
~/.codex/hooks.json and invoked with ``--codex``. Codex does not inject a
hook's raw stdout; it reads a JSON envelope and pulls
``hookSpecificOutput.additionalContext`` from it. ``--codex`` (or
``GAOTTT_HOOK_OUTPUT=codex``) switches the emit path to that envelope. The
state-file handoff written by the Stop hook is identical across frontends.

Codex passes ``session_id`` in both the Stop and the next UserPromptSubmit
events; the state-file bridge relies on Codex providing the **same**
``session_id`` across both. If ``session_id`` changes between events the
read will find no state file and silently skip (fail-safe no-op, never blocks).

Tunables (environment variables):
  GAOTTT_SAVE_CANDIDATES_ENABLED      "0"/"false"/"off" disables (default on).
                                      Shared switch with the Stop side so a
                                      single env var kills both ends.
  GAOTTT_SAVE_CANDIDATES_STATE_DIR    per-session state-file directory
                                      (default ~/.gaottt/save_candidates).
                                      Must match the Stop side.
  GAOTTT_HOOK_OUTPUT                  output format. unset / "text" → raw
                                      stdout block (Claude Code / opencode).
                                      "codex" → JSON envelope (Codex CLI).
                                      The ``--codex`` CLI flag forces "codex".
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

_STATE_DIR = Path(
    os.environ.get(
        "GAOTTT_SAVE_CANDIDATES_STATE_DIR",
        str(Path.home() / ".gaottt" / "save_candidates"),
    )
).expanduser()


def _disabled() -> bool:
    return os.environ.get(
        "GAOTTT_SAVE_CANDIDATES_ENABLED", "1",
    ).strip().lower() in ("0", "false", "no", "off", "")


def _state_path(session_id: str) -> Path:
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in session_id)
    return _STATE_DIR / f"{safe}.txt"


def _emit(text: str) -> None:
    """Direct os.write to dodge the same block-buffering pitfall the ambient
    recall hook documents (asyncio teardown can drop a buffered final
    write)."""
    data = text.encode("utf-8", errors="replace")
    fd = sys.stdout.fileno()
    while data:
        data = data[os.write(fd, data):]


def _codex_output_mode() -> bool:
    """Whether to emit the Codex JSON envelope instead of raw stdout. Mirrors
    ``ambient_recall._codex_output_mode`` — ``--codex`` (passed by
    ~/.codex/hooks.json) or ``GAOTTT_HOOK_OUTPUT=codex``."""
    if "--codex" in sys.argv[1:]:
        return True
    return os.environ.get("GAOTTT_HOOK_OUTPUT", "").strip().lower() in (
        "codex", "codex-json",
    )


def _emit_codex(block: str, event_name: str = "UserPromptSubmit") -> None:
    """Emit the Codex ``hookSpecificOutput.additionalContext`` envelope."""
    payload = {
        "hookSpecificOutput": {
            "hookEventName": event_name,
            "additionalContext": block,
        },
    }
    _emit(json.dumps(payload, ensure_ascii=False))


def main() -> int:
    if _disabled():
        return 0
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    session_id = str(payload.get("session_id") or "default")
    path = _state_path(session_id)
    if not path.exists():
        return 0
    try:
        block = path.read_text(encoding="utf-8").strip()
    except (UnicodeDecodeError, OSError):
        try:
            path.unlink()
        except OSError:
            pass
        return 0
    # Delete before emit so a partial pipe-write doesn't leave the block to
    # re-inject next turn (worst case: block lost once, the heuristic just
    # re-surfaces a fresh one at the next Stop event).
    try:
        path.unlink()
    except Exception:
        pass
    if not block:
        return 0
    if _codex_output_mode():
        _emit_codex(block)
    else:
        _emit(block if block.endswith("\n") else block + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
