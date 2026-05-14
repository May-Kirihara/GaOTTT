"""Shared engine factory for Tier 1-7 perf tests.

The perf suite is a **manual verification step in the 仮説 → 実装 → 検証
loop**, run after implementing a feature to confirm production-grade
behaviour. It is **not** wired into CI.

For that intent to be honest the suite uses the **real RURI v3 310m
embedder** so every recorded number (latency, retrieval quality,
ranking) reflects what a user actually experiences. The model is loaded
once per pytest session via a module-level singleton and shared across
all engines.

The first test pays a ~5-10 second model-load cost (less on a warm HF
cache). All subsequent engines reuse the in-memory model.
"""
from __future__ import annotations

from pathlib import Path

from gaottt.config import GaOTTTConfig
from gaottt.core.engine import GaOTTTEngine
from gaottt.embedding.ruri import RuriEmbedder
from gaottt.index.bm25_index import BM25Index
from gaottt.index.faiss_index import FaissIndex
from gaottt.store.cache import CacheLayer
from gaottt.store.sqlite_store import SqliteStore


_SHARED_EMBEDDER: RuriEmbedder | None = None


def get_shared_embedder() -> RuriEmbedder:
    """Return a process-wide RURI embedder, loaded on first call.

    Loading SentenceTransformer + RURI weights costs several seconds.
    Sharing it across the 38-test suite turns 38 × that cost into a
    one-time amortised cost, keeping the manual verification runtime
    bounded to roughly *single-model-load + per-test work*.
    """
    global _SHARED_EMBEDDER
    if _SHARED_EMBEDDER is None:
        _SHARED_EMBEDDER = RuriEmbedder()
    return _SHARED_EMBEDDER


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
    """Construct a GaOTTTEngine wired with the shared RURI embedder and
    tmp_path-isolated stores.

    Caller is responsible for ``await eng.startup()`` and
    ``await eng.shutdown()``.
    """
    config = make_config(tmp_path, **config_overrides)
    embedder = get_shared_embedder()
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
