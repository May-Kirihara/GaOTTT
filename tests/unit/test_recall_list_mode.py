"""Phase O Stage 4 — unit tests for recall list-mode content truncation.

Tests the truncation rule directly (Pydantic + service helper) without going
through the engine:
- mode='list' truncates content to config.list_mode_excerpt_chars
- newlines and CR are collapsed to spaces so the excerpt fits one line
- mode='detail' (default) keeps content untouched
"""
from __future__ import annotations

from types import SimpleNamespace

from gaottt.services.memory import _to_memory_item


class _FakeEngine:
    """Minimal duck-typed engine — only the surface ``_to_memory_item`` needs."""

    class _Cache:
        def get_displacement_norm(self, _id: str) -> float:
            return 0.0

    def __init__(self):
        self.cache = self._Cache()

    def get_displacement_norm(self, _id: str) -> float:
        return 0.0


def _raw_result(content: str, node_id: str = "abc12345"):
    return SimpleNamespace(
        id=node_id,
        content=content,
        metadata={"source": "agent", "tags": ["t1"]},
        raw_score=0.5,
        final_score=0.6,
        score_breakdown=None,
    )


def test_detail_mode_keeps_content_untouched():
    eng = _FakeEngine()
    raw = _raw_result("x" * 500)
    item = _to_memory_item(eng, raw)  # excerpt_chars=None
    assert item.content == "x" * 500


def test_list_mode_truncates_to_excerpt_chars():
    eng = _FakeEngine()
    raw = _raw_result("x" * 500)
    item = _to_memory_item(eng, raw, excerpt_chars=80)
    assert len(item.content) == 80
    assert item.content == "x" * 80


def test_list_mode_collapses_newlines_to_spaces():
    """One-line per result is the whole point — embedded newlines would break it."""
    eng = _FakeEngine()
    raw = _raw_result("line1\nline2\r\nline3\nline4")
    item = _to_memory_item(eng, raw, excerpt_chars=80)
    assert "\n" not in item.content
    assert "\r" not in item.content
    assert "line1 line2  line3 line4" == item.content


def test_list_mode_content_shorter_than_limit_left_alone():
    eng = _FakeEngine()
    raw = _raw_result("short")
    item = _to_memory_item(eng, raw, excerpt_chars=80)
    assert item.content == "short"


def test_list_mode_empty_content_safe():
    eng = _FakeEngine()
    raw = _raw_result("")
    item = _to_memory_item(eng, raw, excerpt_chars=80)
    assert item.content == ""
