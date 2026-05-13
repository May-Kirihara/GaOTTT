"""GaOTTT MCP stdio→HTTP proxy with auto-spawn backend.

Architecture (cold-war dead-man-switch pattern):

  agent (Claude Code / opencode / ...)
    ↓ stdio
  this proxy  ← lightweight, one per agent
    ↓ HTTP (streamable-http MCP)
  gaottt backend  ← heavy, ONE process shared by all proxies

The proxy:
  1. On startup, probes ``http://<host>:<port>/mcp`` for a live backend.
  2. If absent, spawns ``mcp_server --transport streamable-http`` as a
     detached subprocess (survives the proxy's death — other proxies can
     keep using it) and polls until ready.
  3. Opens an MCP ClientSession to the backend and runs a stdio Server
     that forwards every request to the upstream session. No tool
     definitions are duplicated — tools / prompts / resources are
     discovered dynamically from the upstream so the proxy works for
     any tool list without code changes.
  4. Sends an MCP ``ping`` to the backend every ``ping_interval`` seconds
     (default 60) so the backend's idle watchdog (default 300s) doesn't
     consider the system idle as long as at least one proxy is alive.

When the agent disconnects, this proxy exits naturally. The backend
stays alive until ALL proxies stop pinging for ``idle_timeout`` seconds
(cold-war fail-safe: no key turn → stand down).

Race on simultaneous proxy startup is handled by the spawn step: the
``streamable-http`` backend binds to the port atomically; the second
proxy's spawn fails with ``Address already in use`` and falls through
to the "connect to existing" path.
"""
from __future__ import annotations

import asyncio
import logging
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

from mcp import ClientSession, types
from mcp.client.streamable_http import streamablehttp_client
from mcp.server import Server
from mcp.server.stdio import stdio_server

logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------
# Backend lifecycle
# -----------------------------------------------------------------------

def _port_in_use(host: str, port: int) -> bool:
    """Cheap TCP probe — does someone hold ``host:port``?"""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            s.connect((host, port))
            return True
    except OSError:
        return False


async def _probe_backend(url: str, timeout: float = 5.0) -> bool:
    """Open an MCP session against ``url`` and try ``initialize``.

    Returns True iff the backend answers a valid initialize response.
    Used both for the initial existence check and for spawn-readiness
    polling.
    """
    try:
        async with streamablehttp_client(url) as (read, write, _):
            async with ClientSession(read, write) as session:
                await asyncio.wait_for(session.initialize(), timeout=timeout)
                return True
    except Exception:  # noqa: BLE001 — any failure means "not ready"
        return False


def _spawn_backend_detached(
    host: str,
    port: int,
    idle_timeout: float,
    log_path: Path,
) -> int:
    """Launch a detached ``mcp_server --transport streamable-http`` subprocess.

    Returns the PID. The subprocess is fully detached: its stdin is
    DEVNULL, stdout / stderr go to ``log_path``, and it gets a new
    session so it survives the proxy's death.
    """
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_file = open(log_path, "a", buffering=1)
    log_file.write(
        f"\n--- backend spawn at {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n"
    )
    cmd = [
        sys.executable,
        "-m",
        "gaottt.server.mcp_server",
        "--transport",
        "streamable-http",
        "--host",
        host,
        "--port",
        str(port),
        "--idle-timeout",
        str(idle_timeout),
    ]
    # Linux/macOS: start_new_session detaches. Windows: DETACHED_PROCESS.
    popen_kwargs: dict = {
        "stdin": subprocess.DEVNULL,
        "stdout": log_file,
        "stderr": subprocess.STDOUT,
    }
    if sys.platform == "win32":
        popen_kwargs["creationflags"] = (
            subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
        )
    else:
        popen_kwargs["start_new_session"] = True
    proc = subprocess.Popen(cmd, **popen_kwargs)  # noqa: S603 — controlled args
    return proc.pid


async def _ensure_backend(
    host: str,
    port: int,
    idle_timeout: float,
    spawn_log_path: Path,
    readiness_timeout: float = 90.0,
) -> str:
    """Return a usable backend URL, spawning if necessary.

    Resolution order:
      1. If ``host:port`` already has a live MCP backend → return URL.
      2. If port is in use but doesn't answer MCP → assume a stranger
         is on the port, error out (we won't overwrite).
      3. Else spawn detached + poll until ready (max ``readiness_timeout``
         seconds, giving RURI load + virtual FAISS rebuild headroom).
    """
    url = f"http://{host}:{port}/mcp"
    if await _probe_backend(url, timeout=3.0):
        logger.info("GaOTTT backend already up at %s — connecting", url)
        return url

    if _port_in_use(host, port):
        raise RuntimeError(
            f"Port {host}:{port} is taken but not by a GaOTTT MCP backend. "
            "Check what's listening (`lsof -i :{port}`) or pick a different "
            "port via --port."
        )

    logger.info(
        "GaOTTT backend not running; spawning detached subprocess "
        "(idle_timeout=%ds, log=%s)",
        int(idle_timeout), spawn_log_path,
    )
    pid = _spawn_backend_detached(host, port, idle_timeout, spawn_log_path)
    logger.info("Spawned backend pid=%d, waiting for readiness ...", pid)

    deadline = time.monotonic() + readiness_timeout
    poll_interval = 1.0
    while time.monotonic() < deadline:
        if await _probe_backend(url, timeout=3.0):
            elapsed = readiness_timeout - (deadline - time.monotonic())
            logger.info("Backend ready after %.1fs at %s", elapsed, url)
            return url
        await asyncio.sleep(poll_interval)
    raise RuntimeError(
        f"Backend pid={pid} did not become ready within {readiness_timeout}s. "
        f"Check {spawn_log_path} for startup errors."
    )


