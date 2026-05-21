"""Query segmentation — split a compound prompt into clause-level segments.

Multi-Source Query (docs/wiki/Plans-Query-Mass-Distribution.md) treats a
prompt not as one pooled centroid but as several point masses. This module
does the splitting: a deterministic, no-LLM, zero-dependency regex split on
Japanese / ASCII sentence-and-clause punctuation.

Sudachi is deliberately *not* used here — it is a morphological tokenizer,
not a sentence segmenter, and ``bm25-sudachi`` is an optional extra; the
default install must not lose segmentation. See decision D2 in the plan.
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from gaottt.config import GaOTTTConfig

# Sentence terminators + clause separators, JA and ASCII. Bare ASCII "." is
# deliberately excluded — it collides with file extensions, decimals and
# abbreviations; English compound prompts still split on "," / ";" / newlines.
_SPLIT_RE = re.compile(r"[。．！？!?；;、，,\n]+")


def segment_query(text: str, config: "GaOTTTConfig") -> list[str]:
    """Split ``text`` into clause-level segments.

    Returns a list of one or more segments. A length-1 result means the
    prompt did not split (or splitting is effectively disabled) — the caller
    treats that as the single-source / legacy path.

    Fragments shorter than ``config.multi_source_min_segment_chars`` are
    merged into a neighbour so a stray "as an SPA" does not become a
    degenerate point mass. The result is capped at
    ``config.multi_source_max_segments``, keeping the longest segments
    (longest ≈ most lexically substantive).
    """
    stripped = text.strip()
    if not stripped or config.multi_source_max_segments < 2:
        return [text]

    parts = [s.strip() for s in _SPLIT_RE.split(stripped)]
    parts = [s for s in parts if s]
    if len(parts) <= 1:
        return [stripped]

    # Merge short fragments into the preceding segment.
    min_chars = config.multi_source_min_segment_chars
    merged: list[str] = []
    for part in parts:
        if merged and len(part) < min_chars:
            merged[-1] = f"{merged[-1]} {part}"
        else:
            merged.append(part)
    # If the first segment is itself too short, fold it forward.
    while len(merged) > 1 and len(merged[0]) < min_chars:
        merged[1] = f"{merged[0]} {merged[1]}"
        merged = merged[1:]

    if len(merged) <= 1:
        return [stripped]

    # Cap N — keep the longest segments (most lexically substantive).
    cap = config.multi_source_max_segments
    if len(merged) > cap:
        merged = sorted(merged, key=len, reverse=True)[:cap]
    return merged
