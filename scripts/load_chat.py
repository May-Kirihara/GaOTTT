"""Load Claude Code (and compatible) chat-history JSONL into GaOTTT.

Each session file is parsed turn-by-turn: a user prompt and the immediate
assistant reply are paired into one document. CLI-injected rows
(``<local-command-...>``, ``<command-name>``-only resume markers,
``isMeta:true`` snapshots, ``permission-mode``, ``file-history-snapshot``,
``last-prompt``) are dropped. ``tool_use`` blocks are summarised as
``[tool:<name>] <hint>``; raw tool stdout is skipped by default and can be
included with ``--include-tool-results``.

Source layout matches ``~/.claude/projects/<project>/<sessionId>.jsonl``.
A directory of session files can be ingested in one pass.

Usage::

    # one session
    python scripts/load_chat.py input/projects/.../<sessionId>.jsonl

    # whole project (all sessions, recursive)
    python scripts/load_chat.py input/projects/-mnt-holyland-devs-maysweb/ -r

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
    parser.add_argument("path", help="JSONL file or directory of JSONLs")
    parser.add_argument("--url", default=DEFAULT_URL, help="GaOTTT server URL")
    parser.add_argument("--pattern", default="*.jsonl",
                        help="Glob pattern(s), comma-separated (default: '*.jsonl')")
    parser.add_argument("--recursive", "-r", action="store_true",
                        help="Recursively scan subdirectories")
    parser.add_argument("--source", default="claude-code",
                        help="Source label for metadata (default: 'claude-code')")
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

    # Summary by session
    sessions: dict[str, int] = {}
    sidechain_turns = 0
    for d in documents:
        meta = d.get("metadata", {})
        sid = meta.get("session_id", "?")
        sessions[sid] = sessions.get(sid, 0) + 1
        if meta.get("is_sidechain"):
            sidechain_turns += 1

    print(f"  Sessions: {len(sessions)}")
    print(f"  Documents (turn chunks): {len(documents)}")
    if sidechain_turns:
        print(f"  Sidechain turns: {sidechain_turns}")

    for sid, count in sorted(sessions.items()):
        print(f"    {sid}: {count} chunks")

    if args.dry_run:
        print("\n[DRY RUN] No documents sent.")
        for d in documents[:3]:
            meta = d.get("metadata", {})
            preview = d["content"][:140].replace("\n", " ")
            print(f"  [{meta.get('session_id', '?')}#{meta.get('turn_index', '?')}] {preview}...")
        if len(documents) > 3:
            print(f"  ... and {len(documents) - 3} more")
        return

    try:
        httpx.get(f"{args.url}/docs", timeout=5.0)
    except httpx.ConnectError:
        print(f"\nERROR: Cannot connect to {args.url}. Is the server running?",
              file=sys.stderr)
        sys.exit(1)

    total_indexed = 0
    total_skipped = 0
    start = time.time()

    print(f"\nSending to {args.url}...")
    with httpx.Client() as client:
        for i in range(0, len(documents), args.batch_size):
            batch = documents[i: i + args.batch_size]
            try:
                indexed, skipped = send_batch(client, args.url, batch)
                total_indexed += indexed
                total_skipped += skipped
                elapsed = time.time() - start
                print(
                    f"  Batch {i // args.batch_size + 1}: "
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
