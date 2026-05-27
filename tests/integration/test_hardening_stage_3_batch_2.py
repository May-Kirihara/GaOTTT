"""Hardening Stage 3 第二弾 — M1 (SQLite 999 variable limit) / M5 (BM25
tombstone auto-rebuild) の teeth-having 回帰テスト.

各 fix が **修正前なら落ちる** ことを保証するため:
- M1: 1500 件の ID リスト (default chunk=900 を超える) を渡し、修正前なら
  ``sqlite3.OperationalError: too many SQL variables`` で落ちる
- M5: tombstone 比率が閾値超えた状態で ``remove`` を呼び、``rebuild`` が
  自動発火 (``_removed`` が空になる + inverted index が再構築される) こと
  を確認。修正前なら ``_removed`` に残り続け search の active filter cost
  が積み上がる
"""

from __future__ import annotations

import sqlite3

import numpy as np
import pytest

from gaottt.index.bm25_index import BM25Index
from gaottt.store.sqlite_store import SqliteStore


async def _force_low_var_limit(store: SqliteStore, limit: int = 999) -> None:
    """Force the per-connection ``SQLITE_LIMIT_VARIABLE_NUMBER`` to ``limit``.

    Modern SQLite builds default to 32766, which makes M1 untestable on a
    host that ships the higher limit. We pin the limit to the historic
    default (999) inside each test so the teeth bite uniformly — without
    M1's chunking the ``IN (?,?,...)`` calls would raise ``too many SQL
    variables`` mid-flow.

    aiosqlite runs the underlying sqlite3.Connection on a worker thread, so
    ``setlimit`` must be dispatched via ``_execute`` (a private helper)
    rather than called directly from the asyncio task thread.
    """
    assert store._conn is not None

    def _set(conn):
        conn.setlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER, limit)

    await store._conn._execute(_set, store._conn._conn)


# ----- M1 — SQLite 999 variable limit chunking -----


@pytest.mark.asyncio
async def test_m1_get_node_states_handles_more_than_999_ids(tmp_path):
    """get_node_states with 1500 IDs would raise the 999-variable limit
    without chunking. The chunked version must return all 1500 states."""
    store = SqliteStore(db_path=str(tmp_path / "test.db"))
    await store.initialize()
    await _force_low_var_limit(store)
    n = 1500
    ids = [f"n{i:04d}" for i in range(n)]
    for nid in ids:
        await store._conn.execute(
            "INSERT INTO nodes (id, mass) VALUES (?, ?)", (nid, 1.0)
        )
    await store._conn.commit()

    states = await store.get_node_states(ids)
    assert len(states) == n
    assert "n0000" in states and "n1499" in states


@pytest.mark.asyncio
async def test_m1_find_existing_hashes_handles_more_than_999_hashes(tmp_path):
    """find_existing_hashes with >999 hashes used to hit the SQLite limit
    mid-INSERT-OR-IGNORE flow during bulk ingest. Now it must chunk."""
    store = SqliteStore(db_path=str(tmp_path / "test.db"))
    await store.initialize()
    await _force_low_var_limit(store)
    n = 1200
    docs = [
        {"id": f"d{i}", "content": f"content {i}", "metadata": None}
        for i in range(n)
    ]
    await store.save_documents(docs)

    hashes = [store._content_hash(d["content"]) for d in docs]
    # Add some non-existent hashes too.
    hashes.extend([f"fakehash{i:030d}" for i in range(300)])
    found = await store.find_existing_hashes(hashes)
    assert len(found) == n


@pytest.mark.asyncio
async def test_m1_hard_delete_nodes_handles_more_than_450_ids(tmp_path):
    """hard_delete_nodes uses ``src IN (...) OR dst IN (...)`` for edges,
    doubling the bind count. With 500 ids that's 1000 binds — over the 999
    limit. Without M1 chunking this raises ``too many SQL variables``."""
    store = SqliteStore(db_path=str(tmp_path / "test.db"))
    await store.initialize()
    await _force_low_var_limit(store)
    n = 600
    ids = [f"n{i:04d}" for i in range(n)]
    docs = [{"id": nid, "content": f"c{nid}", "metadata": None} for nid in ids]
    await store.save_documents(docs)
    for nid in ids:
        await store._conn.execute(
            "INSERT INTO nodes (id, mass) VALUES (?, ?)", (nid, 1.0)
        )
    # A few edges spanning various pairs.
    await store._conn.execute(
        "INSERT INTO edges (src, dst, weight) VALUES (?, ?, ?)",
        ("n0000", "n0599", 1.0),
    )
    await store._conn.commit()

    deleted = await store.hard_delete_nodes(ids)
    assert deleted == n
    # And edges referencing them are gone.
    cursor = await store._conn.execute("SELECT COUNT(*) FROM edges")
    row = await cursor.fetchone()
    assert row[0] == 0


