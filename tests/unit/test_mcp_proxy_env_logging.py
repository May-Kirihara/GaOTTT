"""Fix 2 tests: backend env inheritance visibility in mcp_proxy.

Tests spawn and connect paths emit the correct log messages about GAOTTT_*
env var names. No subprocess is actually spawned — _spawn_backend_detached
and _probe_backend are mocked.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest


@pytest.fixture
def clean_env(monkeypatch):
    for k in list(os.environ):
        if k.startswith("GAOTTT_"):
            monkeypatch.delenv(k, raising=False)


@pytest.mark.asyncio
async def test_spawn_path_logs_env_names(caplog, clean_env, tmp_path):
    os.environ["GAOTTT_FOO"] = "secret"
    os.environ["GAOTTT_BAR"] = "also-secret"
    try:
        from gaottt.server.mcp_proxy import _ensure_backend

        with (
            patch(
                "gaottt.server.mcp_proxy._probe_backend",
                side_effect=[False, True],
            ),
            patch(
                "gaottt.server.mcp_proxy._port_in_use",
                return_value=False,
            ),
            patch(
                "gaottt.server.mcp_proxy._spawn_backend_detached",
                return_value=12345,
            ),
            patch(
                "gaottt.server.mcp_proxy.asyncio.sleep",
                new_callable=AsyncMock,
            ),
        ):
            with caplog.at_level(logging.INFO, logger="gaottt.server.mcp_proxy"):
                url = await _ensure_backend(
                    host="127.0.0.1",
                    port=7878,
                    idle_timeout=300,
                    spawn_log_path=tmp_path / "backend.log",
                    readiness_timeout=5.0,
                )

        assert url == "http://127.0.0.1:7878/mcp"
        assert any(
            "GAOTTT_FOO" in r.message and "GAOTTT_BAR" in r.message
            for r in caplog.records
            if "Spawning backend with GAOTTT_*" in r.message
        )
    finally:
        del os.environ["GAOTTT_FOO"]
        del os.environ["GAOTTT_BAR"]


@pytest.mark.asyncio
async def test_connect_path_warns_local_env(caplog, clean_env):
    os.environ["GAOTTT_CUSTOM_TUNING"] = "x"
    try:
        from gaottt.server.mcp_proxy import _ensure_backend

        with patch(
            "gaottt.server.mcp_proxy._probe_backend",
            new_callable=AsyncMock,
            return_value=True,
        ):
            with caplog.at_level(logging.WARNING, logger="gaottt.server.mcp_proxy"):
                url = await _ensure_backend(
                    host="127.0.0.1",
                    port=7878,
                    idle_timeout=300,
                    spawn_log_path=Path("/tmp/dummy.log"),
                )

        assert url == "http://127.0.0.1:7878/mcp"
        assert any(
            "GAOTTT_CUSTOM_TUNING" in r.message
            for r in caplog.records
            if "NOT applied" in r.message
        )
    finally:
        del os.environ["GAOTTT_CUSTOM_TUNING"]


@pytest.mark.asyncio
async def test_connect_no_env_no_warning(caplog, clean_env):
    from gaottt.server.mcp_proxy import _ensure_backend

    with patch(
        "gaottt.server.mcp_proxy._probe_backend",
        new_callable=AsyncMock,
        return_value=True,
    ):
        with caplog.at_level(logging.WARNING, logger="gaottt.server.mcp_proxy"):
            url = await _ensure_backend(
                host="127.0.0.1",
                port=7878,
                idle_timeout=300,
                spawn_log_path=Path("/tmp/dummy.log"),
            )

    assert url == "http://127.0.0.1:7878/mcp"
    assert not any(
        "NOT applied" in r.message for r in caplog.records
    )
