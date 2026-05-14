"""Tests for FaissIndex.save() atomic-write guarantee.

Regression for the 2026-05-14 production incident where
``gaottt.virtual.faiss`` was corrupted to 0 bytes twice during routine
backend restarts — the virtual_faiss_save_loop fires every 60 s, so a
SIGTERM mid-write truncated the file before contents were flushed.

The fix is in ``FaissIndex.save()``: write to ``path.tmp`` then
``os.replace`` to the final path. ``os.replace`` is atomic on POSIX
and Windows, so a kill / crash mid-write leaves the previous valid
file at ``path`` intact.
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest

from gaottt.index.faiss_index import FaissIndex

DIM = 4


def _make_index(n_vectors: int = 3) -> FaissIndex:
    idx = FaissIndex(dimension=DIM)
    rng = np.random.default_rng(seed=42)
    vecs = rng.standard_normal((n_vectors, DIM)).astype(np.float32)
    # Normalize for cosine
    vecs /= np.linalg.norm(vecs, axis=1, keepdims=True)
    ids = [f"node_{i}" for i in range(n_vectors)]
    idx.add(vecs, ids)
    return idx


def test_save_then_load_roundtrip(tmp_path: Path) -> None:
    """Basic correctness: save produces a loadable file."""
    idx = _make_index(5)
    p = str(tmp_path / "test.faiss")
    idx.save(p)

    assert os.path.exists(p)
    assert os.path.exists(p + ".ids")
    # .tmp scratch files must be gone after a clean save
    assert not os.path.exists(p + ".tmp")
    assert not os.path.exists(p + ".ids.tmp")

    idx2 = FaissIndex(dimension=DIM)
    idx2.load(p)
    assert idx2.size == 5
    assert idx2._id_map == [f"node_{i}" for i in range(5)]


def test_save_replaces_existing_atomically(tmp_path: Path) -> None:
    """A second save() must replace the previous file in one atomic step.

    At no observable point between the old file existing and the new
    file existing should ``path`` be a 0-byte stub. We can't easily
    catch the intermediate state in a single-threaded test, but we can
    verify the final state is consistent and the temp file is cleaned
    up.
    """
    p = str(tmp_path / "x.faiss")

    idx_v1 = _make_index(3)
    idx_v1.save(p)
    size_v1 = os.path.getsize(p)

    idx_v2 = _make_index(10)
    idx_v2.save(p)
    size_v2 = os.path.getsize(p)

    assert size_v2 > size_v1
    assert not os.path.exists(p + ".tmp")
    assert not os.path.exists(p + ".ids.tmp")

    idx_loaded = FaissIndex(dimension=DIM)
    idx_loaded.load(p)
    assert idx_loaded.size == 10


def test_stale_tmp_does_not_corrupt_load(tmp_path: Path) -> None:
    """If a previous save was interrupted, a stale ``.tmp`` remains on
    disk. The next ``load()`` must ignore it and use the real file.
    """
    p = str(tmp_path / "y.faiss")
    idx = _make_index(4)
    idx.save(p)

    # Simulate an interrupted save that left junk in path.tmp
    Path(p + ".tmp").write_bytes(b"corrupted partial garbage")
    Path(p + ".ids.tmp").write_text("not\nreal\nids\n")

    # load() must not touch the .tmp files; the real path is fine
    idx_loaded = FaissIndex(dimension=DIM)
    idx_loaded.load(p)
    assert idx_loaded.size == 4
    assert idx_loaded._id_map == [f"node_{i}" for i in range(4)]


def test_simulated_kill_mid_save_keeps_old_file_intact(tmp_path: Path) -> None:
    """The atomic-write contract — the symptom we are fixing.

    Strategy: monkey-patch ``faiss.write_index`` to raise mid-write
    *after* the tmp file is partially created. The exception bubbles
    out of ``save()`` (we re-raise via the patch), but the real file
    at ``path`` must still be the previous valid version.
    """
    import faiss

    p = str(tmp_path / "z.faiss")
    idx_v1 = _make_index(3)
    idx_v1.save(p)
    expected_size = os.path.getsize(p)
    expected_id_map = list(idx_v1._id_map)

    idx_v2 = _make_index(20)  # larger second version

    # Patch faiss.write_index to write to tmp but then raise, simulating
    # a kill / crash after the truncate+open phase but before completion.
    original_write = faiss.write_index

    def evil_write(index, path_str):
        # Touch the tmp file (truncate to 0) then raise — this mimics
        # the OS state right after a kill during a real write_index call.
        Path(path_str).write_bytes(b"")
        raise RuntimeError("simulated kill during write_index")

    faiss.write_index = evil_write
    try:
        with pytest.raises(RuntimeError, match="simulated kill"):
            idx_v2.save(p)
    finally:
        faiss.write_index = original_write

    # The real file at ``path`` must be UNCHANGED — same size as v1.
    assert os.path.getsize(p) == expected_size, (
        "save() corrupted the real file even though only .tmp should be touched"
    )

    # Reload to make sure the existing data is still valid
    idx_check = FaissIndex(dimension=DIM)
    idx_check.load(p)
    assert idx_check.size == 3
    assert idx_check._id_map == expected_id_map

    # The orphan tmp may remain (next save will overwrite); cleanup is
    # not a correctness invariant, just a hygiene one.


def test_ids_file_fsync_does_not_break_save(tmp_path: Path) -> None:
    """The .ids write path uses fsync. Verify the path still works on
    filesystems where fsync is a no-op (most cases) and produces the
    expected file."""
    p = str(tmp_path / "w.faiss")
    idx = _make_index(7)
    idx.save(p)

    with open(p + ".ids") as f:
        lines = [line.strip() for line in f if line.strip()]
    assert lines == [f"node_{i}" for i in range(7)]
