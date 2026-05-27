"""Tests for ``SqliteStore.get_all_originals`` — the COALESCE fallback that
populates ``cache.original_id_by_id`` so Stage 7.1 anti-hub can cluster
chunked content.

Plans-Lens-Hygiene Stage 2 regression: in the 2026-05-27 GLM review
investigation we wrongly concluded "file source has 0% cluster_key
coverage" by looking at ``json_extract(metadata, '$.original_id')`` only.
The actual ``get_all_originals`` query is::

    SELECT id, COALESCE(
        json_extract(metadata, '$.original_id'),
        json_extract(metadata, '$.file_path')
    )

so chunked file ingests (which set ``file_path`` but not ``original_id``)
ARE clustered — at 100% coverage in production. These tests pin that
behavior so a future refactor of the query does not silently re-open the
gap we already (correctly) closed.
"""
from __future__ import annotations

import pytest

from gaottt.store.sqlite_store import SqliteStore


@pytest.fixture
async def store(tmp_path):
    s = SqliteStore(db_path=str(tmp_path / "test.db"))
    await s.initialize()
    yield s
    await s.close()


async def _seed_doc(store: SqliteStore, doc_id: str, metadata: dict | None) -> None:
    await store.save_documents([
        {"id": doc_id, "content": f"content {doc_id}", "metadata": metadata},
    ])


async def test_explicit_original_id_wins_over_file_path(store):
    """When both are set, the ``$.original_id`` field takes precedence —
    the COALESCE fallback to ``$.file_path`` is only for legacy ingests
    that never set ``original_id``."""
    await _seed_doc(store, "n1", {
        "source": "file",
        "original_id": "explicit-id",
        "file_path": "/some/path.md",
    })
    originals = await store.get_all_originals()
    assert originals["n1"] == "explicit-id"


async def test_file_path_fallback_when_original_id_absent(store):
    """The legacy file-ingest case: ``file_path`` is set, ``original_id``
    is not. ``get_all_originals`` must still return a non-None cluster key
    so Stage 7.1 anti-hub can demote same-book chunks."""
    await _seed_doc(store, "n1", {
        "source": "file",
        "file_path": "/books/foo.md",
        "title": "Foo",
        "chunk_index": 0,
    })
    await _seed_doc(store, "n2", {
        "source": "file",
        "file_path": "/books/foo.md",
        "title": "Foo",
        "chunk_index": 1,
    })
    originals = await store.get_all_originals()
    # Both chunks share the same key — the precondition for anti-hub to
    # cluster them and demote one when the other already won a slot.
    assert originals["n1"] == "/books/foo.md"
    assert originals["n2"] == "/books/foo.md"
    assert originals["n1"] == originals["n2"]


async def test_singleton_with_neither_field_is_omitted(store):
    """When both ``original_id`` and ``file_path`` are absent the COALESCE
    returns NULL and the row is filtered out of the result dict.
    Downstream ``_cluster_key_for`` interprets a missing entry as "no
    cluster" (the node is its own singleton), which means it never gets
    an anti-hub penalty — correct for genuine singletons."""
    await _seed_doc(store, "n1", {"source": "agent"})  # no orig/path
    originals = await store.get_all_originals()
    assert "n1" not in originals


async def test_chunked_book_produces_one_cluster_per_file_path(store):
    """Acceptance scenario for the GLM-review-discovered 638-chunk book:
    all chunks of one book share one cluster key under the COALESCE
    fallback. Stage 7.1 anti-hub then sees them as one cluster and
    demotes duplicates from top-K."""
    book_path = "/books/big-book.md"
    for i in range(20):  # smaller-scale stand-in for the 638-chunk book
        await _seed_doc(store, f"chunk-{i}", {
            "source": "file",
            "file_path": book_path,
            "title": "Big Book",
            "chunk_index": i,
        })
    # Plus a chunk from a different book to confirm clusters separate
    await _seed_doc(store, "other-chunk", {
        "source": "file",
        "file_path": "/books/other-book.md",
        "chunk_index": 0,
    })

    originals = await store.get_all_originals()
    # All chunks of the big book share one cluster key.
    big_cluster = {originals[f"chunk-{i}"] for i in range(20)}
    assert big_cluster == {book_path}
    # The other book's chunk gets its own cluster.
    assert originals["other-chunk"] == "/books/other-book.md"
    assert originals["other-chunk"] != book_path


async def test_metadata_is_null_row_omitted(store):
    """``WHERE metadata IS NOT NULL`` — rows without any metadata at all
    are skipped, not crashed on. Defensive coverage for legacy / corrupted
    rows that pre-date the metadata column having a JSON value."""
    await _seed_doc(store, "n1", None)
    originals = await store.get_all_originals()
    assert "n1" not in originals
