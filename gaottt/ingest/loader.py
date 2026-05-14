"""File ingestion: load documents from files and directories.

Supports Markdown (.md), plain text (.txt), CSV (.csv), and Claude Code
transcript JSONL (.jsonl).
"""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path


def ingest_path(
    path: str,
    source: str = "file",
    recursive: bool = False,
    pattern: str = "*.md,*.txt",
    chunk_size: int = 2000,
    include_tool_results: bool = False,
) -> list[dict]:
    """Load documents from a file or directory.

    Returns list of {"content": str, "metadata": dict} dicts.
    """
    p = Path(path)
    if not p.exists():
        return []

    if p.is_file():
        return _ingest_file(p, source, chunk_size, include_tool_results)

    # Directory: collect files by pattern
    patterns = [pat.strip() for pat in pattern.split(",")]
    files: list[Path] = []
    for pat in patterns:
        if recursive:
            files.extend(p.rglob(pat))
        else:
            files.extend(p.glob(pat))

    documents = []
    for f in sorted(files):
        documents.extend(_ingest_file(f, source, chunk_size, include_tool_results))
    return documents


def _ingest_file(
    path: Path,
    source: str,
    chunk_size: int,
    include_tool_results: bool = False,
) -> list[dict]:
    """Ingest a single file based on extension."""
    suffix = path.suffix.lower()
    if suffix == ".md":
        return _ingest_markdown(path, source, chunk_size)
    elif suffix == ".csv":
        return _ingest_csv(path, source, chunk_size)
    elif suffix == ".jsonl":
        return _ingest_claude_jsonl(path, source, chunk_size, include_tool_results)
    else:  # .txt and others
        return _ingest_plaintext(path, source, chunk_size)


# -----------------------------------------------------------------------
# Markdown
# -----------------------------------------------------------------------

def _ingest_markdown(path: Path, source: str, chunk_size: int) -> list[dict]:
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        return []

    # Extract title from # heading
    title = path.stem
    title_match = re.match(r"^#\s+(.+)", text)
    if title_match:
        title = title_match.group(1).strip()

    # Split on ## headings
    sections = re.split(r"(?=^##\s)", text, flags=re.MULTILINE)

    documents = []
    for section in sections:
        section = section.strip()
        if not section:
            continue
        # Skip title-only section (just the # heading)
        if section.startswith("# ") and "\n" not in section.strip():
            continue

        # Extract section heading
        heading = ""
        heading_match = re.match(r"^##\s+(.+)", section)
        if heading_match:
            heading = heading_match.group(1).strip()

        # Chunk if too long
        chunks = _chunk_text(section, chunk_size)
        for i, chunk in enumerate(chunks):
            meta = {
                "source": source,
                # Phase M Stage 1 — every chunk of the same file shares this
                # original_id so the self-force filter in the mass update
                # recognises them as "internal trade" and does not let them
                # inflate each other's mass.
                "original_id": str(path),
                "file_path": str(path),
                "file_name": path.name,
                "title": title,
            }
            if heading:
                meta["section"] = heading
            if len(chunks) > 1:
                meta["chunk_index"] = i
                meta["total_chunks"] = len(chunks)
            documents.append({"content": chunk, "metadata": meta})

    return documents


# -----------------------------------------------------------------------
# Plain text
# -----------------------------------------------------------------------

def _ingest_plaintext(path: Path, source: str, chunk_size: int) -> list[dict]:
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        return []

    chunks = _chunk_text(text, chunk_size)
    documents = []
    for i, chunk in enumerate(chunks):
        meta = {
            "source": source,
            "original_id": str(path),  # Phase M Stage 1 — see _ingest_markdown
            "file_path": str(path),
            "file_name": path.name,
        }
        if len(chunks) > 1:
            meta["chunk_index"] = i
            meta["total_chunks"] = len(chunks)
        documents.append({"content": chunk, "metadata": meta})

    return documents


# -----------------------------------------------------------------------
# CSV
# -----------------------------------------------------------------------

