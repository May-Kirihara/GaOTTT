"""Phase O Stage 3 — query routing classifier.

Detect whether a free-form recall/explore query is *actually* asking about a
structured persona / task aspect that ``reflect`` answers more precisely. If
so, services/memory.py runs the matching ``reflect`` aspect in parallel and
attaches its summary to the response (``routing_hint``).

Rule shape: **query-syntax pattern → aspect name**. No source-class branching
— this stays compatible with Phase M's "source 分岐ゼロの単一規則" because
the classifier reads the *caller's surface form*, not the physics rule.

Patterns are intentionally narrow: false positives waste a reflect call but
don't break recall, false negatives just fall back to the legacy recall-only
path. Add patterns as production usage reveals genuine high-frequency
phrasings — do not over-fit to one-off queries.
"""
from __future__ import annotations

import re

# Aspect names must match the strings ``reflect`` dispatches on
# (gaottt/services/reflection.py + gaottt/server/mcp_server.py).
KNOWN_ASPECTS: tuple[str, ...] = (
    "tasks_todo",
    "tasks_doing",
    "tasks_completed",
    "tasks_abandoned",
    "commitments",
    "values",
    "intentions",
    "relationships",
)


# (compiled_regex, aspect) pairs, evaluated in order. First match wins.
#
# Pattern strategy:
# - Each aspect has both a JP and an EN matcher so callers in either language
#   trip the route. Regex is case-insensitive (re.IGNORECASE on compile).
# - Patterns require *both* a verb-of-state ("現在", "active", "持って", "今")
#   and the target-noun ("commitment", "value", ...) — bare keyword matches
#   would over-route legitimate semantic recalls.
_PATTERN_DEFS: list[tuple[str, str]] = [
    # Commitments — declared promises with deadlines.
    (r"(現在|今|active|現役|有効).{0,12}(commitment|約束|誓約|コミット)", "commitments"),
    (r"(持(って|つ)).{0,6}(commitment|約束|誓約)", "commitments"),
    (r"active\s+commitments?", "commitments"),
    # Values — declared bedrock.
    (r"(持(って|つ)|宣言|declared).{0,8}(value|価値観)", "values"),
    (r"(my|our)\s+values?", "values"),
    # Intentions — declared long-term direction.
    (r"(持(って|つ)|宣言|declared).{0,8}(intention|意図|意向)", "intentions"),
    (r"(my|our)\s+intentions?", "intentions"),
    # Tasks in progress — engaged within the last hour.
    (r"(今|現在|right\s*now).{0,8}(やって|進行中|working\s*on|in\s*progress)", "tasks_doing"),
    (r"(active|ongoing).{0,8}(task|作業)", "tasks_doing"),
    # Tasks completed. Word boundaries on English keywords so "abandoned" does
    # not match via the substring "done".
    (r"(完了|終わった|\b(?:finished|completed|done)\b).{0,8}(task|作業|タスク)", "tasks_completed"),
    # Tasks abandoned.
    (r"(諦め|中断|\b(?:abandoned|dropped)\b).{0,8}(task|作業|タスク)", "tasks_abandoned"),
    # Tasks to-do — surface form distinct from "doing".
    (r"(active|残ってる|todo|未完了|残作業).{0,8}(task|作業|タスク)", "tasks_todo"),
    # Relationships.
    (r"(誰|どんな人|who).{0,8}(関係|relationship)", "relationships"),
    (r"(my|our)\s+relationships?", "relationships"),
]


_COMPILED: list[tuple[re.Pattern[str], str]] = [
    (re.compile(pat, re.IGNORECASE), aspect) for pat, aspect in _PATTERN_DEFS
]


def detect_aspect(query: str) -> str | None:
    """Return the matched ``reflect`` aspect for ``query`` or ``None``.

    The first matching pattern wins; pattern order encodes precedence when
    surface forms overlap (currently no overlaps — see ``tests/unit/test_query_routing``).
    """
    if not query:
        return None
    for pat, aspect in _COMPILED:
        if pat.search(query):
            return aspect
    return None


def pattern_count() -> int:
    """For tests / debugging — how many patterns are wired up."""
    return len(_COMPILED)
