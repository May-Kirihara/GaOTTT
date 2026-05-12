"""Unit tests for Phase L BM25Index."""

from __future__ import annotations

from gaottt.index.bm25_index import BM25Index


def test_empty_index_returns_empty():
    idx = BM25Index()
    assert idx.size == 0
    assert idx.search("anything", top_k=5) == []


def test_add_increments_size():
    idx = BM25Index()
    idx.add(["a", "b", "c"], ["alpha doc", "beta doc", "gamma doc"])
    assert idx.size == 3


def test_search_returns_relevant_doc_first_english():
    idx = BM25Index()
    idx.add(
        ["doc_eleventy", "doc_sicily", "doc_gravity"],
        [
            ".eleventy.js Pipeline configuration responsibility",
            "Sicily naval landing operation history",
            "Gravity model design philosophy",
        ],
    )
    results = idx.search("Eleventy Pipeline", top_k=3)
    assert results
    top_id, top_score = results[0]
    assert top_id == "doc_eleventy"
    assert top_score > 0


def test_search_returns_relevant_doc_first_japanese():
    idx = BM25Index()
    idx.add(
        ["doc_gravity", "doc_sicily", "doc_unrelated"],
        [
            "重力モデルの設計思想と Phase 系譜",
            "シチリア島上陸作戦の戦史",
            "Eleventy パイプライン設定",
        ],
    )
    results = idx.search("重力モデルの設計思想", top_k=3)
    assert results
    assert results[0][0] == "doc_gravity"


def test_search_mixed_language_query_finds_either():
    idx = BM25Index()
    idx.add(
        ["doc_a", "doc_b"],
        [
            "FAISS index 設計 with virtual write-behind",
            "Sicily 上陸",
        ],
    )
    en = idx.search("FAISS write-behind", top_k=2)
    ja = idx.search("FAISS 設計", top_k=2)
    assert en and en[0][0] == "doc_a"
    assert ja and ja[0][0] == "doc_a"


def test_dedup_skips_repeated_id():
    idx = BM25Index()
    idx.add(["x"], ["first text"])
    idx.add(["x"], ["second text"])  # same id, ignored
    assert idx.size == 1
    results = idx.search("second", top_k=1)
    # First text won, so "second" should not match.
    assert results == []


def test_remove_excludes_from_search_immediately():
    idx = BM25Index()
    idx.add(["a", "b"], ["alpha eleventy", "beta eleventy"])
    assert idx.size == 2
    idx.remove(["a"])
    assert idx.size == 1
    results = idx.search("eleventy", top_k=5)
    ids = [r[0] for r in results]
    assert "a" not in ids
    assert "b" in ids


def test_remove_unknown_id_is_noop():
    idx = BM25Index()
    idx.add(["a"], ["text"])
    idx.remove(["nonexistent"])
    assert idx.size == 1


def test_rebuild_drops_removed_from_postings():
    idx = BM25Index()
    idx.add(["a", "b", "c"], ["x y z", "x y", "x"])
    idx.remove(["a", "b"])
    assert idx.size == 1
    # Before rebuild, _inverted still references removed postings;
    # active df for 'x' should be 1 (only 'c' is active).
    results = idx.search("x", top_k=5)
    assert len(results) == 1
    assert results[0][0] == "c"
    idx.rebuild()
    assert idx.size == 1
    # After rebuild, internal arrays drop the removed entries.
    assert "a" not in idx._id_to_idx
    assert "b" not in idx._id_to_idx
    # 'c' still findable.
    results = idx.search("x", top_k=5)
    assert results and results[0][0] == "c"


def test_idf_favors_rare_terms():
    idx = BM25Index()
    # 'common' appears in all 3 docs; 'rare' appears only in doc_rare.
    idx.add(
        ["doc1", "doc2", "doc_rare"],
        [
            "common term filler text",
            "common term other filler",
            "common term rare unique signal",
        ],
    )
    # Query mentioning both: rare contributes higher idf, so doc_rare wins.
    results = idx.search("common rare", top_k=3)
    assert results[0][0] == "doc_rare"


def test_top_k_truncates():
    idx = BM25Index()
    idx.add(
        [f"doc{i}" for i in range(5)],
        ["alpha"] * 5,
    )
    results = idx.search("alpha", top_k=2)
    assert len(results) == 2


def test_empty_query_returns_empty():
    idx = BM25Index()
    idx.add(["a"], ["non-empty doc"])
    assert idx.search("", top_k=5) == []


def test_top_k_zero_returns_empty():
    idx = BM25Index()
    idx.add(["a"], ["x"])
    assert idx.search("x", top_k=0) == []


def test_scores_are_descending():
    idx = BM25Index()
    idx.add(
        ["a", "b", "c"],
        ["eleventy pipeline eleventy", "eleventy pipeline", "pipeline only"],
    )
    results = idx.search("eleventy", top_k=3)
    scores = [s for _, s in results]
    assert scores == sorted(scores, reverse=True)
