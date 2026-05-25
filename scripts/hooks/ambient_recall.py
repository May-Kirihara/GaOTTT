#!/usr/bin/env python3
"""GaOTTT Ambient Recall — Claude Code ``UserPromptSubmit`` hook.

Reads the submitted prompt from stdin, calls the GaOTTT MCP backend's
``ambient_recall`` tool — a structured, passive (read-only, non-perturbing)
recall — and emits the resulting ``<gaottt-ambient-recall>`` block as
additional context for the turn, so long-term memory surfaces automatically
without the model having to call ``recall`` itself.

``ambient_recall`` (Ambient Recall Enrichment) does the relevance gating and
slot composition server-side: direct hits + a gravitational-lensing pick +
provenance metadata (+ reasoning / contradiction / persona). It returns the
ready ``<gaottt-ambient-recall>`` block, or a non-block sentinel when nothing
clears the relevance gate — this hook emits the former and stays silent on
the latter.

Passive throughout: this hook never moves the gravity field.

Fail-safe by construction: any error, timeout, or unreachable backend yields
zero output and exit 0 — the user's prompt is never blocked.

Connects to the single shared engine process (the proxy-mode MCP backend on
port 7878), so it adds no second engine, no second RURI load, and no
write-behind contention.

stdin payload (JSON):
  prompt            (str, required) the user's submitted prompt text
  transcript_path   (str, optional) Claude Code's transcript JSONL path; when
                    present and ``history`` / ``recently_surfaced`` below are
                    NOT supplied, the hook scans this for the past N user
                    prompts and ambient-block ids manifests.
  history           (list[str], optional) past user prompts oldest→newest,
                    forwarded by frontends that don't write a transcript
                    file (opencode). Bypasses transcript scanning when given.
  recently_surfaced (dict[str, int], optional) {node_id: count of recent
                    surfaces} forwarded by the same frontends. Bypasses
                    transcript scanning when given. The server multiplies
                    each slot's ranking by
                    ``ambient_novelty_decay ** count`` (Lateral Association
                    Stage 1).

Frontend parity: Claude Code passes ``{prompt, transcript_path}`` and lets
the hook do the scanning; opencode passes ``{prompt, history,
recently_surfaced}`` having extracted them via the OpenCode SDK message
list. The two paths converge at the same downstream variables, so Stage 1
novelty + Refinement Stage 4 multi-turn behave identically across both
frontends with no per-frontend branching in the hook.

Tunables (environment variables):
  GAOTTT_AMBIENT_RECALL     "0"/"false"/"off" disables the hook (default on)
  GAOTTT_AMBIENT_URL        MCP backend URL (default http://127.0.0.1:7878/mcp)
  GAOTTT_AMBIENT_DIRECT_K   number of direct-hit results (default 2)
  GAOTTT_AMBIENT_MIN_SCORE  *fallback* virtual_score-gate threshold. The
                            primary relevance gate is BM25 lexical, applied
                            server-side (config.ambient_bm25_min_score) — this
                            env only matters when BM25 is disabled/unavailable.
                            Unset → server default.
  GAOTTT_AMBIENT_TIMEOUT    hard timeout in seconds (default 6.0). Steady-state
                            ambient_recall is ~0.5s, but the first few minutes
                            after a backend (re)start can be ~3-4s while
                            virtual FAISS / caches warm up.
  GAOTTT_AMBIENT_MIN_CHARS  skip prompts shorter than this (default 12)
  GAOTTT_AMBIENT_EXCLUDE_TAGS  comma-separated tag substrings to drop from
                            direct / lensing / persona candidates (default
                            "smoke-test,test"). Keeps test artifacts out of
                            ambient injection without deleting them — see
                            Plans-Ambient-Recall-Refinement.md Stage 2.
                            Empty string disables the exclusion.
  GAOTTT_AMBIENT_EXPOSE_BREAKDOWN  "1"/"true" appends a per-slot
                            [raw=.. virt=.. bm25 mass=..] suffix so the
                            caller can see why each memory surfaced
                            (Refinement Stage 3). Default off — adds tokens
                            to every ambient block, opt-in for debug only.
  GAOTTT_AMBIENT_HISTORY_TURNS  Number of preceding user prompts to read
                            from the Claude Code transcript_path and
                            concatenate with the current prompt before the
                            ambient_recall query (default 2). 0 disables
                            (current prompt only — legacy behavior). Fails
                            silently to current-prompt-only when the
                            transcript file is missing or unreadable. See
                            Plans-Ambient-Recall-Refinement.md Stage 4.
  GAOTTT_AMBIENT_NOVELTY_TURNS  Number of preceding ambient_recall turns to
                            scan from the transcript for the
                            ``<!-- ambient-ids ... -->`` manifest, building
                            a ``{node_id: count}`` map forwarded to the
                            server as ``recently_surfaced``. The server
                            multiplies each slot's ranking score by
                            ``config.ambient_novelty_decay ** count``,
                            rotating recently-surfaced memos out of slot
                            1-2 turns (the "〇〇といえば〜だったよな"
                            controlled-novelty channel). Default 5; 0
                            disables (legacy — no decay forwarded). See
                            Plans-Ambient-Recall-Lateral-Association.md
                            Stage 1.
  GAOTTT_AMBIENT_SHOW_COMPOSED_QUERY  Debug-only. When "1"/"true"/"on",
                            the hook appends
                            ``<!-- ambient: composed query = "..." -->``
                            just before the block's closing tag so the
                            agent can see *exactly* what query was sent to
                            the server. Useful when the multi-turn
                            concatenation (``GAOTTT_AMBIENT_HISTORY_TURNS``)
                            seems to produce unexpected surfaces — the
                            line lets you separate "the query was wrong"
                            from "the recall was wrong". Off by default;
                            no-op when the composed query equals the bare
                            user prompt (concatenation didn't add
                            anything). Adds 50-200 chars per block. See
                            Plans-Ambient-Recall-Lateral-Association.md
                            Stage 4.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys

_URL = os.environ.get("GAOTTT_AMBIENT_URL", "http://127.0.0.1:7878/mcp")
_DIRECT_K = int(os.environ.get("GAOTTT_AMBIENT_DIRECT_K", "2"))
_TIMEOUT = float(os.environ.get("GAOTTT_AMBIENT_TIMEOUT", "6.0"))
_MIN_CHARS = int(os.environ.get("GAOTTT_AMBIENT_MIN_CHARS", "12"))
# Optional explicit relevance-gate override; unset → server config decides.
_MIN_SCORE_ENV = os.environ.get("GAOTTT_AMBIENT_MIN_SCORE")
# Refinement Stage 2 — substring tag exclusion. Default keeps MCP/REST smoke
# memories silent in ambient injection. Empty string ("") = no exclusion.
_EXCLUDE_TAGS = [
    t.strip()
    for t in os.environ.get("GAOTTT_AMBIENT_EXCLUDE_TAGS", "smoke-test,test").split(",")
    if t.strip()
]
# Refinement Stage 3 — opt-in score-breakdown rendering. Default off so the
# ambient block stays compact; "1" / "true" / "on" enable the inline suffix.
_EXPOSE_BREAKDOWN = os.environ.get(
    "GAOTTT_AMBIENT_EXPOSE_BREAKDOWN", "0",
).strip().lower() in ("1", "true", "yes", "on")
# Refinement Stage 4 — number of preceding user prompts to prepend to the
# current prompt as context. 0 = legacy (current prompt only). Negative or
# invalid values fall back to 0 silently.
try:
    _HISTORY_TURNS = max(0, int(os.environ.get("GAOTTT_AMBIENT_HISTORY_TURNS", "2")))
except (TypeError, ValueError):
    _HISTORY_TURNS = 0
# Lateral Association Stage 1 — how many recent ambient turns to scan from the
# transcript for ``<!-- ambient-ids ... -->`` manifests. 0 disables (no
# ``recently_surfaced`` forwarded → server applies no novelty decay).
try:
    _NOVELTY_TURNS = max(0, int(os.environ.get("GAOTTT_AMBIENT_NOVELTY_TURNS", "5")))
except (TypeError, ValueError):
    _NOVELTY_TURNS = 0
# Lateral Association Stage 4 — opt-in debug knob. When on, the hook appends
# ``<!-- ambient: composed query = "..." -->`` just before the block's
# closing tag, so the agent can see *exactly* what query was sent to the
# server (the multi-turn-composed prompt, not the bare user input).
# Default off — adds ~50-200 chars of token budget per ambient block, only
# useful when debugging Refinement Stage 4's multi-turn context behaviour.
_SHOW_COMPOSED_QUERY = os.environ.get(
    "GAOTTT_AMBIENT_SHOW_COMPOSED_QUERY", "0",
).strip().lower() in ("1", "true", "yes", "on")

_BLOCK_TAG = "<gaottt-ambient-recall>"
_CLOSE_TAG = "</gaottt-ambient-recall>"
# ``<!-- ambient-ids direct=id1,id2 lensing=id3 persona=id4 -->`` —
# emitted by ``services.formatters.format_ambient`` at the bottom of every
# successful ambient block. Tolerant: missing keys are simply absent.
_AMBIENT_IDS_RE = re.compile(
    r"<!--\s*ambient-ids\s+(.+?)\s*-->",
)


def _extract_user_text(rec: dict) -> str:
    """Best-effort text extraction from a transcript record. Tolerates the
    Claude Code shapes seen in practice:
      - ``{"type": "user", "message": {"content": "..."}}``
      - ``{"type": "user", "message": {"content": [{"type":"text","text":"..."}]}}``
      - ``{"role": "user", "content": "..." | [...]}``
    """
    msg = rec.get("message") if isinstance(rec.get("message"), dict) else rec
    content = msg.get("content") if isinstance(msg, dict) else None
    if content is None:
        content = rec.get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for c in content:
            if isinstance(c, dict):
                t = c.get("text") or c.get("content")
                if isinstance(t, str):
                    parts.append(t)
        return " ".join(parts).strip()
    return ""


def _recent_user_prompts(transcript_path: str | None, n: int) -> list[str]:
    """Last ``n`` user prompts from the Claude Code transcript, oldest →
    newest. Returns ``[]`` on missing file / parse failure / n<=0 —
    fail-safe to current-prompt-only behavior."""
    if not transcript_path or n <= 0:
        return []
    try:
        prompts: list[str] = []
        with open(transcript_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                if rec.get("type") == "user" or rec.get("role") == "user":
                    text = _extract_user_text(rec)
                    if text:
                        prompts.append(text)
        return prompts[-n:] if prompts else []
    except Exception:
        return []


def _compose_query(current: str, history: list[str]) -> str:
    """Concatenate ``history`` (oldest→newest) with the current prompt,
    after dropping any trailing exact-match duplicate (the transcript often
    already includes the current prompt as its last entry)."""
    cleaned = list(history)
    while cleaned and cleaned[-1].strip() == current.strip():
        cleaned.pop()
    if not cleaned:
        return current
    return "\n".join(cleaned + [current])


def _inject_composed_query_debug(block: str, prompt: str, composed: str) -> str:
    """Lateral Association Stage 4 — append an HTML-comment line with the
    composed query just before the block's closing tag.

    Returns ``block`` unchanged when:
      - the block does not look like our ambient block (no close tag), OR
      - ``composed == prompt`` (no multi-turn concatenation happened — the
        debug line would just duplicate the user input).

    Newlines inside the composed query are escaped to ``\\n`` so the comment
    stays a single line that other parsers (and ``_recently_surfaced``'s
    line-by-line transcript reader) don't trip on.
    """
    if _CLOSE_TAG not in block:
        return block
    if composed.strip() == prompt.strip():
        return block
    escaped = composed.replace("\\", "\\\\").replace("\n", "\\n")
    debug_line = f'<!-- ambient: composed query = "{escaped}" -->'
    return block.replace(_CLOSE_TAG, f"{debug_line}\n{_CLOSE_TAG}", 1)


def _ids_from_manifest(text: str) -> list[str]:
    """Extract every node id from a single ``<!-- ambient-ids ... -->`` line.

    The manifest contains slot=id1,id2 tokens; this returns the flat list of
    ids across all slots (the novelty map only counts occurrences, not slot
    membership). Empty list when no manifest is present.
    """
    m = _AMBIENT_IDS_RE.search(text)
    if not m:
        return []
    payload = m.group(1)
    ids: list[str] = []
    # Each space-separated chunk is "slot=id" or "slot=id1,id2".
    for chunk in payload.split():
        if "=" not in chunk:
            continue
        _, _, rhs = chunk.partition("=")
        for nid in rhs.split(","):
            nid = nid.strip()
            if nid:
                ids.append(nid)
    return ids


def _recently_surfaced(transcript_path: str | None, n: int) -> dict[str, int]:
    """Walk the transcript newest→oldest collecting ids from the most recent
    ``n`` ambient blocks emitted by this hook. Returns a ``{id: count}`` map
    suitable for forwarding as the ``recently_surfaced`` arg.

    The hook emits ambient blocks via the ``UserPromptSubmit`` event; Claude
    Code stores the stdout under an ``attachment.type == "hook_success"``
    record with ``hookName == "UserPromptSubmit"``. We scan those records'
    ``content`` / ``stdout`` for the manifest, picking up to ``n`` blocks.

    Fail-safe to ``{}`` on missing file / parse failure / ``n <= 0`` (the
    server then applies no novelty decay).
    """
    if not transcript_path or n <= 0:
        return {}
    try:
        ambient_texts: list[str] = []
        with open(transcript_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                att = rec.get("attachment")
                if not isinstance(att, dict):
                    continue
                if att.get("type") != "hook_success":
                    continue
                if att.get("hookName") != "UserPromptSubmit":
                    continue
                text = att.get("content") or att.get("stdout") or ""
                if isinstance(text, str) and _BLOCK_TAG in text:
                    ambient_texts.append(text)
        if not ambient_texts:
            return {}
        recent = ambient_texts[-n:]
        counts: dict[str, int] = {}
        for text in recent:
            for nid in _ids_from_manifest(text):
                counts[nid] = counts.get(nid, 0) + 1
        return counts
    except Exception:
        return {}


def _disabled() -> bool:
    return os.environ.get("GAOTTT_AMBIENT_RECALL", "1").strip().lower() in (
        "0", "false", "no", "off", "",
    )


async def _ambient_recall(
    prompt: str, recently_surfaced: dict[str, int] | None = None,
) -> str | None:
    """Call the GaOTTT MCP backend's ``ambient_recall`` tool."""
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    args: dict = {"query": prompt, "direct_k": _DIRECT_K}
    if _MIN_SCORE_ENV is not None:
        try:
            args["min_score"] = float(_MIN_SCORE_ENV)
        except ValueError:
            pass
    if _EXCLUDE_TAGS:
        args["exclude_tags"] = _EXCLUDE_TAGS
    if _EXPOSE_BREAKDOWN:
        args["expose_breakdown"] = True
    if recently_surfaced:
        args["recently_surfaced"] = recently_surfaced
    async with streamablehttp_client(_URL) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool("ambient_recall", args)
    if getattr(result, "isError", False):
        return None
    parts = [
        t for t in (getattr(b, "text", None) for b in result.content) if t
    ]
    return "\n".join(parts).strip() or None


