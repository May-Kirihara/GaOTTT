"""BM25 in-memory index — Phase L Stage 1.

Numpy-free, dict-of-postings BM25 with the same ``search`` interface as
:class:`gaottt.index.faiss_index.FaissIndex`. Char 3-gram tokenizer by
default for mixed-language corpus (see :mod:`gaottt.index.tokenizer`).

Disk persistence is intentionally absent in Stage 1 (decision D2 in
Plans-Phase-L-Hybrid-Retrieval.md): the engine rebuilds the index from
SQLite content at startup. Multi-process visibility is the same as raw
FAISS — process A's add is invisible to process B until B restarts.

Scoring formula (Robertson-Sparck-Jones with the +1 idf smoothing):

    score(q, d) = Σ over t in q∩d:
        idf(t) * tf(t,d) * (k1+1) / (tf(t,d) + k1*(1 - b + b*|d|/avgdl))

    idf(t) = log((N - df(t) + 0.5) / (df(t) + 0.5) + 1)

with N = number of active (non-removed) documents, df(t) = number of
active documents containing term t, |d| = active document length in tokens,
avgdl = average active document length.
"""

from __future__ import annotations

import math
from collections import Counter

from gaottt.index.tokenizer import Tokenizer, get_tokenizer


class BM25Index:
    """In-memory BM25 index with FAISS-like ``search`` shape.

    Removed documents are kept in internal arrays but excluded from
    statistics and search results until :meth:`rebuild` drops them.
    """

    def __init__(
        self,
        k1: float = 1.5,
        b: float = 0.75,
        tokenizer: str | Tokenizer = "trigram",
    ) -> None:
        self.k1 = k1
        self.b = b
        self._tokenize: Tokenizer = (
            get_tokenizer(tokenizer) if isinstance(tokenizer, str) else tokenizer
        )

        self._doc_ids: list[str] = []
        self._doc_lens: list[int] = []
        self._id_to_idx: dict[str, int] = {}
        self._inverted: dict[str, list[tuple[int, int]]] = {}  # term → [(doc_idx, tf)]
        self._removed: set[str] = set()
        self._active_count = 0
        self._active_total_dl = 0

    @property
    def size(self) -> int:
        """Number of active (non-removed) documents."""
        return self._active_count

    @property
    def _avgdl(self) -> float:
        if self._active_count == 0:
            return 1.0
        return self._active_total_dl / self._active_count

    def add(self, ids: list[str], texts: list[str]) -> None:
        """Append documents. Ids must be unique within the index (duplicates
        are skipped silently — matching the engine's content-hash dedup)."""
        if len(ids) != len(texts):
            raise ValueError("ids and texts must have the same length")
        for doc_id, text in zip(ids, texts):
            if doc_id in self._id_to_idx:
                continue
            tokens = self._tokenize(text)
            doc_idx = len(self._doc_ids)
            self._doc_ids.append(doc_id)
            self._doc_lens.append(len(tokens))
            self._id_to_idx[doc_id] = doc_idx
            tf = Counter(tokens)
            for term, count in tf.items():
                self._inverted.setdefault(term, []).append((doc_idx, count))
            self._active_count += 1
            self._active_total_dl += len(tokens)

    def remove(self, ids: list[str]) -> None:
        """Soft-remove. Statistics drop the doc immediately; the inverted
        index entries persist until :meth:`rebuild` is called (typically
        via ``engine.compact()``)."""
        for doc_id in ids:
            if doc_id in self._removed:
                continue
            doc_idx = self._id_to_idx.get(doc_id)
            if doc_idx is None:
                continue
            self._removed.add(doc_id)
            self._active_count -= 1
            self._active_total_dl -= self._doc_lens[doc_idx]

    def restore(self, ids: list[str]) -> None:
        """Undo a previous soft-remove. The doc's postings were retained,
        so restoring just re-admits the doc to active statistics. Calling
        on a doc that was never removed (or has already been rebuilt away)
        is a no-op."""
        for doc_id in ids:
            if doc_id not in self._removed:
                continue
            doc_idx = self._id_to_idx.get(doc_id)
            if doc_idx is None:
                continue
            self._removed.discard(doc_id)
            self._active_count += 1
            self._active_total_dl += self._doc_lens[doc_idx]

    def search(self, query: str, top_k: int) -> list[tuple[str, float]]:
        """Return up to ``top_k`` ``(doc_id, bm25_score)`` pairs in
        descending score order. Removed docs are excluded.
        """
        if self._active_count == 0 or top_k <= 0:
            return []
        q_tokens = self._tokenize(query)
        if not q_tokens:
            return []

        n = self._active_count
        avgdl = self._avgdl
        k1, b = self.k1, self.b

        scores: dict[str, float] = {}
        seen: set[str] = set()
        for term in q_tokens:
            if term in seen:
                continue
            seen.add(term)
            postings = self._inverted.get(term)
            if not postings:
                continue
            # Active df is the count of postings whose doc is not removed.
            active_postings = [
                (idx, tf)
                for idx, tf in postings
                if self._doc_ids[idx] not in self._removed
            ]
            df = len(active_postings)
            if df == 0:
                continue
            idf = math.log((n - df + 0.5) / (df + 0.5) + 1.0)
            for doc_idx, tf in active_postings:
                doc_id = self._doc_ids[doc_idx]
                dl = self._doc_lens[doc_idx]
                denom = tf + k1 * (1.0 - b + b * dl / avgdl)
                scores[doc_id] = scores.get(doc_id, 0.0) + idf * tf * (k1 + 1.0) / denom

        if not scores:
            return []
        results = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        return results[:top_k]

    def reset(self) -> None:
        """Drop every document and return to an empty index (keeping the
        configured ``k1`` / ``b`` / tokenizer). Used by
        ``engine._rebuild_bm25_from_store`` to wipe the in-memory state
        before reloading from SQLite."""
        self._doc_ids.clear()
        self._doc_lens.clear()
        self._id_to_idx.clear()
        self._inverted.clear()
        self._removed.clear()
        self._active_count = 0
        self._active_total_dl = 0

    def rebuild(self) -> None:
        """Drop soft-removed documents and recompact internal arrays.
        Call after a large ``forget`` / ``merge`` batch or during
        ``engine.compact()``.
        """
        if not self._removed:
            return
        kept_ids: list[str] = []
        kept_lens: list[int] = []
        kept_old_idx: list[int] = []
        for old_idx, doc_id in enumerate(self._doc_ids):
            if doc_id in self._removed:
                continue
            kept_ids.append(doc_id)
            kept_lens.append(self._doc_lens[old_idx])
            kept_old_idx.append(old_idx)
        old_to_new = {old: new for new, old in enumerate(kept_old_idx)}

        new_inverted: dict[str, list[tuple[int, int]]] = {}
        for term, postings in self._inverted.items():
            kept_postings = [
                (old_to_new[old_idx], tf)
                for old_idx, tf in postings
                if old_idx in old_to_new
            ]
            if kept_postings:
                new_inverted[term] = kept_postings

        self._doc_ids = kept_ids
        self._doc_lens = kept_lens
        self._id_to_idx = {doc_id: idx for idx, doc_id in enumerate(kept_ids)}
        self._inverted = new_inverted
        self._removed.clear()
        self._active_count = len(kept_ids)
        self._active_total_dl = sum(kept_lens)
