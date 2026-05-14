"""Shared engine factory + StubEmbedder for Tier 1-7 perf tests.

Centralises the boilerplate so each tier test stays focused on what it
verifies. The default config disables every non-deterministic side
channel (dream loop, supernova, write-behind delays, persona boost) so
size invariants and round-trip checks are reproducible.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np

from gaottt.config import GaOTTTConfig
from gaottt.core.engine import GaOTTTEngine
from gaottt.index.bm25_index import BM25Index
from gaottt.index.faiss_index import FaissIndex
from gaottt.store.cache import CacheLayer
from gaottt.store.sqlite_store import SqliteStore


class StubEmbedder:
    """Deterministic random embeddings keyed on md5 of text.

    Cosine similarity has no relationship to lexical overlap — useful
    when a test wants FAISS and BM25 to behave as independent metric
    tensors (same shape used by ``test_engine_bm25_union.py``).
    """

    def __init__(self, dim: int = 768):
        self.dim = dim

    @property
    def dimension(self) -> int:
        return self.dim

    def encode_documents(self, contents):
        return np.array([self._embed(c) for c in contents], dtype=np.float32)

    def encode_query(self, text):
        return self._embed(text).reshape(1, -1).astype(np.float32)

    def _embed(self, text: str) -> np.ndarray:
        seed = int.from_bytes(
            hashlib.md5(text.encode("utf-8")).digest()[:4], "big"
        )
        rng = np.random.default_rng(seed)
        v = rng.standard_normal(self.dim).astype(np.float32)
        v /= np.linalg.norm(v) + 1e-9
        return v


def make_config(tmp_path, **overrides) -> GaOTTTConfig:
    """Build a deterministic test config rooted at ``tmp_path``.

    All non-deterministic / asynchronous side channels are disabled by
    default. Override anything you need with kwargs.

    ``tmp_path`` accepts both ``pathlib.Path`` (the pytest fixture form)
    and ``str`` (so ad-hoc scripts and ``scripts/diag_recall.py``-style
    callers don't have to wrap the path themselves).
    """
    tmp_path = Path(tmp_path)
    defaults = dict(
        data_dir=str(tmp_path),
        db_path=str(tmp_path / "test.db"),
        faiss_index_path=str(tmp_path / "test.faiss"),
        virtual_faiss_index_path=str(tmp_path / "test.virtual.faiss"),
        virtual_faiss_enabled=True,
        hybrid_bm25_enabled=True,
        wave_initial_k=3,
        wave_seed_mass_alpha=0.0,
        wave_dynamic_k_enabled=False,
        genesis_kick_enabled=False,
        supernova_enabled=False,
        dream_enabled=False,
        faiss_save_interval_seconds=0.0,
        virtual_faiss_save_interval_seconds=0.0,
        flush_interval_seconds=0.05,
        persona_boost_enabled=False,
        mass_conservation_enabled=False,
        mass_bh_enabled=False,
    )
    defaults.update(overrides)
    return GaOTTTConfig(**defaults)


def make_engine(tmp_path, **config_overrides) -> GaOTTTEngine:
    """Construct a GaOTTTEngine wired with stub embedder + tmp_path-isolated stores.

    Caller is responsible for ``await eng.startup()`` and
    ``await eng.shutdown()`` (or use the ``engine`` fixture below).
    """
    config = make_config(tmp_path, **config_overrides)
    embedder = StubEmbedder(dim=config.embedding_dim)
    faiss_index = FaissIndex(dimension=config.embedding_dim)
    virtual_faiss_index = (
        FaissIndex(dimension=config.embedding_dim)
        if config.virtual_faiss_enabled else None
    )
    bm25_index = (
        BM25Index(
            k1=config.bm25_k1,
            b=config.bm25_b,
            tokenizer=config.bm25_tokenizer,
        ) if config.hybrid_bm25_enabled else None
    )
    store = SqliteStore(db_path=config.db_path)
    cache = CacheLayer(
        flush_interval=config.flush_interval_seconds,
        flush_threshold=config.flush_threshold,
    )
    return GaOTTTEngine(
        config=config,
        embedder=embedder,
        faiss_index=faiss_index,
        cache=cache,
        store=store,
        virtual_faiss_index=virtual_faiss_index,
        bm25_index=bm25_index,
    )


async def active_doc_count(engine: GaOTTTEngine) -> int:
    """Active (non-archived) document count from the SQLite store.

    Treated as ground truth for Tier 5 size-invariant assertions.
    """
    states = await engine.store.get_all_node_states()
    return sum(1 for s in states if not s.is_archived)
