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

Tunables (environment variables):
  GAOTTT_SAVE_CANDIDATES_ENABLED      "0"/"false"/"off" disables (default on).
                                      Shared switch with the Stop side so a
                                      single env var kills both ends.
  GAOTTT_SAVE_CANDIDATES_STATE_DIR    per-session state-file directory
                                      (default ~/.gaottt/save_candidates).
                                      Must match the Stop side.
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
    except Exception:
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
    _emit(block if block.endswith("\n") else block + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
