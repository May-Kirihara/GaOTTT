"""Phase O Stage 2 — unit tests for TrainingDelta model + formatter."""
from __future__ import annotations

from gaottt.core.types import (
    RecallResponse,
    TrainingDelta,
)
from gaottt.services.formatters import (
    _format_training_delta,
    format_recall,
)


def test_training_delta_default_is_empty():
    td = TrainingDelta()
    assert td.displacement_changes == {}
    assert td.mass_changes == {}
    assert td.wave_reached_count == 0
    assert td.wave_max_depth == 0
    assert td.persona_hop_reached == 0
    assert td.supernova_triggered is False
    assert td.cache_hit is False
    assert td.topk_only is True


def test_training_delta_serializes_round_trip():
    td = TrainingDelta(
        displacement_changes={"abc": 0.012, "def": -0.005},
        mass_changes={"abc": 0.003, "def": 0.0},
        wave_reached_count=42,
        wave_max_depth=2,
        persona_hop_reached=5,
        supernova_triggered=False,
        cache_hit=False,
        topk_only=True,
    )
    d = td.model_dump()
    td2 = TrainingDelta.model_validate(d)
    assert td2.displacement_changes == {"abc": 0.012, "def": -0.005}
    assert td2.wave_reached_count == 42
    assert td2.persona_hop_reached == 5


def test_format_training_delta_none_returns_empty_string():
    assert _format_training_delta(None) == ""


def test_format_training_delta_cache_hit_is_explicit():
    td = TrainingDelta(cache_hit=True)
    out = _format_training_delta(td)
    assert "訓練差分" in out
    assert "cache hit" in out


def test_format_training_delta_renders_top_movers():
    td = TrainingDelta(
        displacement_changes={
            "node-a-12345678abc": 0.05,
            "node-b-22222222def": -0.02,
            "node-c-33333333aaa": 0.0001,  # ranks below top-3 cap (only 3 entries; all shown)
        },
        mass_changes={
            "node-a-12345678abc": 0.015,
            "node-b-22222222def": -0.001,
        },
        wave_reached_count=20,
        wave_max_depth=2,
        persona_hop_reached=3,
    )
    out = _format_training_delta(td)
    assert "wave_reached=20" in out
    assert "depth=2" in out
    assert "persona_hop=3" in out
    assert "Δmass top" in out
    assert "Δ|disp| top" in out
    # signed format
    assert "+0.0500" in out  # disp top
    assert "-0.0200" in out
    assert "+0.0150" in out  # mass top
    # coverage label
    assert "top-k only" in out


def test_format_training_delta_full_coverage_label():
    td = TrainingDelta(wave_reached_count=5, topk_only=False)
    out = _format_training_delta(td)
    assert "full reached set" in out


def test_format_recall_appends_training_delta_trailer():
    """recall formatter ends with the ## 訓練差分 trailer when present."""
    from gaottt.core.types import MemoryItem
    resp = RecallResponse(
        items=[MemoryItem(
            id="abc12345", content="hello", raw_score=0.5, final_score=0.5,
            source="user", tags=[],
        )],
        count=1,
        training_delta=TrainingDelta(
            displacement_changes={"abc12345": 0.01},
            mass_changes={"abc12345": 0.002},
            wave_reached_count=3, wave_max_depth=1,
        ),
    )
    out = format_recall(resp)
    assert "## 訓練差分" in out
    assert "wave_reached=3" in out


def test_format_recall_no_trailer_when_delta_none():
    from gaottt.core.types import MemoryItem
    resp = RecallResponse(
        items=[MemoryItem(
            id="x", content="y", raw_score=0.0, final_score=0.0,
            source="user", tags=[],
        )],
        count=1,
        training_delta=None,
    )
    out = format_recall(resp)
    assert "## 訓練差分" not in out


def test_topk_only_signal_distinguishes_debug_mode():
    """topk_only=False is debug coverage; default True is context-economical."""
    td_default = TrainingDelta()
    td_debug = TrainingDelta(topk_only=False, wave_reached_count=100)
    assert td_default.topk_only is True
    assert td_debug.topk_only is False