def _emit(text: str) -> None:
    """Write to the stdout file descriptor directly.

    A plain ``sys.stdout.write`` is block-buffered when stdout is a pipe/file
    (as it is under a Claude Code hook), and the asyncio/anyio teardown left
    by the MCP client makes the normal flush-on-exit unreliable — the buffered
    block is silently dropped. ``os.write`` is a synchronous syscall: once it
    returns the bytes are in the kernel. Loop to handle short writes.
    """
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
    prompt = str(payload.get("prompt") or "").strip()
    if len(prompt) < _MIN_CHARS:
        return 0
    # Frontend parity (2026-05-25, Lateral Association follow-up): the hook
    # accepts ``history`` and ``recently_surfaced`` directly in the payload.
    # Claude Code passes ``transcript_path`` and lets the hook scan; opencode
    # (which has no transcript file, only an SDK message list) builds the
    # equivalent maps in the plugin and passes them here. Either path lands
    # on the same downstream variables, so Stage 1 novelty + Refinement
    # Stage 4 multi-turn behave identically across frontends.
    transcript_path = str(payload.get("transcript_path") or "") or None
    history_in = payload.get("history")
    if isinstance(history_in, list):
        history = [str(h) for h in history_in if str(h).strip()]
    elif _HISTORY_TURNS > 0:
        history = _recent_user_prompts(transcript_path, _HISTORY_TURNS)
    else:
        history = []
    query = _compose_query(prompt, history) if history else prompt
    # Lateral Association Stage 1 — recently_surfaced may arrive directly
    # in the payload (opencode plugin) or be scanned from transcript
    # (Claude Code). Fail-safe to {} (no decay) in either case.
    recently_in = payload.get("recently_surfaced")
    if isinstance(recently_in, dict):
        recently = {str(k): int(v) for k, v in recently_in.items() if isinstance(v, (int, float))}
    else:
        recently = _recently_surfaced(transcript_path, _NOVELTY_TURNS)
    try:
        block = asyncio.run(
            asyncio.wait_for(
                _ambient_recall(query, recently_surfaced=recently or None),
                timeout=_TIMEOUT,
            ),
        )
    except Exception:
        # Backend down / slow / protocol error — stay silent, never block.
        return 0
    # The server returns the full <gaottt-ambient-recall> block only when the
    # relevance gate passed; otherwise a non-block sentinel. Emit only a block.
    if block and block.lstrip().startswith(_BLOCK_TAG):
        # Lateral Association Stage 4 — opt-in debug: append
        # ``<!-- ambient: composed query = "..." -->`` so the agent can see
        # exactly what was sent to the server (vs the bare user input).
        if _SHOW_COMPOSED_QUERY:
            block = _inject_composed_query_debug(block, prompt, query)
        _emit(block if block.endswith("\n") else block + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