# -----------------------------------------------------------------------
# stdio ↔ HTTP forwarder
# -----------------------------------------------------------------------

async def _ping_loop(session: ClientSession, interval: float) -> None:
    """Cold-war heartbeat — refresh the backend's idle timer.

    Any incoming request from this proxy also resets the timer, but
    when the agent is silent for a while only these pings prevent
    backend shutdown. ``session.send_ping`` is a no-op at the protocol
    level — just signal that this side is still around.
    """
    while True:
        try:
            await asyncio.sleep(interval)
            await session.send_ping()
            logger.debug("backend ping ok")
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            # Backend may have shut down or crashed; the main forwarder
            # will hit the same error and exit. Don't spam logs.
            logger.warning("backend ping failed: %s", exc)
            break


def _build_proxy_server(upstream: ClientSession, instructions: str | None) -> Server:
    """Create a low-level Server that forwards every request type to
    ``upstream``.

    Instead of using FastMCP's decorator-based API (which wraps return
    values into specific MCP types and would force us to unwrap+rewrap
    the upstream's already-built results), we register raw request
    handlers on ``proxy.request_handlers`` that return ``ServerResult``
    directly. Pass-through is perfect: every field of the upstream's
    response makes it back to the agent unmodified — schemas, hidden
    fields, future MCP types we haven't seen yet.

    ``PingRequest`` is left to the default handler that the lowlevel
    Server pre-registers; it just returns an empty result. The proxy's
    periodic ``send_ping`` to the *upstream* keeps the backend warm
    independently.
    """
    proxy = Server("gaottt", instructions=instructions or "")

    async def list_tools(_req: types.ListToolsRequest) -> types.ServerResult:
        return types.ServerResult(await upstream.list_tools())

    async def call_tool(req: types.CallToolRequest) -> types.ServerResult:
        result = await upstream.call_tool(
            req.params.name, req.params.arguments or {},
        )
        return types.ServerResult(result)

    async def list_resources(_req: types.ListResourcesRequest) -> types.ServerResult:
        return types.ServerResult(await upstream.list_resources())

    async def list_resource_templates(
        _req: types.ListResourceTemplatesRequest,
    ) -> types.ServerResult:
        return types.ServerResult(await upstream.list_resource_templates())

    async def read_resource(req: types.ReadResourceRequest) -> types.ServerResult:
        return types.ServerResult(await upstream.read_resource(req.params.uri))

    async def list_prompts(_req: types.ListPromptsRequest) -> types.ServerResult:
        return types.ServerResult(await upstream.list_prompts())

    async def get_prompt(req: types.GetPromptRequest) -> types.ServerResult:
        return types.ServerResult(
            await upstream.get_prompt(req.params.name, req.params.arguments or {})
        )

    proxy.request_handlers[types.ListToolsRequest] = list_tools
    proxy.request_handlers[types.CallToolRequest] = call_tool
    proxy.request_handlers[types.ListResourcesRequest] = list_resources
    proxy.request_handlers[types.ListResourceTemplatesRequest] = list_resource_templates
    proxy.request_handlers[types.ReadResourceRequest] = read_resource
    proxy.request_handlers[types.ListPromptsRequest] = list_prompts
    proxy.request_handlers[types.GetPromptRequest] = get_prompt

    return proxy


async def _proxy_session(url: str, ping_interval: float, instructions: str | None) -> None:
    """Connect to backend, run the stdio proxy, until the agent disconnects."""
    async with streamablehttp_client(url) as (read, write, _):
        async with ClientSession(read, write) as upstream:
            init_result = await upstream.initialize()
            upstream_instructions = (
                init_result.instructions if instructions is None else instructions
            )
            logger.info("Proxy connected to backend; serving stdio")

            ping_task = asyncio.create_task(_ping_loop(upstream, ping_interval))

            try:
                proxy_server = _build_proxy_server(upstream, upstream_instructions)
                async with stdio_server() as (stdio_read, stdio_write):
                    await proxy_server.run(
                        stdio_read,
                        stdio_write,
                        proxy_server.create_initialization_options(),
                    )
            finally:
                ping_task.cancel()
                try:
                    await ping_task
                except (asyncio.CancelledError, Exception):  # noqa: BLE001
                    pass


# -----------------------------------------------------------------------
# Public entrypoint
# -----------------------------------------------------------------------

DEFAULT_PORT = 7878
DEFAULT_HOST = "127.0.0.1"
DEFAULT_IDLE_TIMEOUT = 300.0   # backend self-shutdown after 5 minutes of silence
DEFAULT_PING_INTERVAL = 60.0   # proxy heartbeat cadence


def _spawn_log_path() -> Path:
    """Where to redirect spawned backend stdout/stderr.

    Uses XDG_STATE_HOME if set, else ``~/.local/state/gaottt/``. Keeps
    the spawn log out of the data directory so a wipe of data_dir
    doesn't lose startup diagnostics.
    """
    xdg_state = os.environ.get("XDG_STATE_HOME")
    base = Path(xdg_state) if xdg_state else Path.home() / ".local" / "state"
    return base / "gaottt" / "backend.log"


async def run_proxy(
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    idle_timeout: float = DEFAULT_IDLE_TIMEOUT,
    ping_interval: float = DEFAULT_PING_INTERVAL,
) -> None:
    """High-level entrypoint: ensure backend, run stdio proxy."""
    url = await _ensure_backend(
        host=host,
        port=port,
        idle_timeout=idle_timeout,
        spawn_log_path=_spawn_log_path(),
    )
    await _proxy_session(url, ping_interval=ping_interval, instructions=None)
