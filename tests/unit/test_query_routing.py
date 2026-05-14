"""Phase O Stage 3 — unit tests for the query-routing classifier.

Pure-function tests of ``services.query_routing.detect_aspect``:
- positive examples for each aspect (JP + EN surface forms)
- negative examples that must *not* route (free-form recall fallthrough)
- no pattern overlap on representative examples (deterministic routing)
- empty / whitespace queries return None
"""
from __future__ import annotations

from gaottt.services.query_routing import KNOWN_ASPECTS, detect_aspect, pattern_count


def test_pattern_count_nonzero():
    assert pattern_count() > 0


def test_empty_query_returns_none():
    assert detect_aspect("") is None
    assert detect_aspect("   ") is None


def test_routes_commitments_jp():
    assert detect_aspect("現在 active な commitment は?") == "commitments"
    assert detect_aspect("今 active なコミットメント") == "commitments"
    assert detect_aspect("持ってる commitment 一覧") == "commitments"
    assert detect_aspect("有効な誓約") == "commitments"


def test_routes_commitments_en():
    assert detect_aspect("what are my active commitments") == "commitments"
    assert detect_aspect("Active commitments?") == "commitments"


def test_routes_values_jp_and_en():
    assert detect_aspect("持っている value を教えて") == "values"
    assert detect_aspect("declared な価値観") == "values"
    assert detect_aspect("my values please") == "values"


def test_routes_intentions_jp_and_en():
    assert detect_aspect("持っている intention") == "intentions"
    assert detect_aspect("declared な意図") == "intentions"
    assert detect_aspect("my intentions") == "intentions"


def test_routes_tasks_doing():
    assert detect_aspect("今やってる task") == "tasks_doing"
    assert detect_aspect("active な task") == "tasks_doing"
    assert detect_aspect("ongoing tasks") == "tasks_doing"


def test_routes_tasks_completed():
    assert detect_aspect("完了した task") == "tasks_completed"
    assert detect_aspect("finished tasks 一覧") == "tasks_completed"


def test_routes_tasks_abandoned():
    assert detect_aspect("諦めた task") == "tasks_abandoned"
    assert detect_aspect("abandoned tasks") == "tasks_abandoned"


def test_routes_relationships():
    assert detect_aspect("my relationships") == "relationships"
    assert detect_aspect("どんな人と関係がある?") == "relationships"


def test_free_form_query_returns_none():
    """Free-form recall queries must not auto-route — preserves Phase A semantics."""
    assert detect_aspect("Articulation as Carrier の物理実装") is None
    assert detect_aspect("Phase I Stage 2 の query attraction") is None
    assert detect_aspect("FAISS の write-behind について") is None
    assert detect_aspect("奈良の道路") is None
    # Bare keywords without state verbs must not over-route
    assert detect_aspect("commitment") is None
    assert detect_aspect("value") is None
    assert detect_aspect("intention") is None


def test_all_returned_aspects_are_known():
    """detect_aspect must only return strings in KNOWN_ASPECTS (no typos)."""
    sample = [
        "現在 active な commitment",
        "持っている value",
        "持っている intention",
        "今やってる task",
        "完了した task",
        "諦めた task",
        "active な task",
        "my relationships",
    ]
    for q in sample:
        a = detect_aspect(q)
        assert a in KNOWN_ASPECTS, f"{q!r} routed to unknown aspect {a!r}"


def test_no_overlap_between_aspects():
    """Each representative query routes to exactly one aspect — no overlap."""
    queries = {
        "現在 active な commitment は?": "commitments",
        "持っている value": "values",
        "持っている intention": "intentions",
        "完了した task": "tasks_completed",
        "諦めた task": "tasks_abandoned",
        "my relationships": "relationships",
    }
    for q, expected in queries.items():
        got = detect_aspect(q)
        assert got == expected, f"{q!r} → {got!r}, expected {expected!r}"
