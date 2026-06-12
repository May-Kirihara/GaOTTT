"""Observation Apparatus Round 2 — E1 conversational source damping + E2 dump-shape gate.

Plans-Observation-Apparatus-Round-2.md Stage E. Pure-function tests for
``_conversational_source_factor``, ``_dump_symbol_ratio``, and their
integration into ``_pick_lensing`` and ``ambient_recall``'s direct-slot
ranking. No engine / embedder required.
"""
from __future__ import annotations

from types import SimpleNamespace

from gaottt.config import GaOTTTConfig
from gaottt.core.types import MemoryItem, ScoreBreakdown
from gaottt.services.memory import (
    _conversational_source_factor,
    _dump_symbol_ratio,
    _pick_lensing,
)


def _cfg(**overrides):
    return GaOTTTConfig(**overrides)


def _item(
    node_id: str, raw_cos: float, virt_cos: float, *,
    source: str = "agent",
    content: str | None = None,
    final_score: float = 0.5,
) -> MemoryItem:
    return MemoryItem(
        id=node_id,
        content=content if content is not None else f"content-{node_id}",
        raw_score=virt_cos,
        final_score=final_score,
        source=source,
        score_breakdown=ScoreBreakdown(
            raw_cosine=raw_cos, virtual_cosine=virt_cos,
        ),
    )


def _engine(**overrides):
    return SimpleNamespace(config=GaOTTTConfig(**overrides))


# --- E1: _conversational_source_factor ------------------------------------------------


def test_source_factor_returns_1_when_off():
    cfg = _cfg(ambient_conversational_source_factor=1.0)
    assert _conversational_source_factor("openai", cfg) == 1.0
    assert _conversational_source_factor("agent", cfg) == 1.0


def test_source_factor_damps_matching_source():
    cfg = _cfg(
        ambient_conversational_source_factor=0.3,
        ambient_conversational_sources=("openai", "claude-web"),
    )
    assert _conversational_source_factor("openai", cfg) == 0.3
    assert _conversational_source_factor("claude-web", cfg) == 0.3
    assert _conversational_source_factor("agent", cfg) == 1.0


def test_source_factor_returns_1_when_factor_above_1():
    cfg = _cfg(ambient_conversational_source_factor=2.0)
    assert _conversational_source_factor("openai", cfg) == 1.0


# --- E1: direct-slot ranking via ambient_recall re-rank ------------------------------
# The direct-slot re-rank is tested by checking the order of items after
# the novelty + source-factor combined re-sort. We verify that with
# factor < 1.0, a conversational-source item with higher final_score can
# be overtaken by a non-conversational item.


def test_e1_direct_ranking_bitexact_when_off():
    """factor=1.0 (legacy OFF) preserves original final_score ordering."""
    off_cfg = _cfg(ambient_conversational_source_factor=1.0)
    cfg_items = [
        _item("a", 0.1, 0.9, source="openai", final_score=0.95),
        _item("b", 0.1, 0.8, source="agent", final_score=0.80),
    ]
    decayed = []
    for it in cfg_items:
        nv = 1.0
        src_f = _conversational_source_factor(it.source, off_cfg)
        decayed.append((it.final_score * nv * src_f, it))
    decayed.sort(key=lambda t: t[0], reverse=True)
    ids = [it.id for _, it in decayed]
    assert ids == ["a", "b"]


def test_e1_direct_ranking_reverses_with_factor():
    """factor=0.3 causes openai item (0.95) to fall below agent item (0.80)."""
    cfg = _cfg(
        ambient_conversational_source_factor=0.3,
        ambient_conversational_sources=("openai",),
    )
    cfg_items = [
        _item("a", 0.1, 0.9, source="openai", final_score=0.95),
        _item("b", 0.1, 0.8, source="agent", final_score=0.80),
    ]
    decayed = []
    for it in cfg_items:
        src_f = _conversational_source_factor(it.source, cfg)
        decayed.append((it.final_score * src_f, it))
    decayed.sort(key=lambda t: t[0], reverse=True)
    ids = [it.id for _, it in decayed]
    assert ids == ["b", "a"], f"agent should outrank damped openai: {ids}"


# --- E1: _pick_lensing integration ---------------------------------------------------