@pytest.mark.asyncio
async def test_m1_set_archived_handles_more_than_999_ids(tmp_path):
    """set_archived: 1 placeholder for the flag + N for ids; with N=999 we'd
    have 1000 binds and the call fails. M1 chunks ids to 900 max."""
    store = SqliteStore(db_path=str(tmp_path / "test.db"))
    await store.initialize()
    await _force_low_var_limit(store)
    n = 1500
    ids = [f"n{i:04d}" for i in range(n)]
    for nid in ids:
        await store._conn.execute(
            "INSERT INTO nodes (id, mass) VALUES (?, ?)", (nid, 1.0)
        )
    await store._conn.commit()

    affected = await store.set_archived(ids, archived=True)
    assert affected == n


@pytest.mark.asyncio
async def test_m1_load_displacements_handles_more_than_999_ids(tmp_path):
    """load_displacements(ids=[...]) with >999 ids previously crashed.
    Round-trip a chunked load to verify content integrity."""
    store = SqliteStore(db_path=str(tmp_path / "test.db"))
    await store.initialize()
    await _force_low_var_limit(store)
    n = 1100
    ids = [f"n{i:04d}" for i in range(n)]
    for nid in ids:
        await store._conn.execute(
            "INSERT INTO nodes (id, mass) VALUES (?, ?)", (nid, 1.0)
        )
    await store._conn.commit()
    disps = {nid: np.full(8, float(i), dtype=np.float32) for i, nid in enumerate(ids)}
    await store.save_displacements(disps)

    loaded = await store.load_displacements(ids=ids)
    assert len(loaded) == n
    # Spot-check that the per-id displacement was preserved.
    assert np.allclose(loaded["n0050"], np.full(8, 50.0, dtype=np.float32))
    assert np.allclose(loaded["n1099"], np.full(8, 1099.0, dtype=np.float32))


# ----- M5 — BM25 tombstone auto-rebuild -----


def test_m5_auto_rebuild_fires_when_threshold_reached():
    """Remove 25% of docs (threshold 0.2); _removed must be cleared by the
    auto-rebuild. Without M5 the soft-removed set grows monotonically."""
    bm25 = BM25Index(auto_rebuild_threshold=0.2)
    n = 100
    ids = [f"d{i}" for i in range(n)]
    texts = [f"document number {i} with some text" for i in range(n)]
    bm25.add(ids, texts)
    assert bm25.size == n

    # Remove 25 — threshold ratio = 25/100 = 0.25 >= 0.2 → auto-rebuild.
    to_remove = ids[:25]
    bm25.remove(to_remove)

    # Teeth: without M5, _removed would still have 25 entries.
    assert len(bm25._removed) == 0
    # Active count down to 75, and the inverted index is recompacted so the
    # removed ids are no longer in _id_to_idx.
    assert bm25.size == 75
    for rid in to_remove:
        assert rid not in bm25._id_to_idx


def test_m5_below_threshold_does_not_auto_rebuild():
    """If tombstone ratio < threshold, soft-removed entries persist as
    before — this preserves the original behavior for short forget batches.
    """
    bm25 = BM25Index(auto_rebuild_threshold=0.2)
    n = 100
    ids = [f"d{i}" for i in range(n)]
    texts = [f"doc {i}" for i in range(n)]
    bm25.add(ids, texts)

    # Remove 10 — ratio = 10/100 = 0.10 < 0.20 → no auto-rebuild.
    bm25.remove(ids[:10])
    assert len(bm25._removed) == 10
    assert bm25.size == 90
    # Ids are still in _id_to_idx (postings kept, just soft-flagged).
    for rid in ids[:10]:
        assert rid in bm25._id_to_idx


def test_m5_disabled_with_zero_threshold():
    """auto_rebuild_threshold=0.0 disables the auto-rebuild path entirely —
    matches the pre-M5 behavior for callers that want explicit control."""
    bm25 = BM25Index(auto_rebuild_threshold=0.0)
    ids = [f"d{i}" for i in range(20)]
    bm25.add(ids, [f"doc {i}" for i in range(20)])

    # Remove 90% — would normally auto-rebuild, but disabled here.
    bm25.remove(ids[:18])
    assert len(bm25._removed) == 18
    # All 20 ids still in _id_to_idx because no rebuild happened.
    for rid in ids:
        assert rid in bm25._id_to_idx


def test_m5_search_still_excludes_removed_after_threshold():
    """After auto-rebuild, search must continue to exclude the removed docs
    (they are physically gone from the inverted index, not just flagged)."""
    bm25 = BM25Index(auto_rebuild_threshold=0.2)
    ids = [f"d{i}" for i in range(50)]
    texts = [f"alpha beta gamma {i}" for i in range(50)]
    bm25.add(ids, texts)

    # Remove first 15 (30%, > 0.2 threshold).
    bm25.remove(ids[:15])
    assert len(bm25._removed) == 0  # auto-rebuild fired

    results = bm25.search("alpha", top_k=50)
    found_ids = {doc_id for doc_id, _ in results}
    # None of the removed should appear.
    assert all(rid not in found_ids for rid in ids[:15])
    # Remaining ones do appear.
    assert "d25" in found_ids
