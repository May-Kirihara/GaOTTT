"""Tokenizer for BM25 — Phase L Stage 1.

Char n-gram default ("trigram") is robust for mixed Japanese/English corpus
without external dependencies. Sudachi is wired as a plugin: lazy-imported
on demand, requires installing the ``bm25-sudachi`` optional extra.

Tokenizers return ``list[str]`` of token strings, used as the unit of BM25
term frequency / document frequency.
"""

from __future__ import annotations

import unicodedata
from typing import Callable

Tokenizer = Callable[[str], list[str]]


def normalize(text: str) -> str:
    """NFKC normalize, lowercase, collapse whitespace runs."""
    text = unicodedata.normalize("NFKC", text)
    text = text.lower()
    return " ".join(text.split())


def char_ngrams(text: str, n: int = 3) -> list[str]:
    """Extract overlapping char n-grams per whitespace-separated word, with
    word-boundary markers ``<`` / ``>`` so word-start trigrams are
    distinguishable from word-mid trigrams.

    Example (n=3): ``"Eleventy Pipeline"`` →
        ``["<el", "ele", "lev", "eve", "ven", "ent", "nty", "ty>",
           "<pi", "pip", "ipe", "pel", "eli", "lin", "ine", "ne>"]``

    Japanese runs without whitespace stay as one word so trigrams span the
    run: ``"重力モデル"`` → ``["<重力", "重力モ", "力モデ", "モデル", "デル>"]``.
    """
    text = normalize(text)
    tokens: list[str] = []
    for word in text.split():
        bounded = f"<{word}>"
        if len(bounded) <= n:
            tokens.append(bounded)
            continue
        for i in range(len(bounded) - n + 1):
            tokens.append(bounded[i : i + n])
    return tokens


def _sudachi_tokenizer() -> Tokenizer:
    """Build a Sudachi-backed tokenizer. Lazy-imports sudachipy so the import
    cost is only paid when explicitly selected.
    """
    try:
        from sudachipy import dictionary, tokenizer
    except ImportError as exc:
        raise ImportError(
            "bm25_tokenizer='sudachi' requires the sudachipy package. "
            "Install with: uv pip install -e '.[bm25-sudachi]'"
        ) from exc

    sudachi = dictionary.Dictionary().create()
    mode = tokenizer.Tokenizer.SplitMode.C

    def tokenize(text: str) -> list[str]:
        return [m.surface() for m in sudachi.tokenize(normalize(text), mode)]

    return tokenize


def get_tokenizer(name: str = "trigram") -> Tokenizer:
    """Resolve a tokenizer name to a callable.

    Supported:
        - ``"trigram"`` (default): char 3-gram with word-boundary markers
        - ``"sudachi"``: Sudachi C-mode morphological tokenizer (optional extra)
    """
    if name == "trigram":
        return lambda text: char_ngrams(text, n=3)
    if name == "sudachi":
        return _sudachi_tokenizer()
    raise ValueError(f"unknown bm25_tokenizer: {name!r}")