def test_e1_lensing_source_damping():
    """Lensing ranking includes source factor: openai item with large gap
    is outranked by agent item when factor=0.1."""
    engine = _engine(
        ambient_lensing_max_k=2,
        ambient_conversational_source_factor=0.1,
        ambient_conversational_sources=("openai",),
    )
    items = [
        _item("conv", 0.10, 0.90, source="openai"),
        _item("know", 0.30, 0.70, source="agent"),
    ]
    picks = _pick_lensing(engine, items, exclude=set())
    ids = [p[0].id for p in picks]
    assert ids[0] == "know", (
        f"agent lensing should rank above damped openai: {ids}"
    )


def test_e1_lensing_bitexact_when_off():
    engine = _engine(ambient_lensing_max_k=2)
    items = [
        _item("conv", 0.10, 0.90, source="openai"),
        _item("know", 0.30, 0.70, source="agent"),
    ]
    picks = _pick_lensing(engine, items, exclude=set())
    ids = [p[0].id for p in picks]
    assert ids == ["conv", "know"]


# --- E2: _dump_symbol_ratio ----------------------------------------------------------


def test_dump_ratio_japanese_text_is_low():
    text = "これは通常の日本語の文章です。内容は技術的な決定事項について述べています。"
    assert _dump_symbol_ratio(text) < 0.3


def test_dump_ratio_english_text_is_low():
    text = (
        "This is a normal English sentence about technical decisions "
        "and project architecture."
    )
    assert _dump_symbol_ratio(text) < 0.3


def test_dump_ratio_state_dict_is_high():
    text = (
        "residual_layer.0.layer.8.fn.rel_pos_bias.weight "
        "residual_layer.0.layer.9.fn.rel_pos_bias.weight "
        "residual_layer.1.layer.0.fn.rel_pos_bias.weight"
    )
    assert _dump_symbol_ratio(text) > 0.15


def test_dump_ratio_empty_is_zero():
    assert _dump_symbol_ratio("") == 0.0


def test_dump_ratio_code_dump_is_high():
    """Raw code / Go struct dump — the production case from dogfooding."""
    text = (
        'switch msg.Command { case "start": '
        'pythonPath := "/mnt/holyland/miniconda3/bin/python" '
        'scriptPath := "/mnt/holyland/LLM/RWKV/train.py" '
        'executePythonScript(userConn, pythonPath, scriptPath) }'
    )
    assert _dump_symbol_ratio(text) > 0.45


def test_dump_ratio_respects_head_parameter():
    long_text = "あ" * 300 + "residual_layer.0.layer.8.fn.rel_pos_bias.weight " * 20
    ratio_full = _dump_symbol_ratio(long_text, head=9999)
    ratio_head = _dump_symbol_ratio(long_text, head=300)
    assert ratio_head < 0.1
    assert ratio_full > 0.3


# --- E2: ambient_recall integration (items filter) -----------------------------------
# We test the dump-shape filter by constructing items with dump content
# and verifying that the items list is filtered correctly through the
# service logic (without full engine, by calling the filter inline).


def test_e2_items_filter_removes_dump():
    """Items with high symbol ratio are removed when gate is active."""
    cfg = _cfg(ambient_dump_symbol_ratio=0.45)
    dump_content = "residual_layer.1.residual_layer.0.layer.10.norm.weight " * 8
    items = [
        _item("good", 0.1, 0.9, source="agent", content="通常の文章内容です"),
        _item("dump", 0.1, 0.8, source="openai", content=dump_content),
        _item("ok", 0.1, 0.7, source="agent", content="別の正常な内容"),
    ]
    ratio_threshold = cfg.ambient_dump_symbol_ratio
    filtered = [
        it for it in items
        if _dump_symbol_ratio(it.content) <= ratio_threshold
    ]
    ids = [it.id for it in filtered]
    assert "dump" not in ids
    assert "good" in ids
    assert "ok" in ids


def test_e2_items_filter_off_is_noop():
    """ambient_dump_symbol_ratio >= 1.0 (legacy OFF) disables the gate entirely."""
    cfg = _cfg(ambient_dump_symbol_ratio=1.0)
    items = [
        _item("good", 0.1, 0.9, source="agent", content="通常の文章"),
        _item("dump", 0.1, 0.8, source="openai",
              content="residual_layer.0.layer.8.fn.weight " * 10),
    ]
    # Mirror the service-side gate condition: < 1.0 activates the filter.
    if cfg.ambient_dump_symbol_ratio < 1.0:
        items = [
            it for it in items
            if _dump_symbol_ratio(it.content) <= cfg.ambient_dump_symbol_ratio
        ]
    ids = [it.id for it in items]
    assert ids == ["good", "dump"]
