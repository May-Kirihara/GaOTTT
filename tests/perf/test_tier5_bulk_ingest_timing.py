"""Tier 5 integrity — bulk ingest timing sanity.

Catches regressions like the 2026-05-14 incident where a single MCP
``ingest`` call held a 47-minute SQLite transaction and bloated the WAL
to 7.6 GB. The check is intentionally loose — a *generous* upper bound
that only fires on a real pathology (O(N²) loop, missing commit,
synchronous flush per doc).

Two scenarios:
  1. Direct ``engine.index_documents`` with N=200 stub docs.
  2. Full ``services.ingest_service.ingest`` against a tmpdir of .md files.

Both must complete well under :data:`MAX_SECONDS` even on a slow box.
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from gaottt.services import ingest_service
from tests.perf._helpers import active_doc_count, make_engine


# Upper bound. Local: ~1 s. CI: usually a few seconds. Anything over this
# is a structural regression, not a slow machine.
MAX_SECONDS = 30.0


@pytest.mark.asyncio
async def test_index_documents_200_docs_under_budget(tmp_path):
    eng = make_engine(tmp_path)
    await eng.startup()
    try:
        docs = [
            {"content": f"bulk doc {i} body lorem ipsum dolor sit amet"}
            for i in range(200)
        ]
        start = time.monotonic()
        ids = await eng.index_documents(docs)
        elapsed = time.monotonic() - start

        assert len(ids) == 200
        assert eng.faiss_index.size == 200
        assert await active_doc_count(eng) == 200
        assert elapsed < MAX_SECONDS, (
            f"index_documents(200) took {elapsed:.2f}s > {MAX_SECONDS}s budget"
        )
    finally:
        await eng.shutdown()


@pytest.mark.asyncio
async def test_ingest_service_directory_under_budget(tmp_path):
    """End-to-end via services.ingest_service — same path the MCP tool walks."""
    eng = make_engine(tmp_path)
    await eng.startup()
    try:
        docs_dir = tmp_path / "corpus"
        docs_dir.mkdir()
        for i in range(50):
            (docs_dir / f"doc_{i:03d}.md").write_text(
                f"# Document {i}\n\nSome body text for document number {i}.\n"
                "Repeated content to give the chunker something to do.\n" * 3,
                encoding="utf-8",
            )

        start = time.monotonic()
        result = await ingest_service.ingest(
            eng, path=str(docs_dir), source="file", recursive=True,
            pattern="*.md", chunk_size=2000,
        )
        elapsed = time.monotonic() - start

        assert result.found >= 50, f"Loader missed files: found={result.found}"
        assert result.ingested >= 50, f"Engine dropped docs: ingested={result.ingested}"
        assert elapsed < MAX_SECONDS, (
            f"ingest_service.ingest(50 md files) took {elapsed:.2f}s > {MAX_SECONDS}s budget"
        )
    finally:
        await eng.shutdown()


@pytest.mark.asyncio
async def test_wal_size_stays_reasonable_after_bulk(tmp_path):
    """The WAL file should not bloat past the data file after a bulk ingest.

    The 2026-05-14 incident left a 7.6 GB WAL alongside a few-hundred-MB
    main file. Bound at 5× the main DB size — a real WAL leak is orders
    of magnitude larger.
    """
    eng = make_engine(tmp_path)
    await eng.startup()
    try:
        await eng.index_documents(
            [{"content": f"wal sanity {i} " + ("body " * 50)} for i in range(300)]
        )
        await eng.cache.flush_to_store(eng.store)
    finally:
        await eng.shutdown()

    db_path = Path(tmp_path) / "test.db"
    wal_path = Path(tmp_path) / "test.db-wal"
    if not db_path.exists():
        pytest.skip("DB file not at expected path; can't audit WAL")
    db_size = db_path.stat().st_size
    wal_size = wal_path.stat().st_size if wal_path.exists() else 0
    # After clean shutdown the WAL is usually checkpointed to 0. The
    # bound just catches the pathological "WAL grew to multi-GB" case.
    assert wal_size <= max(db_size * 5, 10 * 1024 * 1024), (
        f"WAL bloat: wal={wal_size} bytes vs db={db_size} bytes"
    )
