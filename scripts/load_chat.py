"""Load chat history into GaOTTT.

Supports three formats — auto-detected by extension and JSON shape:

* Claude Code transcripts (``*.jsonl``) — CLI session files
* OpenAI ChatGPT export (``conversations*.json``) — tree-structured, active
  path only
* Claude.ai web export (``conversations.json``) — linear ``chat_messages``

Each format is parsed turn-by-turn: one user prompt + the assistant reply
that follows = one document. CLI-injected rows / system / tool-result noise
is dropped by default. ``tool_use`` blocks are summarised as
``[tool:<name>] <hint>``; raw tool stdout is opt-in via
``--include-tool-results``.

Batching: when documents carry a ``conversation_id`` (or ``session_id``)
metadata key, batches are split on conversation boundaries so that each
conversation becomes one supernova cohort (turn-pair siblings then orbit
each other naturally under Phase L / K mechanics).

Usage::

    # Claude Code session
    python scripts/load_chat.py input/projects/.../<sessionId>.jsonl

    # whole project tree of Claude Code sessions
    python scripts/load_chat.py input/projects/-mnt-holyland-devs-maysweb/ -r

    # OpenAI ChatGPT export (single file or directory of conversations-*.json)
    python scripts/load_chat.py input/OpenAI/ --pattern 'conversations-*.json'

    # Claude.ai web export
    python scripts/load_chat.py input/claude-data/conversations.json

    # include tool output (noisier, larger DB)
    python scripts/load_chat.py <dir>/ -r --include-tool-results

    # see what would be ingested without sending
    python scripts/load_chat.py <session>.jsonl --dry-run
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import httpx

from gaottt.ingest.loader import ingest_path

DEFAULT_URL = "http://localhost:8000"
DEFAULT_BATCH = 50


def send_batch(client: httpx.Client, url: str, docs: list[dict]) -> tuple[int, int]:
    """POST a batch to /index. Returns (indexed, skipped)."""
    payload = {
        "documents": [
            {"content": d["content"], "metadata": d.get("metadata")}
            for d in docs
        ]
    }
    resp = client.post(f"{url}/index", json=payload, timeout=120.0)
    resp.raise_for_status()
    data = resp.json()
    return data["count"], data.get("skipped", 0)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Load Claude Code chat history (JSONL) into GaOTTT",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  %(prog)s input/projects/-mnt-holyland-devs-maysweb/<sessionId>.jsonl\n"
            "  %(prog)s ~/.claude/projects/-mnt-holyland-Project-GaOTTT/ -r\n"
            "  %(prog)s ./chats/ -r --include-tool-results\n"
        ),
    )
    parser.add_argument("path", help="JSONL/JSON file or directory of chat exports")
    parser.add_argument("--url", default=DEFAULT_URL, help="GaOTTT server URL")
    parser.add_argument("--pattern", default="*.jsonl,*.json",
                        help="Glob pattern(s), comma-separated "
                             "(default: '*.jsonl,*.json')")
    parser.add_argument("--recursive", "-r", action="store_true",
                        help="Recursively scan subdirectories")
    parser.add_argument("--source", default="file",
                        help="Source label override. Default ('file') lets the "
                             "loader pick per-format defaults: 'claude-code' for "
                             ".jsonl, 'openai' for OpenAI export, 'claude-web' for "
                             "Claude.ai export. Pass an explicit value to override.")
    parser.add_argument("--chunk-size", type=int, default=2000,
                        help="Max characters per chunk (default: 2000)")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH,
                        help="Documents per API request (default: 50)")
    parser.add_argument("--include-tool-results", action="store_true",
                        help="Include raw tool stdout/stderr content "
                             "(default: off — usually noisy)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be ingested without sending")
    args = parser.parse_args()

    p = Path(args.path)
    if not p.exists():
        print(f"ERROR: {args.path} does not exist", file=sys.stderr)
        sys.exit(1)

    print(f"Scanning: {args.path}")
    if p.is_dir():
        print(f"  Pattern: {args.pattern}, Recursive: {args.recursive}")
    if args.include_tool_results:
        print("  Including tool_result content")

    documents = ingest_path(
        args.path,
        source=args.source,
        recursive=args.recursive,
        pattern=args.pattern,
        chunk_size=args.chunk_size,
        include_tool_results=args.include_tool_results,
    )

    if not documents:
        print("No turns found (sample may be empty or contain only CLI noise).")
        sys.exit(0)

    # Summary by conversation/session. Use whichever id metadata the parser
    # populated (Claude Code → session_id, OpenAI/Claude.ai → conversation_id).
    def _conv_key(meta: dict) -> str:
        return (
            meta.get("conversation_id")
            or meta.get("session_id")
            or meta.get("file_name")
            or "?"
        )

    convs: dict[str, int] = {}
    sources_seen: dict[str, int] = {}
    sidechain_turns = 0
    for d in documents:
        meta = d.get("metadata", {})
        ck = _conv_key(meta)
        convs[ck] = convs.get(ck, 0) + 1
        sources_seen[meta.get("source", "?")] = sources_seen.get(meta.get("source", "?"), 0) + 1
        if meta.get("is_sidechain"):
            sidechain_turns += 1

    print(f"  Conversations: {len(convs)}")
    print(f"  Documents (turn chunks): {len(documents)}")
    print(f"  Sources: {sources_seen}")
    if sidechain_turns:
        print(f"  Sidechain turns: {sidechain_turns}")

    if args.dry_run:
        print("\n[DRY RUN] No documents sent.")
        for d in documents[:3]:
            meta = d.get("metadata", {})
            preview = d["content"][:140].replace("\n", " ")
            print(f"  [{_conv_key(meta)}#{meta.get('turn_index', '?')}] {preview}...")
        if len(documents) > 3:
            print(f"  ... and {len(documents) - 3} more")
        return

    try:
        httpx.get(f"{args.url}/docs", timeout=5.0)
    except httpx.ConnectError:
        print(f"\nERROR: Cannot connect to {args.url}. Is the server running?",
              file=sys.stderr)
        sys.exit(1)

    # Build batches: keep all turn-pairs from a single conversation together
    # so each conversation becomes one supernova cohort (Phase K). When a
    # single conversation exceeds batch_size, it is split — siblings still
    # share original_id so the Phase L self-force filter contains the
    # mass-inflation cost. Documents without a conversation id (legacy
    # plaintext/markdown) fall through to the fixed-size path.
    def _batched(docs: list[dict], cap: int) -> list[list[dict]]:
        batches: list[list[dict]] = []
        cur: list[dict] = []
        cur_key: str | None = None
        for d in docs:
            meta = d.get("metadata") or {}
            key = _conv_key(meta)
            if cur and (key != cur_key or len(cur) >= cap):
                batches.append(cur)
                cur = []
            cur.append(d)
            cur_key = key
        if cur:
            batches.append(cur)
        return batches

    batches = _batched(documents, args.batch_size)

    total_indexed = 0
    total_skipped = 0
    start = time.time()

    print(f"\nSending to {args.url}... ({len(batches)} batches)")
    with httpx.Client() as client:
        for idx, batch in enumerate(batches, start=1):
            try:
                indexed, skipped = send_batch(client, args.url, batch)
                total_indexed += indexed
                total_skipped += skipped
                elapsed = time.time() - start
                print(
                    f"  Batch {idx}/{len(batches)}: "
                    f"+{indexed} indexed, {skipped} skipped "
                    f"({total_indexed + total_skipped}/{len(documents)}) "
                    f"[{elapsed:.1f}s]"
                )
            except httpx.HTTPStatusError as e:
                print(f"  ERROR: {e.response.status_code} {e.response.text[:200]}",
                      file=sys.stderr)

    elapsed = time.time() - start
    print(f"\nDone: {total_indexed} indexed, {total_skipped} skipped in {elapsed:.1f}s")


if __name__ == "__main__":
    main()
