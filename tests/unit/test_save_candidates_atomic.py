"""Fix 3 tests: atomic state file write + read-side corruption tolerance.

Tests that save_candidates.py uses atomic write (os.replace) and
save_candidates_inject.py handles corrupted state files gracefully
(silently deletes and returns 0).
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture
def state_dir(tmp_path):
    d = tmp_path / "save_candidates"
    d.mkdir()
    return d


def _write_state(state_dir: Path, session_id: str, content: str) -> Path:
    target = state_dir / f"{session_id}.txt"
    target.write_text(content, encoding="utf-8")
    return target


def test_inject_reads_valid_state(state_dir):
    from scripts.hooks import save_candidates_inject as mod

    target = _write_state(state_dir, "sess1", "<gaottt-save-candidates>block</gaottt-save-candidates>")
    captured = {}

    def fake_emit(text):
        captured["text"] = text

    with (
        patch.object(mod, "_STATE_DIR", state_dir),
        patch.object(mod, "_disabled", return_value=False),
        patch.object(mod, "_emit", fake_emit),
        patch("sys.stdin", __import__("io").StringIO(json.dumps({"session_id": "sess1"}))),
    ):
        ret = mod.main()

    assert ret == 0
    assert not target.exists()
    assert "<gaottt-save-candidates>" in captured["text"]


def test_inject_corrupted_file_is_deleted(state_dir):
    from scripts.hooks import save_candidates_inject as mod

    target = state_dir / "sess_bad.txt"
    target.write_bytes(b"\xff\xfe invalid binary \x00\x80")

    with (
        patch.object(mod, "_STATE_DIR", state_dir),
        patch.object(mod, "_disabled", return_value=False),
        patch("sys.stdin", __import__("io").StringIO(json.dumps({"session_id": "sess_bad"}))),
    ):
        ret = mod.main()

    assert ret == 0
    assert not target.exists()


def test_inject_empty_file_no_output(state_dir):
    from scripts.hooks import save_candidates_inject as mod

    _write_state(state_dir, "sess_empty", "")
    emitted = []

    def fake_emit(text):
        emitted.append(text)

    with (
        patch.object(mod, "_STATE_DIR", state_dir),
        patch.object(mod, "_disabled", return_value=False),
        patch.object(mod, "_emit", fake_emit),
        patch("sys.stdin", __import__("io").StringIO(json.dumps({"session_id": "sess_empty"}))),
    ):
        ret = mod.main()

    assert ret == 0
    assert emitted == []


def test_atomic_write_no_partial_on_error(state_dir):
    block = "<gaottt-save-candidates>test block content</gaottt-save-candidates>"
    target = state_dir / "sess_atomic.txt"

    with (
        patch(
            "scripts.hooks.save_candidates._state_path",
            return_value=target,
        ),
        patch("scripts.hooks.save_candidates._EMIT_MODE", "state"),
        patch("scripts.hooks.save_candidates._disabled", return_value=False),
        patch("scripts.hooks.save_candidates._STATE_DIR", state_dir),
        patch(
            "scripts.hooks.save_candidates._call_save_candidates",
            return_value=block,
        ),
        patch("os.replace", side_effect=PermissionError("nope")),
    ):
        from scripts.hooks import save_candidates as mod

        ret = mod.main()

    assert ret == 0
    assert not target.exists()
    tmp_files = list(state_dir.glob(".save-cand-*.tmp"))
    assert len(tmp_files) == 0
