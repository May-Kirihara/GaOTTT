"""Regression: H5 — per-field env-var override layer.

Precedence (highest wins): GAOTTT_<FIELD> env > config.json > default.
Only scalar fields are env-settable; the bool branch must not fall into
the ``bool("false") is True`` trap.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from gaottt.config import GaOTTTConfig


def test_env_overrides_default_with_correct_type(monkeypatch):
    monkeypatch.setenv("GAOTTT_GAMMA", "0.8")
    monkeypatch.setenv("GAOTTT_TOP_K", "11")
    cfg = GaOTTTConfig.from_config_file()
    assert cfg.gamma == 0.8
    assert isinstance(cfg.gamma, float)
    assert cfg.top_k == 11
    assert isinstance(cfg.top_k, int)


@pytest.mark.parametrize(
    "raw,expected",
    [("false", False), ("0", False), ("", False), ("no", False),
     ("true", True), ("1", True), ("YES", True), ("On", True)],
)
def test_bool_env_does_not_fall_into_truthy_string_trap(monkeypatch, raw, expected):
    # bool("false") is True in Python — a naive cast would make
    # GAOTTT_DREAM_ENABLED=false enable the dream loop.
    monkeypatch.setenv("GAOTTT_DREAM_ENABLED", raw)
    cfg = GaOTTTConfig.from_config_file()
    assert cfg.dream_enabled is expected


def test_env_beats_config_file(monkeypatch):
    # Simulate a config.json that sets gamma=0.3; env must still win.
    monkeypatch.setattr(
        "gaottt.config._load_config_file", lambda: {"gamma": 0.3, "top_k": 7}
    )
    # No env → file value applies.
    monkeypatch.delenv("GAOTTT_GAMMA", raising=False)
    assert GaOTTTConfig.from_config_file().gamma == 0.3
    # Env present → env wins over file.
    monkeypatch.setenv("GAOTTT_GAMMA", "0.95")
    cfg = GaOTTTConfig.from_config_file()
    assert cfg.gamma == 0.95
    assert cfg.top_k == 7  # untouched file value preserved


def test_invalid_env_value_is_ignored_not_fatal(monkeypatch):
    monkeypatch.setenv("GAOTTT_TOP_K", "not-an-int")
    cfg = GaOTTTConfig.from_config_file()  # must not raise
    assert cfg.top_k == GaOTTTConfig().top_k  # fell back to default


def test_legacy_ger_rag_env_honored_with_warning(monkeypatch, caplog):
    import logging

    monkeypatch.delenv("GAOTTT_GAMMA", raising=False)
    monkeypatch.setenv("GER_RAG_GAMMA", "0.42")
    with caplog.at_level(logging.WARNING, logger="gaottt.config"):
        cfg = GaOTTTConfig.from_config_file()
    assert cfg.gamma == 0.42
    assert any("GER_RAG_GAMMA is deprecated" in r.message for r in caplog.records)


def test_gaottt_env_takes_precedence_over_legacy(monkeypatch):
    monkeypatch.setenv("GAOTTT_GAMMA", "0.11")
    monkeypatch.setenv("GER_RAG_GAMMA", "0.99")
    assert GaOTTTConfig.from_config_file().gamma == 0.11


# WP-1 — embedder lazy spawn knobs (supervisor lazily spawns a dedicated
# embedding service). Detail: docs/plans/embedder-auto-spawn-supervisor.md.
def test_embedder_lazy_spawn_defaults():
    cfg = GaOTTTConfig()
    assert cfg.supervisor_spawn_embedder is True
    assert cfg.embedder_spawn_idle_timeout_seconds == 300.0
    assert cfg.embedder_spawn_readiness_timeout_seconds == 90.0
    assert cfg.embedder_idle_watchdog_poll_seconds == 30.0


@pytest.mark.parametrize(
    "raw,expected",
    [("false", False), ("0", False), ("no", False),
     ("true", True), ("1", True), ("YES", True), ("On", True)],
)
def test_supervisor_spawn_embedder_bool_env(monkeypatch, raw, expected):
    monkeypatch.setenv("GAOTTT_SUPERVISOR_SPAWN_EMBEDDER", raw)
    cfg = GaOTTTConfig.from_config_file()
    assert cfg.supervisor_spawn_embedder is expected


def test_embedder_lazy_spawn_float_env_overrides(monkeypatch):
    monkeypatch.setenv("GAOTTT_EMBEDDER_SPAWN_IDLE_TIMEOUT_SECONDS", "120.5")
    monkeypatch.setenv("GAOTTT_EMBEDDER_SPAWN_READINESS_TIMEOUT_SECONDS", "45")
    monkeypatch.setenv("GAOTTT_EMBEDDER_IDLE_WATCHDOG_POLL_SECONDS", "15")
    cfg = GaOTTTConfig.from_config_file()
    assert cfg.embedder_spawn_idle_timeout_seconds == 120.5
    assert isinstance(cfg.embedder_spawn_idle_timeout_seconds, float)
    assert cfg.embedder_spawn_readiness_timeout_seconds == 45.0
    assert isinstance(cfg.embedder_spawn_readiness_timeout_seconds, float)
    assert cfg.embedder_idle_watchdog_poll_seconds == 15.0
    assert isinstance(cfg.embedder_idle_watchdog_poll_seconds, float)


# ===========================================================================
# data_dir precedence — 2026-09-17 multiverse /route 503 regression
# ===========================================================================
#
# ``data_dir`` is a ``field(default_factory=...)`` field, so the generic
# env loop skips it; a config-file ``data_dir`` used to win via the
# constructor-argument path, inverting the documented H5 precedence
# (env > file > default) for this one field. Real damage: the multiverse
# supervisor passes the correct GAOTTT_DATA_DIR at spawn, but
# ~/.config/gaottt/config.json pinned the backend to the main universe and
# the engine went after the RUNNING main backend's owner.lock → readiness
# FAILED → /route 503. The env must win again (the dedicated resolver
# ``_default_data_dir`` reads it first). tmp_path is used for both sides
# because the dedicated resolver mkdirs the winning path.

def test_data_dir_env_beats_config_file(monkeypatch, tmp_path):
    """The 2026-09-17 regression: file pins data_dir, GAOTTT_DATA_DIR env
    must still win (dedicated resolver, env-first)."""
    env_side = tmp_path / "env-side"
    file_side = tmp_path / "file-side"
    monkeypatch.delenv("GAOTTT_DATA_DIR", raising=False)
    monkeypatch.delenv("GER_RAG_DATA_DIR", raising=False)
    monkeypatch.setenv("GAOTTT_DATA_DIR", str(env_side))
    monkeypatch.setattr(
        "gaottt.config._load_config_file",
        lambda: {"data_dir": str(file_side)},
    )
    cfg = GaOTTTConfig.from_config_file()
    assert Path(cfg.data_dir).resolve() == env_side.resolve()
    # the dedicated resolver mkdirs the env side; the pinned side is untouched
    assert env_side.exists()
    assert not file_side.exists()


def test_data_dir_config_file_wins_without_env(monkeypatch, tmp_path):
    """No env → the config-file data_dir stays effective (existing
    behaviour preserved)."""
    file_side = tmp_path / "file-side"
    monkeypatch.delenv("GAOTTT_DATA_DIR", raising=False)
    monkeypatch.delenv("GER_RAG_DATA_DIR", raising=False)
    monkeypatch.setattr(
        "gaottt.config._load_config_file",
        lambda: {"data_dir": str(file_side)},
    )
    cfg = GaOTTTConfig.from_config_file()
    assert Path(cfg.data_dir).resolve() == file_side.resolve()


def test_data_dir_legacy_ger_rag_env_beats_config_file(monkeypatch, tmp_path):
    """Legacy GER_RAG_DATA_DIR also wins over the file value when
    GAOTTT_DATA_DIR is unset (same dedicated-resolver priority)."""
    env_side = tmp_path / "legacy-env-side"
    file_side = tmp_path / "file-side"
    monkeypatch.delenv("GAOTTT_DATA_DIR", raising=False)
    monkeypatch.setenv("GER_RAG_DATA_DIR", str(env_side))
    monkeypatch.setattr(
        "gaottt.config._load_config_file",
        lambda: {"data_dir": str(file_side)},
    )
    cfg = GaOTTTConfig.from_config_file()
    assert Path(cfg.data_dir).resolve() == env_side.resolve()
    assert env_side.exists()


def test_data_dir_provenance_env_file_default(monkeypatch, tmp_path):
    """resolve_config_with_sources reports the true data_dir source:
    env (env + file) / file (file only) / default (neither)."""
    env_side = tmp_path / "env-side"
    file_side = tmp_path / "file-side"
    file_conf = {"data_dir": str(file_side)}
    monkeypatch.delenv("GAOTTT_DATA_DIR", raising=False)
    monkeypatch.delenv("GER_RAG_DATA_DIR", raising=False)

    # env + file -> "env"
    monkeypatch.setenv("GAOTTT_DATA_DIR", str(env_side))
    monkeypatch.setattr(
        "gaottt.config._load_config_file", lambda: dict(file_conf),
    )
    cfg, sources = GaOTTTConfig.resolve_config_with_sources()
    assert sources["data_dir"] == "env"
    assert Path(cfg.data_dir).resolve() == env_side.resolve()

    # file only -> "file"
    monkeypatch.delenv("GAOTTT_DATA_DIR", raising=False)
    cfg, sources = GaOTTTConfig.resolve_config_with_sources()
    assert sources["data_dir"] == "file"
    assert Path(cfg.data_dir).resolve() == file_side.resolve()

    # neither -> "default"
    monkeypatch.setattr("gaottt.config._load_config_file", lambda: {})
    _, sources = GaOTTTConfig.resolve_config_with_sources()
    assert sources["data_dir"] == "default"


def test_data_dir_env_provenance_when_file_absent(monkeypatch, tmp_path):
    """File sets another field but NOT data_dir + GAOTTT_DATA_DIR env ->
    env side wins and provenance is "env" (the dedicated resolver ran —
    not "default", which heuristic guessing would misreport)."""
    env_side = tmp_path / "env-side"
    monkeypatch.delenv("GAOTTT_DATA_DIR", raising=False)
    monkeypatch.delenv("GER_RAG_DATA_DIR", raising=False)
    monkeypatch.setenv("GAOTTT_DATA_DIR", str(env_side))
    monkeypatch.setattr(
        "gaottt.config._load_config_file",
        lambda: {"gamma": 0.3},  # other field only — no data_dir key
    )
    cfg = GaOTTTConfig.from_config_file()
    assert Path(cfg.data_dir).resolve() == env_side.resolve()
    assert cfg.gamma == 0.3  # file-only field still applies
    assert env_side.exists()  # dedicated resolver mkdirs the winner
    _, provenance = GaOTTTConfig.resolve_config_with_sources()
    assert provenance["data_dir"] == "env"


def test_data_dir_empty_string_env_treated_as_unset(monkeypatch, tmp_path):
    """GAOTTT_DATA_DIR="" is not an override — the file value wins. Same
    semantics as _default_data_dir's ``if env:`` — an empty string is
    unset, so the file beats the (empty) env."""
    file_side = tmp_path / "file-side"
    monkeypatch.delenv("GER_RAG_DATA_DIR", raising=False)
    monkeypatch.setenv("GAOTTT_DATA_DIR", "")
    monkeypatch.setattr(
        "gaottt.config._load_config_file",
        lambda: {"data_dir": str(file_side)},
    )
    cfg = GaOTTTConfig.from_config_file()
    assert Path(cfg.data_dir).resolve() == file_side.resolve()


def test_data_dir_empty_gaottt_env_falls_back_to_legacy(monkeypatch, tmp_path):
    """GAOTTT_DATA_DIR="" + GER_RAG_DATA_DIR set -> the legacy env wins
    over the file value ("" is unset, so the legacy fallback applies in
    both the override popper and the dedicated resolver)."""
    legacy_side = tmp_path / "legacy-env-side"
    file_side = tmp_path / "file-side"
    monkeypatch.setenv("GAOTTT_DATA_DIR", "")
    monkeypatch.setenv("GER_RAG_DATA_DIR", str(legacy_side))
    monkeypatch.setattr(
        "gaottt.config._load_config_file",
        lambda: {"data_dir": str(file_side)},
    )
    cfg = GaOTTTConfig.from_config_file()
    assert Path(cfg.data_dir).resolve() == legacy_side.resolve()
    assert legacy_side.exists()
    assert not file_side.exists()
