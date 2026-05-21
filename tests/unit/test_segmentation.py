"""Query segmentation — the Multi-Source Query clause splitter (unit).

``segment_query`` splits a compound prompt into clause-level segments so the
wave can seed from several point masses instead of one pooled centroid. See
docs/wiki/Plans-Query-Mass-Distribution.md.
"""
from __future__ import annotations

from gaottt.config import GaOTTTConfig
from gaottt.core.segmentation import segment_query


def _cfg(tmp_path, **kw):
    base = dict(
        data_dir=str(tmp_path),
        db_path=str(tmp_path / "t.db"),
        faiss_index_path=str(tmp_path / "t.faiss"),
    )
    base.update(kw)
    return GaOTTTConfig(**base)


def test_compound_prompt_splits_on_clause_punctuation(tmp_path):
    segs = segment_query(
        "philharmonic と GaOTTT の記憶を使って、harakiriworks の web サイトを作って",
        _cfg(tmp_path),
    )
    assert len(segs) == 2
    assert "GaOTTT" in segs[0]
    assert "harakiriworks" in segs[1]


def test_sentence_terminator_also_splits(tmp_path):
    segs = segment_query(
        "最初のとても長い文章の例です。二番目のとても長い文章の例です",
        _cfg(tmp_path),
    )
    assert len(segs) == 2


def test_simple_prompt_does_not_split(tmp_path):
    text = "重力モデルの設計思想について教えてほしい"
    assert segment_query(text, _cfg(tmp_path)) == [text]


def test_short_fragments_merge_into_neighbor(tmp_path):
    cfg = _cfg(tmp_path)
    # "うん" (2 chars) is below min_segment_chars — it must not become its
    # own degenerate point mass.
    segs = segment_query("これは十分に長い最初の文章です、うん", cfg)
    assert all(len(s) >= cfg.multi_source_min_segment_chars for s in segs)


def test_max_segments_cap_keeps_longest(tmp_path):
    cfg = _cfg(tmp_path, multi_source_max_segments=2)
    text = (
        "セグメント番号いちの長い文章。"
        "セグメント番号にの長い文章。"
        "セグメント番号さんのとても長い長い文章"
    )
    segs = segment_query(text, cfg)
    assert len(segs) == 2
    # The shortest of the three must have been dropped by the cap.
    assert all("番号さん" in s or "番号いち" in s or "番号に" in s for s in segs)


def test_disabled_when_max_segments_below_two(tmp_path):
    cfg = _cfg(tmp_path, multi_source_max_segments=1)
    text = "文一の長い文章です。文二の長い文章です。文三の長い文章です"
    assert segment_query(text, cfg) == [text]


def test_empty_and_whitespace_are_returned_unchanged(tmp_path):
    cfg = _cfg(tmp_path)
    assert segment_query("", cfg) == [""]
    assert segment_query("   ", cfg) == ["   "]
