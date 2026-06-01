"""Concurrency regression suite for the stdio→HTTP proxy.

Guards the 2026-06-01 "Session terminated" bug: the single upstream
streamable-http ``ClientSession`` cannot survive concurrent in-flight
requests — two simultaneous POSTs break it and every later call fails
until reconnect. The fix (``_Upstream`` holder) serializes all upstream
access on one in-flight request and rebuilds-and-retries once on a
session-terminated error.

These tests drive ``_Upstream`` directly with a fake session (no backend
/ no network), so they assert the serialization + reconnect invariants
without a live engine.
Handover: docs/maintainers/handover-2026-06-01-concurrent-recall-session-termination.md
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import anyio
import pytest
from mcp import types
from mcp.shared.exceptions import McpError

from gaottt.server.mcp_proxy import _Upstream, _is_session_dead


class _Tracker:
    def __init__(self) -> None:
        self.cur = 0
        self.peak = 0


class _FakeSession:
    """Stands in for the upstream ClientSession. Tracks peak concurrent
    in-flight calls so a test can assert serialization."""

    def __init__(self, tracker: _Tracker, *, fail_first_terminated: bool = False,
                 raise_exc: BaseException | None = None) -> None:
        self._tracker = tracker
        self._fail_first_terminated = fail_first_terminated
        self._raise_exc = raise_exc
        self.calls = 0

    async def _tracked(self):
        self._tracker.cur += 1
        self._tracker.peak = max(self._tracker.peak, self._tracker.cur)
        try:
            await asyncio.sleep(0.01)  # widen the interleave window
        finally:
            self._tracker.cur -= 1

    async def call_tool(self, name, args):
        self.calls += 1
        if self._fail_first_terminated and self.calls == 1:
            raise McpError(types.ErrorData(code=32600, message="Session terminated"))
        if self._raise_exc is not None:
            raise self._raise_exc
        await self._tracked()
        return types.CallToolResult(
            content=[types.TextContent(type="text", text="ok")]
        )

    async def send_ping(self):
        await self._tracked()


def _make_upstream(session, *, serialize=True, auto_reconnect=True) -> _Upstream:
    up = _Upstream(
        "http://127.0.0.1:7878/mcp",
        host="127.0.0.1",
        port=7878,
        idle_timeout=0.0,
        spawn_log_path=Path("/tmp/gaottt-test-proxy.log"),
        serialize=serialize,
        auto_reconnect=auto_reconnect,
        instructions_override=None,
    )
    up._session = session
    return up


def test_is_session_dead_classification():
    assert _is_session_dead(McpError(types.ErrorData(code=32600, message="Session terminated")))
    assert _is_session_dead(anyio.ClosedResourceError())
    assert _is_session_dead(anyio.BrokenResourceError())
    assert _is_session_dead(ConnectionError("connection refused"))
    # A genuine application/protocol error must NOT be treated as a dead session.
    assert not _is_session_dead(McpError(types.ErrorData(code=-32601, message="Method not found")))
    assert not _is_session_dead(ValueError("nope"))


@pytest.mark.asyncio
async def test_upstream_serializes_concurrent_calls():
    """With the lock, 3 concurrent call_tool never overlap in-flight."""
    tracker = _Tracker()
    up = _make_upstream(_FakeSession(tracker), serialize=True)
    results = await asyncio.gather(*[
        up.call("call_tool", "recall", {"query": f"q{i}"}) for i in range(3)
    ])
    assert tracker.peak == 1, f"upstream calls overlapped (peak={tracker.peak})"
    assert len(results) == 3
    assert all(not r.isError for r in results)


@pytest.mark.asyncio
async def test_upstream_no_lock_allows_overlap():
    """Demonstrates the bug: without serialization the calls overlap in-flight
    (this is what breaks the real streamable-http session)."""
    tracker = _Tracker()
    up = _make_upstream(_FakeSession(tracker), serialize=False)
    await asyncio.gather(*[
        up.call("call_tool", "recall", {"query": f"q{i}"}) for i in range(3)
    ])
    assert tracker.peak >= 2, "expected overlap without the serialization lock"


@pytest.mark.asyncio
async def test_ping_shares_lock_with_calls():
    """A ping never runs in-flight alongside a tool call (same lock)."""
    tracker = _Tracker()
    up = _make_upstream(_FakeSession(tracker), serialize=True)
    await asyncio.gather(
        up.call("call_tool", "recall", {"query": "q"}),
        up.ping(),
        up.call("call_tool", "recall", {"query": "q2"}),
    )
    assert tracker.peak == 1


@pytest.mark.asyncio
async def test_reconnects_once_on_session_terminated():
    """A 'Session terminated' error transparently rebuilds + retries once."""
    tracker = _Tracker()
    dead = _FakeSession(tracker, fail_first_terminated=True)
    healthy = _FakeSession(tracker)
    up = _make_upstream(dead, serialize=True, auto_reconnect=True)

    reconnects = {"n": 0}

    async def _fake_reconnect():
        reconnects["n"] += 1
        up._session = healthy   # swap to a healthy session (no network)

    up._reconnect_locked = _fake_reconnect  # type: ignore[assignment]

    result = await up.call("call_tool", "recall", {"query": "q"})
    assert reconnects["n"] == 1, "should have reconnected exactly once"
    assert not result.isError
    assert up._session is healthy


@pytest.mark.asyncio
async def test_does_not_reconnect_on_application_error():
    """A non-session error (e.g. Method not found) propagates, no reconnect."""
    tracker = _Tracker()
    boom = McpError(types.ErrorData(code=-32601, message="Method not found"))
    up = _make_upstream(_FakeSession(tracker, raise_exc=boom), serialize=True,
                        auto_reconnect=True)

    reconnects = {"n": 0}

    async def _fake_reconnect():
        reconnects["n"] += 1

    up._reconnect_locked = _fake_reconnect  # type: ignore[assignment]

    with pytest.raises(McpError):
        await up.call("call_tool", "recall", {"query": "q"})
    assert reconnects["n"] == 0, "must not reconnect on an application error"