def _ingest_csv(path: Path, source: str, chunk_size: int) -> list[dict]:
    documents = []
    with open(path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            return []

        # Auto-detect content column
        content_col = None
        for candidate in ["content", "text", "body", "message"]:
            if candidate in reader.fieldnames:
                content_col = candidate
                break
        if content_col is None:
            content_col = reader.fieldnames[0]

        # Phase M Stage 1 — derive a per-row original_id so chunks of the
        # same CSV row group together; rows themselves stay independent.
        # Prefer a user-supplied "id" column, fall back to "<path>#<row>".
        id_col = "id" if "id" in reader.fieldnames else None

        for row_idx, row in enumerate(reader):
            text = row.get(content_col, "").strip()
            if not text:
                continue

            original_id = (
                row[id_col] if id_col and row.get(id_col) else f"{path}#{row_idx}"
            )
            meta = {
                "source": source,
                "original_id": original_id,
                "file_path": str(path),
                "file_name": path.name,
            }
            # Include other columns as metadata
            for col in reader.fieldnames:
                if col != content_col and row.get(col):
                    meta[col] = row[col]

            chunks = _chunk_text(text, chunk_size)
            for i, chunk in enumerate(chunks):
                doc_meta = {**meta}
                if len(chunks) > 1:
                    doc_meta["chunk_index"] = i
                    doc_meta["total_chunks"] = len(chunks)
                documents.append({"content": chunk, "metadata": doc_meta})

    return documents


# -----------------------------------------------------------------------
# Claude Code transcript JSONL
# -----------------------------------------------------------------------

# Sentinels for messages we never want to ingest as content.
_SKIP_TYPES = {
    "permission-mode",
    "file-history-snapshot",
    "last-prompt",
    "summary",  # condensed-history markers — usually duplicates of regular turns
}

# User-message content prefixes that mean "synthetic CLI injection", not
# real user prose. Match against the raw string content.
_LOCAL_COMMAND_PATTERNS = (
    "<local-command-caveat>",
    "<local-command-stdout>",
    "<local-command-stderr>",
    "<command-stdout>",
    "<command-stderr>",
)


def _extract_text_blocks(
    content,
    include_tool_results: bool,
) -> str:
    """Flatten Anthropic content (string OR list of blocks) into plain text.

    Returns empty string if nothing remains after filtering.
    """
    if content is None:
        return ""
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ""

    out: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        btype = block.get("type")
        if btype == "text":
            txt = (block.get("text") or "").strip()
            if txt:
                out.append(txt)
        elif btype == "tool_use":
            name = block.get("name") or "?"
            # Best-effort one-line summary of the most useful input field.
            inp = block.get("input") or {}
            hint = ""
            if isinstance(inp, dict):
                for key in ("command", "description", "query", "file_path",
                            "path", "url", "prompt", "subject"):
                    val = inp.get(key)
                    if isinstance(val, str) and val.strip():
                        hint = val.strip().splitlines()[0]
                        if len(hint) > 120:
                            hint = hint[:117] + "..."
                        break
            out.append(f"[tool:{name}]" + (f" {hint}" if hint else ""))
        elif btype == "tool_result" and include_tool_results:
            inner = block.get("content")
            if isinstance(inner, str):
                txt = inner.strip()
            elif isinstance(inner, list):
                txt = "\n".join(
                    (b.get("text") or "").strip()
                    for b in inner
                    if isinstance(b, dict) and b.get("type") == "text"
                ).strip()
            else:
                txt = ""
            if txt:
                out.append(f"[tool_result]\n{txt}")
        # thinking / image / other blocks are dropped silently
    return "\n\n".join(out).strip()


def _is_local_command_injection(text: str) -> bool:
    """True for CLI-injected user messages we should skip.

    Examples: `<local-command-caveat>...`, `<local-command-stdout>...`,
    `<command-name>/resume</command-name>...`.
    """
    s = text.lstrip()
    if not s:
        return True
    if any(s.startswith(p) for p in _LOCAL_COMMAND_PATTERNS):
        return True
    # `<command-name>` wrappers without surrounding user prose
    if s.startswith("<command-name>") and "</command-name>" in s:
        # If the only thing in the message is the command wrappers, skip.
        residue = re.sub(
            r"<(?:command-name|command-message|command-args)>.*?</(?:command-name|command-message|command-args)>",
            "",
            s,
            flags=re.DOTALL,
        ).strip()
        return not residue
    return False


def _ingest_claude_jsonl(
    path: Path,
    source: str,
    chunk_size: int,
    include_tool_results: bool,
) -> list[dict]:
    """Ingest a Claude Code transcript .jsonl file.

    Pairs each (user, assistant) exchange into one document. Synthetic /
    CLI-injected rows are dropped. ``original_id`` is ``"<sessionId>#<turn>"``
    so chunks of the same turn group as one logical unit under Phase M's
    self-force filter.
    """
    if not path.exists():
        return []

    # Pass 1: collect message rows in file order, indexed by uuid for parent
    # lookups (used to detect orphaned assistants).
    rows: list[dict] = []
    by_uuid: dict[str, dict] = {}
    with open(path, encoding="utf-8") as f:
        for raw in f:
            raw = raw.strip()
            if not raw:
                continue
            try:
                obj = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if not isinstance(obj, dict):
                continue
            if obj.get("type") in _SKIP_TYPES:
                continue
            if obj.get("type") not in ("user", "assistant"):
                continue
            if obj.get("isMeta") is True:
                continue
            rows.append(obj)
            uid = obj.get("uuid")
            if isinstance(uid, str):
                by_uuid[uid] = obj

    # Pass 2: group rows into "exchanges". An exchange = one real user
    # prompt + every assistant + tool_result message that follows until the
    # next real user prompt. This matches what a human reading the chat
    # would call "one Q&A" — Claude Code's transcript interleaves multiple
    # assistant turns with tool_result user turns, so pairing only the
    # first assistant produces orphaned tool-call fragments.
    documents: list[dict] = []
    session_id = path.stem  # fallback if no sessionId field

    cur_user_obj: dict | None = None
    cur_user_text: str = ""
    cur_asst_parts: list[str] = []
    cur_asst_obj: dict | None = None  # last assistant in the exchange
    turn_index = 0

    def _is_tool_result_only_user(inner: dict) -> bool:
        c = inner.get("content")
        return (
            isinstance(c, list)
            and len(c) > 0
            and all(
                isinstance(b, dict) and b.get("type") == "tool_result"
                for b in c
            )
        )

    def flush() -> None:
        nonlocal turn_index, cur_user_obj, cur_user_text
        nonlocal cur_asst_parts, cur_asst_obj

        user_text = cur_user_text
        asst_text = "\n\n".join(p for p in cur_asst_parts if p).strip()

        if not user_text and not asst_text:
            # Reset and bail.
            cur_user_obj = None
            cur_user_text = ""
            cur_asst_parts = []
            cur_asst_obj = None
            return

        parts: list[str] = []
        if user_text:
            parts.append(f"## User\n{user_text}")
        if asst_text:
            parts.append(f"## Assistant\n{asst_text}")
        body = "\n\n".join(parts)

        anchor = cur_asst_obj or cur_user_obj
        sid = (anchor.get("sessionId") if anchor else None) or session_id
        ts = (cur_user_obj.get("timestamp") if cur_user_obj else None) or (
            cur_asst_obj.get("timestamp") if cur_asst_obj else None
        )
        cwd = anchor.get("cwd") if anchor else None
        git_branch = anchor.get("gitBranch") if anchor else None
        version = anchor.get("version") if anchor else None
        is_sidechain = bool(
            (cur_asst_obj and cur_asst_obj.get("isSidechain"))
            or (cur_user_obj and cur_user_obj.get("isSidechain"))
        )
        model = None
        if cur_asst_obj:
            am = cur_asst_obj.get("message") or {}
            mdl = am.get("model")
            if isinstance(mdl, str) and mdl and mdl != "<synthetic>":
                model = mdl

        meta_base = {
            "source": source,
            "original_id": f"{sid}#{turn_index}",
            "file_path": str(path),
            "file_name": path.name,
            "session_id": sid,
            "turn_index": turn_index,
        }
        if ts:
            meta_base["timestamp"] = ts
        if cwd:
            meta_base["cwd"] = cwd
        if git_branch:
            meta_base["git_branch"] = git_branch
        if version:
            meta_base["cli_version"] = version
        if model:
            meta_base["model"] = model
        if is_sidechain:
            meta_base["is_sidechain"] = True

        chunks = _chunk_text(body, chunk_size)
        # When an exchange is split across multiple chunks, every chunk after
        # the first loses the `## User` / `## Assistant` headers — making
        # tool-heavy continuations look like naked tool-call fragments to
        # the embedder. Inject a short user-context prefix into chunks[1..]
        # so the exchange shape stays visible to retrieval. The first chunk
        # is left untouched (it already has the full headers).
        if len(chunks) > 1 and user_text:
            first_line = user_text.strip().splitlines()[0] if user_text.strip() else ""
            user_short = first_line[:100].strip()
            if len(first_line) > 100:
                user_short += "..."
            if user_short:
                for i in range(1, len(chunks)):
                    stripped = chunks[i].lstrip()
                    if stripped.startswith("## Assistant"):
                        # First continuation chunk often starts with the
                        # `## Assistant` header (paragraph boundary). Add a
                        # User-prev line above it so both headers are present.
                        chunks[i] = f"## User (prev): {user_short}\n\n{chunks[i]}"
                    else:
                        # Naked continuation (mid-assistant tail). Wrap with
                        # both pseudo-headers.
                        chunks[i] = (
                            f"## User (prev): {user_short}\n\n"
                            f"## Assistant (cont.)\n{chunks[i]}"
                        )
            # Edge case: when the User paragraph fit alone and the Assistant
            # paragraph was huge, chunks[0] is "## User\n<text>" with no
            # ## Assistant header. Append a forward-reference so the
            # invariant "every chunk has both headers" holds for chunks[0]
            # too.
            if "## Assistant" not in chunks[0]:
                chunks[0] = chunks[0] + "\n\n## Assistant (continues in next chunk)"

        for i, chunk in enumerate(chunks):
            doc_meta = {**meta_base}
            if len(chunks) > 1:
                doc_meta["chunk_index"] = i
                doc_meta["total_chunks"] = len(chunks)
            documents.append({"content": chunk, "metadata": doc_meta})
        turn_index += 1

        # Reset
        cur_user_obj = None
        cur_user_text = ""
        cur_asst_parts = []
        cur_asst_obj = None

    for obj in rows:
        rtype = obj.get("type")
        inner = obj.get("message") or {}
        role = inner.get("role")

        if rtype == "user" and role == "user":
            # tool_result-only user rows are part of the current exchange,
            # not a new prompt.
            if _is_tool_result_only_user(inner):
                if include_tool_results:
                    txt = _extract_text_blocks(
                        inner.get("content"), include_tool_results=True
                    )
                    if txt:
                        cur_asst_parts.append(txt)
                continue

            text = _extract_text_blocks(
                inner.get("content"), include_tool_results
            )
            if not text or _is_local_command_injection(text):
                continue

            # Real new prompt — flush the previous exchange first.
            if cur_user_obj is not None or cur_asst_parts:
                flush()
            cur_user_obj = obj
            cur_user_text = text

        elif rtype == "assistant" and role == "assistant":
            text = _extract_text_blocks(
                inner.get("content"), include_tool_results
            )
            model = inner.get("model")
            if model == "<synthetic>" or not text:
                continue
            cur_asst_parts.append(text)
            cur_asst_obj = obj

    # Trailing exchange (last user/assistant block).
    if cur_user_obj is not None or cur_asst_parts:
        flush()

    return documents


# -----------------------------------------------------------------------
# Chunking
# -----------------------------------------------------------------------

def _chunk_text(text: str, max_chars: int) -> list[str]:
    """Split text into chunks, preserving paragraph boundaries."""
    text = text.strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    # Try paragraph splitting
    paragraphs = re.split(r"\n\n+", text)
    if len(paragraphs) > 1:
        chunks = []
        current = ""
        for para in paragraphs:
            para = para.strip()
            if not para:
                continue
            if len(current) + len(para) + 2 <= max_chars:
                current = current + "\n\n" + para if current else para
            else:
                if current:
                    chunks.append(current)
                if len(para) > max_chars:
                    chunks.extend(_hard_split(para, max_chars))
                else:
                    current = para
        if current:
            chunks.append(current)
        return chunks

    return _hard_split(text, max_chars)


def _hard_split(text: str, max_chars: int) -> list[str]:
    chunks = []
    while len(text) > max_chars:
        cut = max_chars
        for sep in ["。", "\n", "．", ".", "！", "？"]:
            pos = text.rfind(sep, 0, max_chars)
            if pos > max_chars // 2:
                cut = pos + len(sep)
                break
        chunks.append(text[:cut].strip())
        text = text[cut:].strip()
    if text:
        chunks.append(text)
    return chunks
