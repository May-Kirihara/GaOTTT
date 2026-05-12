"""Unit tests for the Phase L BM25 tokenizer."""

from __future__ import annotations

import pytest

from gaottt.index.tokenizer import char_ngrams, get_tokenizer, normalize


def test_normalize_lowercases_ascii():
    assert normalize("Eleventy Pipeline") == "eleventy pipeline"


def test_normalize_collapses_whitespace():
    assert normalize("foo   bar\n\tbaz") == "foo bar baz"


def test_normalize_nfkc_fullwidth_to_halfwidth():
    # NFKC maps fullwidth ASCII (U+FF21–FF5A) to halfwidth.
    assert normalize("ＥＬＥＶＥＮＴＹ") == "eleventy"


def test_char_ngrams_english_word_boundaries():
    tokens = char_ngrams("Eleventy", n=3)
    # Boundary markers distinguish word-start trigrams.
    assert "<el" in tokens
    assert "ty>" in tokens
    assert "ele" in tokens
    assert "<ty" not in tokens  # 'ty' is not a word-start in 'eleventy'


def test_char_ngrams_japanese_unbroken_run():
    tokens = char_ngrams("重力モデル", n=3)
    # Japanese without whitespace stays one word; trigrams span the run
    # with boundary markers.
    assert tokens == ["<重力", "重力モ", "力モデ", "モデル", "デル>"]


def test_char_ngrams_short_word_kept_whole():
    # When the bounded word length equals n, the whole token is kept.
    assert char_ngrams("a", n=3) == ["<a>"]
    assert char_ngrams("X", n=3) == ["<x>"]
    # When the bounded length exceeds n, normal sliding window applies:
    # "<ab>" (len 4) → 2 trigrams.
    assert char_ngrams("ab", n=3) == ["<ab", "ab>"]


def test_char_ngrams_multi_word_emits_all():
    tokens = char_ngrams("Eleventy Pipeline", n=3)
    # Both English words contribute trigrams.
    assert "<el" in tokens and "ty>" in tokens
    assert "<pi" in tokens and "ne>" in tokens
    # No cross-word trigram (whitespace splits boundaries).
    assert "y p" not in tokens


def test_get_tokenizer_trigram_default():
    tok = get_tokenizer("trigram")
    assert tok("Test") == char_ngrams("Test", n=3)


def test_get_tokenizer_unknown_raises():
    with pytest.raises(ValueError, match="unknown bm25_tokenizer"):
        get_tokenizer("nonsense")


def test_get_tokenizer_sudachi_import_error_when_missing():
    # If sudachipy is not installed (Stage 1 default), selecting it must
    # raise an explicit ImportError pointing to the optional extra.
    try:
        import sudachipy  # noqa: F401
    except ImportError:
        with pytest.raises(ImportError, match="bm25-sudachi"):
            get_tokenizer("sudachi")
    else:
        # sudachipy IS installed; should construct successfully.
        tok = get_tokenizer("sudachi")
        out = tok("テスト")
        assert isinstance(out, list)
