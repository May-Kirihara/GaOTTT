"""Unit smoke for ``scripts/diag_recall.py``.

Tests the snapshot-building and diff functions directly with a stub
engine so we don't need to load the production RURI model. End-to-end
CLI exercise (with the real embedder) lives in
``scripts/diag_recall.py`` itself via ``--data-dir /tmp/...``.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from tests.perf._helpers import make_engine


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "diag_recall.py"


def _load_diag_module():
    spec = importlib.util.spec_from_file_location("diag_recall", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.mark.asyncio
async def test_snapshot_query_captures_all_three_layers(tmp_path):
    """The snapshot record must contain engine_top, bm25_top, and raw_faiss_top."""
    diag = _load_diag_module()

    eng = make_engine(tmp_path)
    await eng.startup()
    try:
        await eng.index_documents([
            {"content": "Eleventy Pipeline static-site generator"},
            {"content": "Operation Husky Sicily 1943 landing"},
            {"content": "BM25 token frequency ranking"},
        ])
        snap = await diag._snapshot_query(eng, "Eleventy Pipeline", top_k=3)
    finally:
        await eng.shutdown()

    assert snap["query"] == "Eleventy Pipeline"
    assert snap["engine_top"], "engine_top should not be empty"
    assert snap["bm25_top"], "bm25_top should not be empty (BM25 enabled by default)"
    assert snap["raw_faiss_top"], "raw_faiss_top should not be empty"

    for row in snap["engine_top"]:
        assert set(row) >= {"id", "raw_score", "final_score", "displacement_norm"}
    for row in snap["bm25_top"]:
        assert set(row) >= {"id", "score"}
    for row in snap["raw_faiss_top"]:
        assert set(row) >= {"id", "cosine"}


def test_diff_id_lists_reordered():
    diag = _load_diag_module()
    out = diag._diff_id_lists(
        [{"id": "a"}, {"id": "b"}, {"id": "c"}],
        [{"id": "b"}, {"id": "a"}, {"id": "c"}],
    )
    assert out["added"] == []
    assert out["removed"] == []
    assert out["reordered"] is True


def test_diff_id_lists_added_removed():
    diag = _load_diag_module()
    out = diag._diff_id_lists(
        [{"id": "a"}, {"id": "b"}],
        [{"id": "b"}, {"id": "c"}],
    )
    assert out["added"] == ["c"]
    assert out["removed"] == ["a"]


@pytest.mark.asyncio
async def test_snapshot_output_is_json_serialisable(tmp_path):
    """Top-level snapshot dict (queries + headers) round-trips through JSON."""
    diag = _load_diag_module()

    eng = make_engine(tmp_path)
    await eng.startup()
    try:
        await eng.index_documents([{"content": f"doc {i}"} for i in range(5)])
        snap = await diag._snapshot_query(eng, "doc 2", top_k=3)
    finally:
        await eng.shutdown()

    payload = {
        "captured_at": "2026-05-14T00:00:00",
        "top_k": 3,
        "n_queries": 1,
        "engine_faiss_size": 5,
        "engine_bm25_size": 5,
        "queries": [snap],
    }
    encoded = json.dumps(payload, ensure_ascii=False)
    decoded = json.loads(encoded)
    assert decoded["queries"][0]["query"] == "doc 2"
