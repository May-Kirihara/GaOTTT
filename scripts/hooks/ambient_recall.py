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
"""
from __future__ import annotations

import asyncio
import json
import os
import sys

_URL = os.environ.get("GAOTTT_AMBIENT_URL", "http://127.0.0.1:7878/mcp")
_DIRECT_K = int(os.environ.get("GAOTTT_AMBIENT_DIRECT_K", "2"))
_TIMEOUT = float(os.environ.get("GAOTTT_AMBIENT_TIMEOUT", "6.0"))
_MIN_CHARS = int(os.environ.get("GAOTTT_AMBIENT_MIN_CHARS", "12"))
# Optional explicit relevance-gate override; unset → server config decides.
_MIN_SCORE_ENV = os.environ.get("GAOTTT_AMBIENT_MIN_SCORE")

_BLOCK_TAG = "<gaottt-ambient-recall>"


def _disabled() -> bool:
    return os.environ.get("GAOTTT_AMBIENT_RECALL", "1").strip().lower() in (
        "0", "false", "no", "off", "",
    )


async def _ambient_recall(prompt: str) -> str | None:
    """Call the GaOTTT MCP backend's ``ambient_recall`` tool."""
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    args: dict = {"query": prompt, "direct_k": _DIRECT_K}
    if _MIN_SCORE_ENV is not None:
        try:
            args["min_score"] = float(_MIN_SCORE_ENV)
        except ValueError:
            pass
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
    try:
        block = asyncio.run(
            asyncio.wait_for(_ambient_recall(prompt), timeout=_TIMEOUT),
        )
    except Exception:
        # Backend down / slow / protocol error — stay silent, never block.
        return 0
    # The server returns the full <gaottt-ambient-recall> block only when the
    # relevance gate passed; otherwise a non-block sentinel. Emit only a block.
    if block and block.lstrip().startswith(_BLOCK_TAG):
        _emit(block if block.endswith("\n") else block + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
